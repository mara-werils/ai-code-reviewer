from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models import AgentToolCall, Feedback, Repository, Review, ReviewComment

logger = structlog.get_logger()

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("")
async def get_stats(
    repo: str = Query(..., description="Repository full name (owner/name)"),
    period: str = Query("30d", description="Period: 7d, 30d, 90d"),
    db: AsyncSession = Depends(get_db),
) -> dict:  # type: ignore[type-arg]
    days = int(period.rstrip("d"))
    since = datetime.now(UTC) - timedelta(days=days)

    # Get repository
    result = await db.execute(
        select(Repository).where(Repository.github_full_name == repo)
    )
    repo_obj = result.scalar_one_or_none()
    if not repo_obj:
        return {"error": "Repository not found"}

    repo_id = repo_obj.id

    # Total PRs reviewed
    total_result = await db.execute(
        select(func.count(Review.id)).where(
            Review.repository_id == repo_id,
            Review.created_at >= since,
            Review.status == "posted",
        )
    )
    total_prs = total_result.scalar() or 0

    # Average cost
    cost_result = await db.execute(
        select(func.avg(Review.total_cost_usd)).where(
            Review.repository_id == repo_id,
            Review.created_at >= since,
            Review.status == "posted",
        )
    )
    avg_cost = float(cost_result.scalar() or 0)

    # Latency percentiles
    latency_result = await db.execute(
        text("""
            SELECT
                percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms) as p50,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) as p95
            FROM reviews
            WHERE repository_id = :repo_id
              AND created_at >= :since
              AND status = 'posted'
              AND duration_ms IS NOT NULL
        """),
        {"repo_id": repo_id, "since": since},
    )
    latency_row = latency_result.fetchone()
    p50_latency = float(latency_row[0] or 0) if latency_row else 0
    p95_latency = float(latency_row[1] or 0) if latency_row else 0

    # Precision (% comments resolved positively)
    positive_result = await db.execute(
        select(func.count(Feedback.id)).where(
            Feedback.feedback_type.in_(["resolved", "thumbs_up"]),
            Feedback.review_comment_id.in_(
                select(ReviewComment.id).join(Review).where(
                    Review.repository_id == repo_id,
                    Review.created_at >= since,
                )
            ),
        )
    )
    positive_count = positive_result.scalar() or 0

    total_feedback_result = await db.execute(
        select(func.count(Feedback.id)).where(
            Feedback.review_comment_id.in_(
                select(ReviewComment.id).join(Review).where(
                    Review.repository_id == repo_id,
                    Review.created_at >= since,
                )
            ),
        )
    )
    total_feedback = total_feedback_result.scalar() or 0
    precision = (positive_count / total_feedback * 100) if total_feedback > 0 else 0

    # Tool call distribution
    tool_dist_result = await db.execute(
        select(AgentToolCall.tool_name, func.count(AgentToolCall.id))
        .join(Review)
        .where(Review.repository_id == repo_id, Review.created_at >= since)
        .group_by(AgentToolCall.tool_name)
    )
    tool_distribution = {row[0]: row[1] for row in tool_dist_result.fetchall()}

    # Cost by day
    cost_by_day_result = await db.execute(
        text("""
            SELECT DATE(created_at) as day, SUM(total_cost_usd) as cost
            FROM reviews
            WHERE repository_id = :repo_id
              AND created_at >= :since
              AND status = 'posted'
            GROUP BY DATE(created_at)
            ORDER BY day
        """),
        {"repo_id": repo_id, "since": since},
    )
    cost_by_day = [
        {"date": str(row[0]), "cost": float(row[1])} for row in cost_by_day_result.fetchall()
    ]

    return {
        "repository": repo,
        "period": period,
        "total_prs_reviewed": total_prs,
        "avg_cost_usd": round(avg_cost, 4),
        "p50_latency_ms": round(p50_latency),
        "p95_latency_ms": round(p95_latency),
        "precision_percent": round(precision, 1),
        "tool_call_distribution": tool_distribution,
        "cost_by_day": cost_by_day,
    }
