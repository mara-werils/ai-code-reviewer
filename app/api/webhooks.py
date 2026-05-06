from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, Request, Response
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_cached_settings, get_db, get_redis
from app.config import Settings
from app.core.exceptions import WebhookValidationError
from app.core.security import verify_webhook_signature
from app.db.models import Feedback, Repository, Review, ReviewComment

logger = structlog.get_logger()

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/github", status_code=202)
async def github_webhook(
    request: Request,
    x_hub_signature_256: str = Header(...),
    x_github_event: str = Header(...),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_cached_settings),
) -> dict[str, str]:
    payload = await request.body()

    try:
        verify_webhook_signature(payload, x_hub_signature_256, settings.github_webhook_secret)
    except WebhookValidationError:
        logger.warning("webhook_signature_invalid")
        return Response(status_code=401, content="Invalid signature")  # type: ignore[return-value]

    body = await request.json()

    if x_github_event == "ping":
        logger.info("webhook_ping", zen=body.get("zen"))
        return {"status": "pong"}

    if x_github_event == "pull_request":
        action = body.get("action")
        if action in ("opened", "reopened", "synchronize"):
            return await _handle_pull_request(body, db, redis)

    if x_github_event == "pull_request_review_comment":
        return await _handle_review_comment(body, db)

    return {"status": "ignored"}


async def _handle_pull_request(
    body: dict[str, Any],
    db: AsyncSession,
    redis: Redis,
) -> dict[str, str]:
    pr = body["pull_request"]
    repo_data = body["repository"]
    repo_full_name = repo_data["full_name"]
    pr_number = pr["number"]
    head_sha = pr["head"]["sha"]
    installation_id = body.get("installation", {}).get("id", 0)

    logger.info(
        "webhook_pr_event",
        repo=repo_full_name,
        pr=pr_number,
        sha=head_sha,
        action=body["action"],
    )

    # Ensure repository exists
    result = await db.execute(
        select(Repository).where(Repository.github_full_name == repo_full_name)
    )
    repo = result.scalar_one_or_none()
    if not repo:
        repo = Repository(
            github_full_name=repo_full_name,
            installation_id=installation_id,
        )
        db.add(repo)
        await db.flush()

    # Create review record
    review = Review(
        repository_id=repo.id,
        pr_number=pr_number,
        pr_head_sha=head_sha,
        pr_title=pr.get("title"),
        status="queued",
    )
    db.add(review)
    await db.flush()

    # Enqueue task in Redis
    task_data = {
        "review_id": str(review.id),
        "repo_id": str(repo.id),
        "repo_full_name": repo_full_name,
        "pr_number": pr_number,
        "head_sha": head_sha,
        "installation_id": installation_id,
    }
    await redis.rpush("queue:reviews", str(task_data))  # type: ignore[misc]

    logger.info("review_enqueued", review_id=str(review.id), pr=pr_number)
    return {"status": "queued", "review_id": str(review.id)}


async def _handle_review_comment(
    body: dict[str, Any],
    db: AsyncSession,
) -> dict[str, str]:
    comment = body.get("comment", {})
    action = body.get("action")

    if action != "created":
        return {"status": "ignored"}

    github_comment_id = comment.get("id")
    user_login = comment.get("user", {}).get("login", "")
    comment_body = comment.get("body", "")

    # Check if this is a reply to one of our comments
    in_reply_to = comment.get("in_reply_to_id")
    if in_reply_to:
        result = await db.execute(
            select(ReviewComment).where(ReviewComment.github_comment_id == in_reply_to)
        )
        review_comment = result.scalar_one_or_none()
        if review_comment:
            feedback = Feedback(
                review_comment_id=review_comment.id,
                feedback_type="reply",
                reply_text=comment_body,
                github_user_login=user_login,
            )
            db.add(feedback)
            logger.info(
                "feedback_recorded",
                type="reply",
                github_comment_id=github_comment_id,
            )

    return {"status": "ok"}
