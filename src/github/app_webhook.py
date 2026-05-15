"""Lightweight GitHub App webhook server.

Minimal FastAPI server that handles GitHub App webhook events using
the standalone review engine. No Postgres/Redis required — just the
App credentials and an LLM API key.

Supports all commands: auto-review, /review, /fix, /ask, /generate-tests
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import traceback
from pathlib import Path

from fastapi import FastAPI, Request, Response

from src.config import ReviewConfig
from src.github.app_auth import GitHubAppAuth, verify_webhook_signature
from src.github.client import GitHubAPI
from src.review.engine import ReviewEngine
from src.review.formatter import build_github_review_comments, format_review_body

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="AI Code Reviewer", docs_url=None, redoc_url=None)

_app_auth: GitHubAppAuth | None = None
_webhook_secret: str = ""


def _get_auth() -> GitHubAppAuth:
    global _app_auth
    if _app_auth is None:
        app_id = os.environ["GITHUB_APP_ID"]
        private_key_path = os.getenv("GITHUB_PRIVATE_KEY_PATH", "")
        private_key = os.getenv("GITHUB_PRIVATE_KEY", "")

        if private_key_path and Path(private_key_path).exists():
            private_key = Path(private_key_path).read_text()

        if not private_key:
            raise RuntimeError("Set GITHUB_PRIVATE_KEY or GITHUB_PRIVATE_KEY_PATH")

        _app_auth = GitHubAppAuth(app_id, private_key)
    return _app_auth


def _get_webhook_secret() -> str:
    global _webhook_secret
    if not _webhook_secret:
        _webhook_secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    return _webhook_secret


# ── Health ───────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "mode": "github-app"}


# ── Webhook endpoint ────────────────────────────────────────────────────────


@app.post("/webhooks/github")
async def handle_webhook(request: Request) -> Response:
    """Handle GitHub App webhook events."""
    body = await request.body()

    # Verify signature
    secret = _get_webhook_secret()
    if secret:
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not verify_webhook_signature(body, signature, secret):
            logger.warning("Invalid webhook signature")
            return Response(status_code=401, content="Invalid signature")

    event_type = request.headers.get("X-GitHub-Event", "")
    event = await request.json()

    if event_type == "ping":
        logger.info(f"Ping received from app: {event.get('app_id', '?')}")
        return Response(status_code=200, content="pong")

    if event_type == "installation":
        action = event.get("action", "")
        installer = event.get("sender", {}).get("login", "?")
        logger.info(f"Installation {action} by {installer}")
        return Response(status_code=200)

    if event_type == "pull_request":
        action = event.get("action", "")
        if action in ("opened", "synchronize", "reopened"):
            asyncio.create_task(_handle_pr_review(event))
            return Response(status_code=202, content="queued")

    if (
        event_type == "issue_comment"
        and event.get("action") == "created"
        and event.get("issue", {}).get("pull_request")
    ):
        comment_body = (event.get("comment", {}).get("body") or "").strip()
        if comment_body.startswith(("/review", "/fix", "/ask", "/generate-tests")):
            asyncio.create_task(_handle_command(event, comment_body))
            return Response(status_code=202, content="queued")

    if event_type == "pull_request_review_comment" and event.get("action") == "created":
        comment = event.get("comment", {})
        user = comment.get("user", {}).get("login", "")
        if not user.endswith("[bot]") and comment.get("in_reply_to_id"):
            asyncio.create_task(_handle_chat_reply(event))
            return Response(status_code=202, content="queued")

    return Response(status_code=200, content="ignored")


# ── Event handlers ──────────────────────────────────────────────────────────


async def _get_github_client(installation_id: int) -> GitHubAPI:
    """Create a GitHubAPI client authenticated as the App installation."""
    auth = _get_auth()
    token = await auth.get_installation_token(installation_id)
    return GitHubAPI(token)


def _get_installation_id(event: dict) -> int:
    """Extract installation ID from webhook event."""
    return event.get("installation", {}).get("id", 0)


async def _handle_pr_review(event: dict) -> None:
    """Handle automatic PR review on open/sync."""
    pr_data = event["pull_request"]
    repo = event["repository"]["full_name"]
    pr_number = pr_data["number"]
    installation_id = _get_installation_id(event)

    if pr_data.get("draft", False):
        logger.info(f"PR #{pr_number} is a draft, skipping")
        return

    github = await _get_github_client(installation_id)
    try:
        await _run_review(github, repo, pr_number)
    except Exception as e:
        logger.error(f"Review failed for PR #{pr_number}: {e}")
        traceback.print_exc()
        with contextlib.suppress(Exception):
            await github.post_comment(
                repo,
                pr_number,
                f"## AI Code Review\n\nReview failed: `{type(e).__name__}: {e}`",
            )
    finally:
        await github.close()


async def _handle_command(event: dict, comment_body: str) -> None:
    """Handle /review, /fix, /ask, /generate-tests commands."""
    repo = event["repository"]["full_name"]
    pr_number = event["issue"]["number"]
    installation_id = _get_installation_id(event)

    github = await _get_github_client(installation_id)
    try:
        if comment_body.startswith("/fix"):
            await _run_fix(github, repo, pr_number)
        elif comment_body.startswith("/ask"):
            question = comment_body[4:].strip()
            if question:
                await _run_ask(github, repo, pr_number, question)
        elif comment_body.startswith("/generate-tests"):
            await _run_generate_tests(github, repo, pr_number)
        elif comment_body.startswith("/review"):
            await _run_review(github, repo, pr_number)
    except Exception as e:
        cmd = comment_body.split()[0]
        logger.error(f"{cmd} failed on PR #{pr_number}: {e}")
        traceback.print_exc()
        with contextlib.suppress(Exception):
            await github.post_comment(
                repo,
                pr_number,
                f"## AI Code Reviewer\n\n`{cmd}` failed: `{type(e).__name__}: {e}`",
            )
    finally:
        await github.close()


async def _handle_chat_reply(event: dict) -> None:
    """Handle reply to a review comment thread."""
    from src.review.chat import ChatEngine, format_chat_response

    repo = event["repository"]["full_name"]
    pr_data = event["pull_request"]
    pr_number = pr_data["number"]
    comment = event["comment"]
    installation_id = _get_installation_id(event)

    github = await _get_github_client(installation_id)
    try:
        config = _load_config()
        pr = await github.get_pr(repo, pr_number)

        app_info = await _get_auth().get_app_info()
        bot_username = f"{app_info.get('slug', 'ai-code-reviewer')}[bot]"

        chat_engine = ChatEngine(config)
        chat_result = await chat_engine.reply_to_thread(
            github=github,
            repo=repo,
            pr=pr,
            comment_id=comment["in_reply_to_id"],
            user_message=comment["body"],
            bot_username=bot_username,
        )

        reply_body = format_chat_response(chat_result)
        await github.reply_to_review_comment(repo, pr_number, comment["in_reply_to_id"], reply_body)
        logger.info(f"Chat reply posted on PR #{pr_number}")
    except Exception as e:
        logger.error(f"Chat reply failed on PR #{pr_number}: {e}")
        traceback.print_exc()
    finally:
        await github.close()


# ── Core operations ──────────────────────────────────────────────────────────


def _load_config() -> ReviewConfig:
    """Load review config from env vars + .pr-reviewer.yml."""
    config = ReviewConfig.from_env()
    yml_path = Path(".pr-reviewer.yml")
    if yml_path.exists():
        config = ReviewConfig.from_yaml(yml_path, base=config)
    return config


async def _run_review(github: GitHubAPI, repo: str, pr_number: int) -> None:
    """Run a full PR review."""
    config = _load_config()
    engine = ReviewEngine(config)

    pr = await github.get_pr(repo, pr_number)

    # Skip ignored titles
    for pattern in config.ignore_titles:
        if pattern.lower() in pr.title.lower():
            logger.info(f"PR title matches ignore pattern '{pattern}', skipping")
            return

    files = await github.get_pr_files(repo, pr_number)
    if not files:
        return

    diff = await github.get_pr_diff(repo, pr_number)

    logger.info(
        f"Reviewing PR #{pr_number}: '{pr.title}' "
        f"({len(files)} files, "
        f"+{sum(f.additions for f in files)}/-{sum(f.deletions for f in files)})"
    )

    result = await engine.review_pr(pr, files, diff)

    body = format_review_body(result)
    inline_comments = build_github_review_comments(result)

    if inline_comments:
        try:
            await github.post_review(
                repo,
                pr_number,
                body,
                inline_comments,
                event="COMMENT",
                commit_id=pr.head_sha,
            )
        except Exception:
            await github.post_comment(repo, pr_number, body)
            await github.post_inline_comments(
                repo,
                pr_number,
                pr.head_sha,
                inline_comments,
            )
    else:
        await github.post_comment(repo, pr_number, body)

    if config.label_pr and result.labels:
        with contextlib.suppress(Exception):
            await github.add_labels(repo, pr_number, result.labels)

    logger.info(
        f"Review complete: {len(result.comments)} comments, "
        f"risk={result.risk_level}, cost=${result.cost_usd:.4f}"
    )


async def _run_fix(github: GitHubAPI, repo: str, pr_number: int) -> None:
    """Run /fix command."""
    from src.review.fixer import format_fix_comment, run_fix

    config = _load_config()
    pr = await github.get_pr(repo, pr_number)

    fix_summary = await run_fix(
        github=github,
        config=config,
        repo=repo,
        pr_number=pr_number,
        head_ref=pr.head_ref,
        head_sha=pr.head_sha,
    )

    await github.post_comment(repo, pr_number, format_fix_comment(fix_summary))
    logger.info(f"/fix complete: {fix_summary.files_fixed} files fixed")


async def _run_ask(github: GitHubAPI, repo: str, pr_number: int, question: str) -> None:
    """Run /ask command."""
    from src.review.chat import ChatEngine, format_chat_response

    config = _load_config()
    pr = await github.get_pr(repo, pr_number)
    files = await github.get_pr_files(repo, pr_number)
    diff = await github.get_pr_diff(repo, pr_number)

    chat_engine = ChatEngine(config)
    chat_result = await chat_engine.answer_question(
        pr=pr,
        files=files,
        diff=diff,
        user_message=question,
    )

    await github.post_comment(repo, pr_number, format_chat_response(chat_result))
    logger.info(f"/ask answered on PR #{pr_number}")


async def _run_generate_tests(github: GitHubAPI, repo: str, pr_number: int) -> None:
    """Run /generate-tests command."""
    from src.review.test_generator import format_test_gen_comment, generate_tests

    config = _load_config()
    pr = await github.get_pr(repo, pr_number)
    files = await github.get_pr_files(repo, pr_number)

    test_summary = await generate_tests(
        github=github,
        config=config,
        repo=repo,
        pr_number=pr_number,
        head_ref=pr.head_ref,
        files=files,
    )

    await github.post_comment(repo, pr_number, format_test_gen_comment(test_summary))
    logger.info(f"/generate-tests: {test_summary.total_tests} tests generated")
