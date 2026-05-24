"""Batch review — review multiple PRs at once.

Supports batch reviewing all open PRs in a repo, PRs matching
a filter, or a list of specific PR numbers.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from src.config import ReviewConfig
from src.github.client import GitHubAPI
from src.review.engine import ReviewEngine, ReviewResult

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    """Result of a batch review."""

    pr_number: int
    title: str
    author: str
    result: ReviewResult | None = None
    error: str = ""
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class BatchSummary:
    """Summary of a batch review run."""

    total: int
    reviewed: int
    skipped: int
    failed: int
    results: list[BatchResult] = field(default_factory=list)
    total_cost_usd: float = 0.0
    total_comments: int = 0
    total_critical: int = 0


async def batch_review(
    config: ReviewConfig,
    repo: str,
    pr_numbers: list[int] | None = None,
    labels: list[str] | None = None,
    max_prs: int = 20,
    concurrency: int = 3,
    skip_reviewed: bool = True,
    dry_run: bool = False,
) -> BatchSummary:
    """Review multiple PRs in a repo."""
    github = GitHubAPI(config.github_token)
    engine = ReviewEngine(config)

    # Get PRs to review
    if pr_numbers:
        prs = []
        for num in pr_numbers[:max_prs]:
            try:
                pr = await github.get_pr(repo, num)
                prs.append(pr)
            except Exception as e:
                logger.warning(f"Failed to fetch PR #{num}: {e}")
    else:
        # Get all open PRs
        prs = await github.list_open_prs(repo, max_count=max_prs)

    if labels:
        label_set = set(l.lower() for l in labels)
        prs = [
            pr for pr in prs
            if any(l.lower() in label_set for l in getattr(pr, "labels", []))
        ]

    logger.info(f"Batch review: {len(prs)} PRs to review in {repo}")

    summary = BatchSummary(total=len(prs), reviewed=0, skipped=0, failed=0)
    semaphore = asyncio.Semaphore(concurrency)

    async def review_one(pr) -> BatchResult:
        async with semaphore:
            batch_result = BatchResult(
                pr_number=pr.number,
                title=pr.title,
                author=pr.author,
            )

            # Check if already reviewed
            if skip_reviewed:
                try:
                    comments = await github.get_pr_comments(repo, pr.number)
                    has_review = any(
                        "AI Code Review" in (c.get("body", "") or "")
                        for c in comments
                    )
                    if has_review:
                        batch_result.skipped = True
                        batch_result.skip_reason = "Already reviewed"
                        return batch_result
                except Exception:
                    pass

            if dry_run:
                batch_result.skipped = True
                batch_result.skip_reason = "Dry run"
                return batch_result

            try:
                files = await github.get_pr_files(repo, pr.number)
                result = await engine.review_pr(pr, files)
                batch_result.result = result

                # Post review
                from src.review.formatter import format_review_body, build_github_review_comments

                body = format_review_body(result)
                review_comments = build_github_review_comments(result.comments)
                await github.post_review(
                    repo, pr.number, body, review_comments, pr.head_sha
                )

                logger.info(
                    f"PR #{pr.number}: {len(result.comments)} comments, "
                    f"risk={result.risk_level}, cost=${result.cost_usd:.4f}"
                )

            except Exception as e:
                batch_result.error = str(e)
                logger.error(f"PR #{pr.number} review failed: {e}")

            return batch_result

    # Run reviews with concurrency limit
    tasks = [review_one(pr) for pr in prs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in results:
        if isinstance(r, Exception):
            summary.failed += 1
        elif isinstance(r, BatchResult):
            summary.results.append(r)
            if r.skipped:
                summary.skipped += 1
            elif r.error:
                summary.failed += 1
            elif r.result:
                summary.reviewed += 1
                summary.total_cost_usd += r.result.cost_usd
                summary.total_comments += len(r.result.comments)
                summary.total_critical += sum(
                    1 for c in r.result.comments if c.severity == "critical"
                )

    return summary


def format_batch_summary(summary: BatchSummary) -> str:
    """Format batch summary for output."""
    parts = [
        "## Batch Review Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total PRs | {summary.total} |",
        f"| Reviewed | {summary.reviewed} |",
        f"| Skipped | {summary.skipped} |",
        f"| Failed | {summary.failed} |",
        f"| Total comments | {summary.total_comments} |",
        f"| Critical issues | {summary.total_critical} |",
        f"| Total cost | ${summary.total_cost_usd:.4f} |",
        "",
    ]

    if summary.results:
        parts.append("### Details")
        parts.append("")

        for r in summary.results:
            if r.skipped:
                parts.append(f"- ⏭️ PR #{r.pr_number}: {r.title} — {r.skip_reason}")
            elif r.error:
                parts.append(f"- ❌ PR #{r.pr_number}: {r.title} — Error: {r.error}")
            elif r.result:
                risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(r.result.risk_level, "⚪")
                parts.append(
                    f"- {risk_emoji} PR #{r.pr_number}: {r.title} — "
                    f"{len(r.result.comments)} comments, ${r.result.cost_usd:.4f}"
                )

    return "\n".join(parts)
