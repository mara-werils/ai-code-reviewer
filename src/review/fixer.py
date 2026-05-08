"""Fix engine — generates code fixes from review comments and commits them.

Flow:
1. Collect review comments from the last AI review
2. Group by file
3. For each file: send current content + comments to LLM → get fixed content
4. Commit each fix via GitHub API
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from src.config import ReviewConfig
from src.github.client import GitHubAPI
from src.providers import LLMProvider, create_provider

logger = logging.getLogger(__name__)

FIX_SYSTEM_PROMPT = """You are an expert programmer. You fix code issues identified in code reviews.

Rules:
1. Apply ONLY the fixes described in the review comments. Do not refactor or change anything else.
2. Return the COMPLETE file content with fixes applied. Not a diff, not a snippet — the full file.
3. Preserve all existing formatting, comments, imports, and structure.
4. If a fix would break other parts of the code, skip it and note it in the skipped array.
5. Be precise and minimal. Change only what's needed to fix each issue."""

FIX_PROMPT = """Fix the issues in this file based on the review comments.

## File: {path}

```{language}
{content}
```

## Review Comments to Fix
{comments_text}

Respond with JSON:
{{
  "fixed_content": "the complete fixed file content as a string",
  "applied": ["short description of each fix applied"],
  "skipped": ["short description of any issues skipped and why"]
}}

IMPORTANT:
- Return the COMPLETE file content in fixed_content, not a diff
- Preserve exact indentation and formatting
- Only fix the issues listed above, nothing else
- ONLY output JSON, no other text"""


@dataclass
class FixResult:
    """Result of fixing a single file."""

    path: str
    applied: list[str]
    skipped: list[str]
    commit_sha: str


@dataclass
class FixSummary:
    """Summary of all fixes applied to a PR."""

    files_fixed: int
    total_applied: int
    total_skipped: int
    fixes: list[FixResult]
    cost_usd: float


def _extract_ai_review_comments(
    review_comments: list[dict],
    issue_comments: list[dict],
) -> dict[str, list[dict]]:
    """Extract fixable comments from the last AI review, grouped by file path.

    Looks at both inline review comments and parses the summary comment
    for issues listed there.
    """
    by_file: dict[str, list[dict]] = {}

    # Inline review comments from AI Code Reviewer
    for c in review_comments:
        body = c.get("body", "")
        # Our inline comments contain severity markers
        if not any(marker in body for marker in ["[CRITICAL]", "[WARNING]", "[SUGGESTION]"]):
            continue

        path = c.get("path", "")
        if not path:
            continue

        line = c.get("original_line") or c.get("line") or 0
        if path not in by_file:
            by_file[path] = []
        by_file[path].append(
            {
                "line": line,
                "body": body,
                "severity": _extract_severity(body),
            }
        )

    # Also check summary comments for general issues
    for c in issue_comments:
        body = c.get("body", "")
        if not body.startswith("## AI Code Review"):
            continue
        # Extract file references from general comments section
        for match in re.finditer(
            r"\[(?:CRITICAL|WARNING|SUGGESTION)\]\s+\*\*([^*]+)\*\*:\s+(.+)",
            body,
        ):
            path = match.group(1)
            comment_body = match.group(2)
            if path not in by_file:
                by_file[path] = []
            by_file[path].append(
                {
                    "line": 0,
                    "body": comment_body,
                    "severity": "warning",
                }
            )

    return by_file


def _extract_severity(body: str) -> str:
    """Extract severity from a review comment body."""
    if "[CRITICAL]" in body:
        return "critical"
    if "[WARNING]" in body:
        return "warning"
    if "[SUGGESTION]" in body:
        return "suggestion"
    return "info"


def _detect_language(path: str) -> str:
    """Detect language from file extension."""
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".jsx": "jsx",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".rb": "ruby",
        ".php": "php",
        ".cs": "csharp",
        ".cpp": "cpp",
        ".c": "c",
        ".swift": "swift",
        ".kt": "kotlin",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".md": "markdown",
        ".sh": "bash",
    }
    for ext, lang in ext_map.items():
        if path.endswith(ext):
            return lang
    return ""


