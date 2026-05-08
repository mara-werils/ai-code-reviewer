"""Pre-commit hook — reviews staged changes before committing.

Runs AI review on `git diff --cached` and reports issues.
Exit code 0 = pass (no critical issues), 1 = fail (critical issues found).

Usage in .pre-commit-config.yaml:
    repos:
      - repo: https://github.com/mara-werils/ai-code-reviewer
        rev: v0.4.0
        hooks:
          - id: ai-code-review

Environment variables:
    OPENAI_API_KEY / ANTHROPIC_API_KEY / GROQ_API_KEY / GOOGLE_API_KEY
    PROVIDER        — LLM provider (default: auto-detect from available key)
    MODEL           — Model override
    REVIEW_STYLE    — concise (default), thorough, minimal
    MAX_COMMENTS    — Max comments (default: 10)
    SEVERITY_THRESHOLD — Block on: critical (default), warning, suggestion
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys

from src.config import ReviewConfig
from src.github.client import PRFile, PRInfo
from src.review.engine import ReviewEngine

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

# ANSI colors
RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
CYAN = "\033[96m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

SEVERITY_ORDER = {"critical": 0, "warning": 1, "suggestion": 2, "info": 3}

SEVERITY_COLORS = {
    "critical": RED,
    "warning": YELLOW,
    "suggestion": GREEN,
    "info": DIM,
}


def get_staged_diff() -> str:
    """Get the staged diff (what will be committed)."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--unified=3"],
        capture_output=True,
        text=True,
    )
    return result.stdout


def get_staged_files() -> list[PRFile]:
    """Get list of staged files with stats."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--numstat"],
        capture_output=True,
        text=True,
    )
    files: list[PRFile] = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        additions = int(parts[0]) if parts[0] != "-" else 0
        deletions = int(parts[1]) if parts[1] != "-" else 0
        filename = parts[2]

        # Get patch for this file
        patch_result = subprocess.run(
            ["git", "diff", "--cached", "--", filename],
            capture_output=True,
            text=True,
        )

        files.append(
            PRFile(
                filename=filename,
                status="modified",
                additions=additions,
                deletions=deletions,
                patch=patch_result.stdout,
            )
        )
    return files


def get_severity_threshold() -> int:
    """Get the severity level that should block the commit."""
    import os

    threshold = os.getenv("SEVERITY_THRESHOLD", "critical").lower()
    return SEVERITY_ORDER.get(threshold, 0)


async def run_hook() -> int:
    """Run the pre-commit review. Returns exit code."""
    diff = get_staged_diff()
    if not diff.strip():
        return 0

    files = get_staged_files()
    if not files:
        return 0

    total_changes = sum(f.additions + f.deletions for f in files)
    print(
        f"{DIM}AI Code Review: scanning {len(files)} files ({total_changes} lines changed)...{RESET}"
    )

    config = ReviewConfig.from_env()

    # Override defaults for hook context
    import os

    max_comments_str = os.getenv("MAX_COMMENTS", "10")
    try:
        config.max_comments = int(max_comments_str)
    except ValueError:
        config.max_comments = 10

    style = os.getenv("REVIEW_STYLE", "concise")
    if style in ("concise", "thorough", "minimal"):
        config.review_style = style

    if not config.api_key and config.provider != "ollama":
        print(f"{YELLOW}AI Code Review: No API key found. Skipping review.{RESET}")
        print(f"{DIM}Set OPENAI_API_KEY, GROQ_API_KEY, or another provider key.{RESET}")
        return 0

    engine = ReviewEngine(config)

    # Build a synthetic PR object
    branch_result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
    )
    branch = branch_result.stdout.strip() or "unknown"

    pr = PRInfo(
        number=0,
        title=f"Pre-commit review ({branch})",
        body="",
        head_sha="staged",
        base_sha="HEAD",
        base_ref="HEAD",
        head_ref=branch,
        repo_full_name="local/repo",
        author="local",
    )

    try:
        result = await engine.review_pr(pr, files, diff)
    except Exception as e:
        print(f"{YELLOW}AI Code Review: Review failed ({e}). Allowing commit.{RESET}")
        return 0

    if not result.comments:
        print(
            f"{GREEN}AI Code Review: No issues found. {RESET}{DIM}(${result.cost_usd:.4f}, {result.duration_ms}ms){RESET}"
        )
        return 0

    # Display results
    threshold = get_severity_threshold()
    blocking_comments = []

    print(f"\n{BOLD}AI Code Review: {len(result.comments)} issues found{RESET}")
    print(
        f"{DIM}Risk: {result.risk_level} | Cost: ${result.cost_usd:.4f} | {result.duration_ms}ms{RESET}\n"
    )

    for c in sorted(result.comments, key=lambda x: SEVERITY_ORDER.get(x.severity, 3)):
        color = SEVERITY_COLORS.get(c.severity, DIM)
        sev = c.severity.upper()
        print(f"  {color}{sev}{RESET} {c.path}:{c.line}")
        # Indent body
        for line in c.body.split("\n"):
            print(f"    {DIM}{line}{RESET}")
        print()

        if SEVERITY_ORDER.get(c.severity, 3) <= threshold:
            blocking_comments.append(c)

    if blocking_comments:
        print(
            f"{RED}{BOLD}Commit blocked: {len(blocking_comments)} issue(s) at or above threshold.{RESET}"
        )
        print(f"{DIM}Fix the issues above or commit with --no-verify to skip.{RESET}")
        print(f"{DIM}Adjust threshold with: SEVERITY_THRESHOLD=warning{RESET}\n")
        return 1

    print(f"{GREEN}All issues below threshold. Commit allowed.{RESET}\n")
    return 0


def main() -> None:
    exit_code = asyncio.run(run_hook())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
