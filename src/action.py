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
from src.review.chat import ChatEngine, format_chat_response
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

    # Detect event type
    pr_data = event.get("pull_request")
    comment_data = event.get("comment")
    repo = event["repository"]["full_name"]
    event_name = os.getenv("GITHUB_EVENT_NAME", "")

    is_fix_command = False
    is_ask_command = False
    is_chat_reply = False
    is_test_gen_command = False
    ask_question = ""
    chat_comment_id = 0
    chat_user_message = ""

    if event_name == "pull_request_review_comment" and comment_data:
        # Reply to a review comment thread — potential chat interaction
        comment_body = (comment_data.get("body") or "").strip()
        comment_user = comment_data.get("user", {}).get("login", "")
        in_reply_to = comment_data.get("in_reply_to_id")

        # Skip bot's own comments to avoid infinite loops
        if comment_user.endswith("[bot]") or _is_bot_user(comment_user):
            logger.info("Ignoring bot's own comment to avoid loop")
            return

        if in_reply_to:
            # This is a reply in a thread — check if the thread involves our bot
            is_chat_reply = True
            chat_comment_id = in_reply_to
            chat_user_message = comment_body
            pr_number = event.get("pull_request", {}).get("number", 0)
            logger.info(f"Chat reply detected on PR #{pr_number}, thread #{in_reply_to}")
        else:
            logger.info("Review comment is not a thread reply, skipping")
            return

    elif comment_data and event.get("issue", {}).get("pull_request"):
        # On-demand command triggered by /review, /fix, or /ask comment
        comment_body = (comment_data.get("body") or "").strip()

        if comment_body.startswith("/fix"):
            is_fix_command = True
            pr_number = event["issue"]["number"]
            logger.info(f"/fix command triggered on PR #{pr_number}")
        elif comment_body.startswith("/review"):
            pr_number = event["issue"]["number"]
            logger.info(f"On-demand review triggered by /review comment on PR #{pr_number}")
        elif comment_body.startswith("/ask"):
            is_ask_command = True
            ask_question = comment_body[4:].strip()
            if not ask_question:
                logger.info("/ask command with no question, skipping")
                return
            pr_number = event["issue"]["number"]
            logger.info(f"/ask command triggered on PR #{pr_number}")
        elif comment_body.startswith("/generate-tests"):
            is_test_gen_command = True
            pr_number = event["issue"]["number"]
            logger.info(f"/generate-tests command triggered on PR #{pr_number}")
        else:
            logger.info("Comment is not a recognized command, skipping")
            return
    elif pr_data:
        pr_number = pr_data["number"]

        # Skip drafts
        if pr_data.get("draft", False):
            logger.info(f"PR #{pr_number} is a draft, skipping")
            return
    else:
        logger.info("Not a recognized event, skipping")
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

        # --- Chat: reply to review comment thread ---
        if is_chat_reply:
            bot_username = os.getenv("GITHUB_ACTOR", "github-actions[bot]")
            chat_engine = ChatEngine(config)

            chat_result = await chat_engine.reply_to_thread(
                github=github,
                repo=repo,
                pr=pr,
                comment_id=chat_comment_id,
                user_message=chat_user_message,
                bot_username=bot_username,
            )

            reply_body = format_chat_response(chat_result)
            await github.reply_to_review_comment(repo, pr_number, chat_comment_id, reply_body)

            logger.info(
                f"Chat reply posted on PR #{pr_number}, "
                f"cost=${chat_result.cost_usd:.4f}"
            )
            return

        # --- /ask command ---
        if is_ask_command:
            files = await github.get_pr_files(repo, pr_number)
            diff = await github.get_pr_diff(repo, pr_number)

            chat_engine = ChatEngine(config)
            chat_result = await chat_engine.answer_question(
                pr=pr,
                files=files,
                diff=diff,
                user_message=ask_question,
            )

            reply_body = format_chat_response(chat_result)
            await github.post_comment(repo, pr_number, reply_body)

            logger.info(
                f"/ask answered on PR #{pr_number}, "
                f"cost=${chat_result.cost_usd:.4f}"
            )
            return

        # --- /generate-tests command ---
        if is_test_gen_command:
            from src.review.test_generator import (
                format_test_gen_comment,
                generate_tests,
            )

            files = await github.get_pr_files(repo, pr_number)
            logger.info(f"Running /generate-tests on PR #{pr_number}")

            test_summary = await generate_tests(
                github=github,
                config=config,
                repo=repo,
                pr_number=pr_number,
                head_ref=pr.head_ref,
                files=files,
            )

            comment_body = format_test_gen_comment(test_summary)
            await github.post_comment(repo, pr_number, comment_body)

            logger.info(
                f"/generate-tests complete: {test_summary.total_tests} tests "
                f"in {test_summary.files_with_tests} files, "
                f"cost=${test_summary.cost_usd:.4f}"
            )
            return

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

        # Run rules engine (deterministic, team-defined rules)
        from src.review.rules import evaluate_rules, format_rule_violations, load_rules

        rules_config = load_rules()
        rule_violations = evaluate_rules(rules_config, files)
        rule_comments = format_rule_violations(rule_violations)

        if rule_violations:
            logger.info(f"Rules engine found {len(rule_violations)} violations")

        # Format output
        body = format_review_body(result)
        inline_comments = build_github_review_comments(result)

        # Merge rule-based comments into inline comments
        for rc in rule_comments:
            inline_comments.append(
                {
                    "path": rc["path"],
                    "line": rc["line"],
                    "body": rc["body"],
                }
            )

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


def _is_bot_user(username: str) -> bool:
    """Check if a username belongs to a GitHub Actions bot."""
    bot_names = {"github-actions", "github-actions[bot]", "dependabot", "dependabot[bot]"}
    return username.lower() in bot_names


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