async def run_fix(
    github: GitHubAPI,
    config: ReviewConfig,
    repo: str,
    pr_number: int,
    head_ref: str,
    head_sha: str,
) -> FixSummary:
    """Run the /fix command: collect review comments, generate fixes, commit them.

    Args:
        github: GitHub API client
        config: Review config (for LLM provider)
        repo: Repository full name (owner/repo)
        pr_number: PR number
        head_ref: PR head branch name
        head_sha: Current head commit SHA

    Returns:
        FixSummary with all applied and skipped fixes
    """
    provider: LLMProvider = create_provider(config)
    total_cost = 0.0

    # 1. Collect review comments
    review_comments = await github.get_review_comments(repo, pr_number)
    issue_comments = await github.get_issue_comments(repo, pr_number)

    comments_by_file = _extract_ai_review_comments(review_comments, issue_comments)

    if not comments_by_file:
        return FixSummary(
            files_fixed=0,
            total_applied=0,
            total_skipped=0,
            fixes=[],
            cost_usd=0,
        )

    # Filter to only fixable severities (critical + warning)
    fixable_files: dict[str, list[dict]] = {}
    for path, comments in comments_by_file.items():
        fixable = [c for c in comments if c["severity"] in ("critical", "warning", "suggestion")]
        if fixable:
            fixable_files[path] = fixable

    if not fixable_files:
        return FixSummary(
            files_fixed=0,
            total_applied=0,
            total_skipped=0,
            fixes=[],
            cost_usd=0,
        )

    logger.info(
        f"/fix: Found {sum(len(v) for v in fixable_files.values())} issues in {len(fixable_files)} files"
    )

    # 2. For each file: get content, generate fix, commit
    fixes: list[FixResult] = []

    for path, comments in fixable_files.items():
        try:
            # Get current file content
            content = await github.get_file_content(repo, path, head_ref)
            if not content:
                logger.warning(f"/fix: Could not read {path}, skipping")
                fixes.append(
                    FixResult(path=path, applied=[], skipped=["File not found"], commit_sha="")
                )
                continue

            # Build comments text
            comments_text = ""
            for i, c in enumerate(comments, 1):
                line_info = f" (line {c['line']})" if c["line"] else ""
                comments_text += f"{i}. [{c['severity'].upper()}]{line_info}: {c['body']}\n\n"

            language = _detect_language(path)

            # Generate fix via LLM
            messages = [
                {"role": "system", "content": FIX_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": FIX_PROMPT.format(
                        path=path,
                        language=language,
                        content=content[:25000],
                        comments_text=comments_text,
                    ),
                },
            ]

            response = await provider.complete(
                messages=messages,
                temperature=0.05,
                max_tokens=8192,
                json_mode=True,
            )
            total_cost += response.cost_usd

            # Parse response
            try:
                text = response.content.strip()
                json_match = re.search(r"\{.*\}", text, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                else:
                    data = json.loads(text)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"/fix: Failed to parse LLM response for {path}: {e}")
                fixes.append(
                    FixResult(
                        path=path,
                        applied=[],
                        skipped=["Failed to parse AI response"],
                        commit_sha="",
                    )
                )
                continue

            fixed_content = data.get("fixed_content", "")
            applied = data.get("applied", [])
            skipped = data.get("skipped", [])

            if not fixed_content or not applied:
                fixes.append(
                    FixResult(
                        path=path,
                        applied=[],
                        skipped=skipped or ["No fixes generated"],
                        commit_sha="",
                    )
                )
                continue

            # Ensure file ends with newline
            if not fixed_content.endswith("\n"):
                fixed_content += "\n"

            # Commit the fix
            file_sha = await github.get_file_sha(repo, path, head_ref)

            applied_summary = "; ".join(applied[:3])
            commit_msg = f"fix({path.split('/')[-1]}): {applied_summary}"
            if len(commit_msg) > 72:
                commit_msg = commit_msg[:69] + "..."

            commit_sha = await github.create_or_update_file(
                repo=repo,
                path=path,
                content=fixed_content,
                message=commit_msg,
                branch=head_ref,
                file_sha=file_sha,
            )

            logger.info(f"/fix: Fixed {path} ({len(applied)} fixes) → {commit_sha[:8]}")
            fixes.append(
                FixResult(path=path, applied=applied, skipped=skipped, commit_sha=commit_sha)
            )

        except Exception as e:
            logger.error(f"/fix: Failed to fix {path}: {e}")
            fixes.append(FixResult(path=path, applied=[], skipped=[f"Error: {e}"], commit_sha=""))

    return FixSummary(
        files_fixed=sum(1 for f in fixes if f.commit_sha),
        total_applied=sum(len(f.applied) for f in fixes),
        total_skipped=sum(len(f.skipped) for f in fixes),
        fixes=fixes,
        cost_usd=total_cost,
    )


def format_fix_comment(summary: FixSummary) -> str:
    """Format the /fix result as a GitHub comment."""
    if summary.total_applied == 0:
        parts = [
            "## AI Code Fix",
            "",
            "No fixable issues found in the last review. "
            "Run `/review` first, then `/fix` to auto-apply fixes.",
        ]
        return "\n".join(parts)

    parts = [
        "## AI Code Fix",
        "",
        f"Applied **{summary.total_applied} fixes** across **{summary.files_fixed} files**.",
        "",
    ]

    for fix in summary.fixes:
        if fix.applied:
            parts.append(f"### `{fix.path}`")
            for a in fix.applied:
                parts.append(f"- {a}")
            if fix.skipped:
                parts.append(f"  - _Skipped: {'; '.join(fix.skipped)}_")
            parts.append(f"  - Commit: `{fix.commit_sha[:8]}`")
            parts.append("")
        elif fix.skipped:
            parts.append(f"### `{fix.path}` (skipped)")
            for s in fix.skipped:
                parts.append(f"- _{s}_")
            parts.append("")

    parts.extend(
        [
            "---",
            f"<sub>Cost: ${summary.cost_usd:.4f} | "
            f"[AI Code Reviewer](https://github.com/mara-werils/ai-code-reviewer)</sub>",
        ]
    )

    return "\n".join(parts)
