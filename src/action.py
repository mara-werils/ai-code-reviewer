"""GitHub Action entrypoint — runs when triggered by a PR event."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from src.config import ReviewConfig
from src.github.client import GitHubAPI
from src.review.engine import ReviewEngine
from src.review.formatter import build_github_review_comments, format_review_body

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def run_action() -> None:
    """Main GitHub Action logic."""
    # Load event
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    if not event_path or not Path(event_path).exists():
        logger.error("GITHUB_EVENT_PATH not set or file not found")
        sys.exit(1)

    with open(event_path) as f:
        event = json.load(f)

    # Check if this is a PR event
    pr_data = event.get("pull_request")
    if not pr_data:
        logger.info("Not a pull_request event, skipping")
        return

    pr_number = pr_data["number"]
    repo = event["repository"]["full_name"]

    # Skip drafts
    if pr_data.get("draft", False):
        logger.info(f"PR #{pr_number} is a draft, skipping")
        return

    # Load config
    config = ReviewConfig.from_env()

    # Check for .pr-reviewer.yml in the repo
    yml_path = Path(".pr-reviewer.yml")
    if yml_path.exists():
        config = ReviewConfig.from_yaml(yml_path, base=config)

    # Skip by title patterns
    title = pr_data.get("title", "")
    for pattern in config.ignore_titles:
        if pattern.lower() in title.lower():
            logger.info(f"PR title matches ignore pattern '{pattern}', skipping")
            return

    if not config.api_key and config.provider != "ollama":
        logger.error(
            f"No API key found for provider '{config.provider}'. "
            f"Set the appropriate secret (e.g., OPENAI_API_KEY)."
        )
        sys.exit(1)

    if not config.github_token:
        logger.error("GITHUB_TOKEN not set. Required for posting reviews.")
        sys.exit(1)

    # Initialize
    github = GitHubAPI(config.github_token)
    engine = ReviewEngine(config)

    try:
        # Get PR info
        pr = await github.get_pr(repo, pr_number)
        files = await github.get_pr_files(repo, pr_number)
        diff = await github.get_pr_diff(repo, pr_number)

        logger.info(
            f"Reviewing PR #{pr_number}: '{pr.title}' "
            f"({len(files)} files, +{sum(f.additions for f in files)}/-{sum(f.deletions for f in files)})"
        )

        # Check if we already reviewed this SHA
        existing = await github.get_existing_reviews(repo, pr_number)
        for review in existing:
            if review.get("body", "").startswith("## 🔍 AI Code Review") and review.get("commit_id") == pr.head_sha:
                    logger.info(f"Already reviewed commit {pr.head_sha[:8]}, skipping")
                    return

        # Run review
        result = await engine.review_pr(pr, files, diff)

        # Format output
        body = format_review_body(result)
        inline_comments = build_github_review_comments(result)

        # Post review
        if inline_comments:
            await github.post_review(
                repo, pr_number, body, inline_comments, event="COMMENT"
            )
            logger.info(f"Posted review with {len(inline_comments)} inline comments")
        else:
            await github.post_comment(repo, pr_number, body)
            logger.info("Posted review summary (no inline comments)")

        # Add labels
        if config.label_pr and result.labels:
            await github.add_labels(repo, pr_number, result.labels)
            logger.info(f"Added labels: {result.labels}")

        # Set outputs for GitHub Actions
        _set_output("summary", result.summary)
        _set_output("risk_level", result.risk_level)
        _set_output("comments_count", str(len(result.comments)))
        _set_output("cost_usd", f"{result.cost_usd:.4f}")

        logger.info(
            f"✅ Review complete: {len(result.comments)} comments, "
            f"risk={result.risk_level}, cost=${result.cost_usd:.4f}"
        )

    finally:
        await github.close()


def _set_output(name: str, value: str) -> None:
    """Set GitHub Action output."""
    output_file = os.getenv("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"{name}={value}\n")


def main() -> None:
    asyncio.run(run_action())


if __name__ == "__main__":
    main()
