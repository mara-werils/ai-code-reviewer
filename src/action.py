"""GitHub Action entrypoint — runs when triggered by a PR event."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
import traceback
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

    # Detect event type: pull_request or issue_comment (/review command)
    pr_data = event.get("pull_request")
    comment_data = event.get("comment")
    repo = event["repository"]["full_name"]

    is_fix_command = False

    if comment_data and event.get("issue", {}).get("pull_request"):
        # On-demand command triggered by /review or /fix comment
        comment_body = (comment_data.get("body") or "").strip()

        if comment_body.startswith("/fix"):
            is_fix_command = True
            pr_number = event["issue"]["number"]
            logger.info(f"/fix command triggered on PR #{pr_number}")
        elif comment_body.startswith("/review"):
            pr_number = event["issue"]["number"]
            logger.info(f"On-demand review triggered by /review comment on PR #{pr_number}")
        else:
            logger.info("Comment is not a /review or /fix command, skipping")
            return
    elif pr_data:
        pr_number = pr_data["number"]

        # Skip drafts
        if pr_data.get("draft", False):
            logger.info(f"PR #{pr_number} is a draft, skipping")
            return
    else:
        logger.info("Not a pull_request or /review comment event, skipping")
        return

    # Load config
    config = ReviewConfig.from_env()

    # Check for .pr-reviewer.yml in the repo
    yml_path = Path(".pr-reviewer.yml")
    if yml_path.exists():
        config = ReviewConfig.from_yaml(yml_path, base=config)

    # Skip by title patterns (only for PR events, not issue_comment)
    if pr_data:
        title = pr_data.get("title", "")
        for pattern in config.ignore_titles:
            if pattern.lower() in title.lower():
                logger.info(f"PR title matches ignore pattern '{pattern}', skipping")
                return

    if not config.api_key and config.provider != "ollama":
        provider = config.provider
        key_names = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "groq": "GROQ_API_KEY",
            "google": "GOOGLE_API_KEY",
        }
        key_name = key_names.get(provider, f"{provider.upper()}_API_KEY")
        logger.error(
            f"No API key for provider '{provider}'. "
            f"Add {key_name} to your repository secrets and pass it via env:\n\n"
            f"  env:\n"
            f"    {key_name}: ${{{{ secrets.{key_name} }}}}"
        )
        sys.exit(1)

    if not config.github_token:
        logger.error(
            "GITHUB_TOKEN not set. Add this to your workflow:\n\n"
            "  permissions:\n"
            "    contents: read\n"
            "    pull-requests: write"
        )
        sys.exit(1)

    # Initialize
    github = GitHubAPI(config.github_token)

    try:
        # Get PR info
        pr = await github.get_pr(repo, pr_number)

        # --- /fix command ---
        if is_fix_command:
            from src.review.fixer import format_fix_comment, run_fix

            logger.info(f"Running /fix on PR #{pr_number}")
            fix_summary = await run_fix(
                github=github,
                config=config,
                repo=repo,
                pr_number=pr_number,
                head_ref=pr.head_ref,
                head_sha=pr.head_sha,
            )

            comment_body = format_fix_comment(fix_summary)
            await github.post_comment(repo, pr_number, comment_body)

            logger.info(
                f"/fix complete: {fix_summary.files_fixed} files fixed, "
                f"{fix_summary.total_applied} fixes applied, "
                f"cost=${fix_summary.cost_usd:.4f}"
            )
            return

        # --- /review and auto-review ---
        engine = ReviewEngine(config)

        files = await github.get_pr_files(repo, pr_number)

        if not files:
            logger.info(f"PR #{pr_number} has no files, skipping")
            return

        diff = await github.get_pr_diff(repo, pr_number)

        logger.info(
            f"Reviewing PR #{pr_number}: '{pr.title}' "
            f"({len(files)} files, "
            f"+{sum(f.additions for f in files)}/-{sum(f.deletions for f in files)})"
        )

        # Check if we already reviewed this SHA (skip for on-demand /review)
        is_on_demand = comment_data is not None
        if not is_on_demand:
            try:
                existing = await github.get_existing_reviews(repo, pr_number)
                for review in existing:
                    body = review.get("body") or ""
                    if (
                        body.startswith("## AI Code Review")
                        and review.get("commit_id") == pr.head_sha
                    ):
                        logger.info(f"Already reviewed commit {pr.head_sha[:8]}, skipping")
                        return
            except Exception:
                pass  # Non-critical, proceed with review

        # Run review
        result = await engine.review_pr(pr, files, diff)

        # Format output
        body = format_review_body(result)
        inline_comments = build_github_review_comments(result)

        # Post review
        if inline_comments:
            # Try batch review first
            try:
                await github.post_review(
                    repo,
                    pr_number,
                    body,
                    inline_comments,
                    event="COMMENT",
                    commit_id=pr.head_sha,
                )
                logger.info(f"Posted review with {len(inline_comments)} inline comments")
            except Exception as e:
                logger.warning(f"Batch review failed: {e}")
                # Fallback: post summary + individual inline comments
                await github.post_comment(repo, pr_number, body)
                posted = await github.post_inline_comments(
                    repo,
                    pr_number,
                    pr.head_sha,
                    inline_comments,
                )
                logger.info(f"Posted summary + {posted}/{len(inline_comments)} inline comments")
        else:
            await github.post_comment(repo, pr_number, body)
            logger.info("Posted review summary (no inline comments)")

        # Add labels
        if config.label_pr and result.labels:
            try:
                await github.add_labels(repo, pr_number, result.labels)
                logger.info(f"Added labels: {result.labels}")
            except Exception as e:
                logger.warning(f"Failed to add labels: {e}")

        # Collect feedback from previous reviews (reactions on old comments)
        try:
            from src.review.feedback import (
                collect_feedback_from_reactions,
                load_feedback,
                save_feedback,
            )

            prev_comments = await github.get_review_comments(repo, pr_number)
            bot_user = os.getenv("GITHUB_ACTOR", "github-actions[bot]")
            new_feedback = collect_feedback_from_reactions(prev_comments, bot_user)

            if new_feedback:
                store = load_feedback()
                store.repo = repo
                for entry in new_feedback:
                    entry.pr_number = pr_number
                    store.add(entry)
                save_feedback(store)
                logger.info(f"Collected {len(new_feedback)} feedback signals")
        except Exception as e:
            logger.debug(f"Feedback collection skipped: {e}")

        # Set outputs for GitHub Actions
        _set_output("summary", result.summary)
        _set_output("risk_level", result.risk_level)
        _set_output("comments_count", str(len(result.comments)))
        _set_output("cost_usd", f"{result.cost_usd:.4f}")

        logger.info(
            f"Review complete: {len(result.comments)} comments, "
            f"risk={result.risk_level}, cost=${result.cost_usd:.4f}"
        )

    except Exception as e:
        cmd = "/fix" if is_fix_command else "Review"
        logger.error(f"{cmd} failed: {e}")
        traceback.print_exc()
        # Try to post a failure comment so the user knows
        with contextlib.suppress(Exception):
            await github.post_comment(
                repo,
                pr_number,
                f"## AI Code {cmd}\n\n{cmd} failed: `{type(e).__name__}: {e}`\n\n"
                f"Check the [Action logs]({os.getenv('GITHUB_SERVER_URL', 'https://github.com')}"
                f"/{repo}/actions) for details.",
            )
        sys.exit(1)
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
