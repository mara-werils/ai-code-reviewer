"""PR description generator — auto-generates comprehensive PR descriptions.

Uses LLM to analyze the diff and generate a structured PR description
including summary, changes list, testing notes, and migration steps.
Triggered by /describe comment command.
"""

from __future__ import annotations

import json
import logging
import re

from src.config import ReviewConfig
from src.github.client import GitHubAPI, PRFile, PRInfo
from src.providers import LLMProvider, create_provider
from src.review.analyzer import build_diff_text, filter_files

logger = logging.getLogger(__name__)

DESCRIBE_SYSTEM_PROMPT = """You are an expert at writing clear, informative pull request descriptions.
Analyze the code diff and generate a comprehensive PR description.

Rules:
1. Be concise but thorough
2. Focus on WHAT changed and WHY (infer intent from code)
3. Group related changes logically
4. Mention any breaking changes, new dependencies, or migration needs
5. Use markdown formatting"""

DESCRIBE_PROMPT = """Generate a PR description for this pull request.

## PR Title: {title}
## Author: {author}
## Current Description: {body}

## Files Changed
{files_summary}

## Diff
{diff}

Respond with JSON:
{{
  "summary": "1-2 sentence high-level summary",
  "motivation": "Why this change is needed",
  "changes": ["List of specific changes made"],
  "type": "feature|bugfix|refactor|docs|chore|test|perf|ci",
  "breaking_changes": ["List of breaking changes, or empty array"],
  "testing": "How to test these changes",
  "migration_notes": "Migration steps if needed, or empty string",
  "related_issues": ["Detected issue references like #123"],
  "risk_level": "low|medium|high"
}}"""


async def generate_description(
    config: ReviewConfig,
    pr: PRInfo,
    files: list[PRFile],
    diff: str | None = None,
) -> dict:
    """Generate a PR description from the diff."""
    provider = create_provider(config)

    filtered = filter_files(files, config.ignore_paths)
    if not filtered:
        return {"summary": "No reviewable files in this PR."}

    if not diff:
        diff = build_diff_text(filtered, max_size=config.max_diff_size)
    else:
        diff = diff[: config.max_diff_size]

    files_summary = "\n".join(f"- `{f.filename}` (+{f.additions}/-{f.deletions})" for f in filtered[:30])

    messages = [
        {"role": "system", "content": DESCRIBE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": DESCRIBE_PROMPT.format(
                title=pr.title,
                author=pr.author,
                body=(pr.body or "No description")[:1000],
                files_summary=files_summary,
                diff=diff,
            ),
        },
    ]

    response = await provider.complete(
        messages=messages,
        temperature=0.2,
        max_tokens=2048,
        json_mode=True,
    )

    try:
        text = response.content.strip()
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {"summary": response.content[:500]}


def format_pr_description(data: dict) -> str:
    """Format generated description into markdown."""
    parts = []

    # Summary
    summary = data.get("summary", "")
    if summary:
        parts.append(f"## Summary")
        parts.append(f"{summary}")
        parts.append("")

    # Motivation
    motivation = data.get("motivation", "")
    if motivation:
        parts.append(f"## Motivation")
        parts.append(f"{motivation}")
        parts.append("")

    # Type badge
    pr_type = data.get("type", "")
    if pr_type:
        type_emoji = {
            "feature": "✨", "bugfix": "🐛", "refactor": "♻️",
            "docs": "📝", "chore": "🔧", "test": "✅",
            "perf": "⚡", "ci": "🔄",
        }
        emoji = type_emoji.get(pr_type, "📋")
        parts.append(f"**Type:** {emoji} {pr_type.capitalize()}")
        parts.append("")

    # Changes
    changes = data.get("changes", [])
    if changes:
        parts.append("## Changes")
        for change in changes:
            parts.append(f"- {change}")
        parts.append("")

    # Breaking changes
    breaking = data.get("breaking_changes", [])
    if breaking:
        parts.append("## ⚠️ Breaking Changes")
        for bc in breaking:
            parts.append(f"- {bc}")
        parts.append("")

    # Testing
    testing = data.get("testing", "")
    if testing:
        parts.append("## Testing")
        parts.append(testing)
        parts.append("")

    # Migration notes
    migration = data.get("migration_notes", "")
    if migration:
        parts.append("## Migration Notes")
        parts.append(migration)
        parts.append("")

    # Risk level
    risk = data.get("risk_level", "")
    if risk:
        risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}
        parts.append(f"**Risk:** {risk_emoji.get(risk, '⚪')} {risk.capitalize()}")

    # Related issues
    issues = data.get("related_issues", [])
    if issues:
        parts.append("")
        parts.append("**Related:** " + ", ".join(issues))

    return "\n".join(parts)


async def handle_describe_command(
    config: ReviewConfig,
    github: GitHubAPI,
    repo: str,
    pr_number: int,
) -> None:
    """Handle /describe command — generate and update PR description."""
    pr = await github.get_pr(repo, pr_number)
    files = await github.get_pr_files(repo, pr_number)

    data = await generate_description(config, pr, files)
    description = format_pr_description(data)

    # Update the PR description
    await github.update_pr(repo, pr_number, body=description)

    # Post confirmation comment
    await github.post_comment(
        repo,
        pr_number,
        "✅ PR description generated and updated by AI Code Reviewer.\n\n"
        f"*Type: {data.get('type', 'unknown')} | "
        f"Risk: {data.get('risk_level', 'unknown')}*",
    )

    logger.info(f"Generated description for PR #{pr_number}")
