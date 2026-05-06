import time
from typing import Any
from uuid import UUID

import structlog
from arq import func
from sqlalchemy import select, update

from app.db.models import Review
from app.db.session import async_session_factory
from app.services.github_client import GitHubClient
from app.services.reviewer.graph import build_review_graph
from app.services.reviewer.state import ReviewState
from app.workers.arq_settings import get_redis_settings

logger = structlog.get_logger()


async def process_review(
    ctx: dict[str, Any],
    review_id: str,
    repo_id: str,
    repo_full_name: str,
    pr_number: int,
    head_sha: str,
    installation_id: int,
) -> None:
    """Main worker task: run the review LangGraph agent."""
    logger.info(
        "review_processing_start",
        review_id=review_id,
        repo=repo_full_name,
        pr=pr_number,
    )
    start = time.monotonic()

    async with async_session_factory() as session:
        try:
            # Update status
            await session.execute(
                update(Review).where(Review.id == UUID(review_id)).values(status="running")
            )
            await session.commit()

            # Fetch PR data
            github = GitHubClient()
            try:
                diff = await github.get_pull_request_diff(
                    repo_full_name, pr_number, installation_id
                )
                files = await github.get_pull_request_files(
                    repo_full_name, pr_number, installation_id
                )
            finally:
                await github.close()

            # Build and run graph
            graph = build_review_graph(session)
            compiled = graph.compile()

            initial_state: ReviewState = {
                "review_id": UUID(review_id),
                "repository_id": UUID(repo_id),
                "pr_number": pr_number,
                "pr_diff": diff,
                "pr_title": "",  # Will be filled from DB
                "pr_body": None,
                "changed_files": files,
                "identifiers_in_diff": [],
                "classification": None,
                "risk_level": None,
                "messages": [],
                "tool_calls_count": 0,
                "cost_spent_usd": 0.0,
                "final_summary": None,
                "final_comments": [],
                "status": "running",
                "installation_id": installation_id,
                "repo_full_name": repo_full_name,
            }

            # Load PR title from DB
            result = await session.execute(select(Review).where(Review.id == UUID(review_id)))
            review = result.scalar_one_or_none()
            if review and review.pr_title:
                initial_state["pr_title"] = review.pr_title

            await compiled.ainvoke(initial_state)

            duration_ms = int((time.monotonic() - start) * 1000)
            await session.execute(
                update(Review).where(Review.id == UUID(review_id)).values(duration_ms=duration_ms)
            )
            await session.commit()

            logger.info(
                "review_processing_complete",
                review_id=review_id,
                duration_ms=duration_ms,
            )

        except Exception as e:
            logger.error(
                "review_processing_failed",
                review_id=review_id,
                error=str(e),
            )
            await session.execute(
                update(Review)
                .where(Review.id == UUID(review_id))
                .values(status="failed", error_message=str(e)[:500])
            )
            await session.commit()
            raise


class WorkerSettings:
    """ARQ worker settings."""

    redis_settings = get_redis_settings()
    functions = [func(process_review, name="process_review")]
    max_jobs = 5
    job_timeout = 300  # 5 minutes
    queue_name = "reviews"
