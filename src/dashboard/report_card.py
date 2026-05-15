"""Team review report card — weekly/monthly analytics digest.

Generates a markdown report from the local review log showing:
- Total PRs reviewed, issues found, cost
- Risk distribution
- Top issue categories
- Cost trend
- Team review health score

Usage:
    pr-reviewer report --period week
    pr-reviewer report --period month
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from src.dashboard.review_log import ReviewLogEntry, load_log


@dataclass
class ReportCard:
    """Aggregated review analytics."""

    period: str
    start_date: str
    end_date: str
    total_reviews: int
    total_comments: int
    total_cost_usd: float
    avg_duration_ms: int
    risk_distribution: dict[str, int]
    category_distribution: dict[str, int]
    severity_distribution: dict[str, int]
    top_authors: list[tuple[str, int]]
    health_score: int  # 0-100


def _compute_health_score(entries: list[ReviewLogEntry]) -> int:
    """Compute team review health score (0-100).

    Factors:
    - Low % of high-risk PRs → higher score
    - Low avg comments per PR → higher score (cleaner code)
    - Consistent review adoption → higher score
    """
    if not entries:
        return 0

    total = len(entries)
    high_risk = sum(1 for e in entries if e.risk_level == "high")
    avg_comments = sum(e.comments_count for e in entries) / total

    # Risk factor: fewer high-risk PRs = better (0-40 pts)
    high_risk_ratio = high_risk / total
    risk_score = int(40 * (1 - high_risk_ratio))

    # Code quality: fewer comments needed = better (0-30 pts)
    if avg_comments <= 2:
        quality_score = 30
    elif avg_comments <= 5:
        quality_score = 20
    elif avg_comments <= 10:
        quality_score = 10
    else:
        quality_score = 0

    # Volume: consistent reviews = better (0-30 pts)
    if total >= 20:
        volume_score = 30
    elif total >= 10:
        volume_score = 20
    elif total >= 5:
        volume_score = 10
    else:
        volume_score = 5

    return min(risk_score + quality_score + volume_score, 100)


def generate_report(period: str = "week") -> ReportCard:
    """Generate a report card for the given period."""
    log = load_log()

    now = datetime.datetime.now(datetime.UTC)
    if period == "month":
        start = now - datetime.timedelta(days=30)
    else:
        start = now - datetime.timedelta(days=7)

    start_str = start.strftime("%Y-%m-%d")
    end_str = now.strftime("%Y-%m-%d")

    # Filter entries by period
    entries = [e for e in log.entries if e.timestamp >= start_str]

    # Aggregate
    risk_dist: dict[str, int] = {}
    cat_dist: dict[str, int] = {}
    sev_dist: dict[str, int] = {}
    author_counts: dict[str, int] = {}
    total_cost = 0.0
    total_comments = 0
    total_duration = 0

    for e in entries:
        risk_dist[e.risk_level] = risk_dist.get(e.risk_level, 0) + 1
        cat_dist[e.category] = cat_dist.get(e.category, 0) + 1
        author_counts[e.author] = author_counts.get(e.author, 0) + 1
        total_cost += e.cost_usd
        total_comments += e.comments_count
        total_duration += e.duration_ms

        for sev, count in e.severity_counts.items():
            sev_dist[sev] = sev_dist.get(sev, 0) + count

    top_authors = sorted(author_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    avg_duration = total_duration // max(len(entries), 1)

    return ReportCard(
        period=period,
        start_date=start_str,
        end_date=end_str,
        total_reviews=len(entries),
        total_comments=total_comments,
        total_cost_usd=total_cost,
        avg_duration_ms=avg_duration,
        risk_distribution=risk_dist,
        category_distribution=cat_dist,
        severity_distribution=sev_dist,
        top_authors=top_authors,
        health_score=_compute_health_score(entries),
    )


def format_report_markdown(report: ReportCard) -> str:
    """Format report card as markdown."""
    parts = [
        f"# AI Code Review — {'Weekly' if report.period == 'week' else 'Monthly'} Report",
        "",
        f"**{report.start_date}** to **{report.end_date}**",
        "",
        "---",
        "",
        f"## Team Health Score: {report.health_score}/100",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| PRs Reviewed | {report.total_reviews} |",
        f"| Total Comments | {report.total_comments} |",
        f"| Total Cost | ${report.total_cost_usd:.2f} |",
        f"| Avg Duration | {report.avg_duration_ms}ms |",
        "",
    ]

    if report.risk_distribution:
        parts.append("### Risk Distribution")
        parts.append("")
        for risk, count in sorted(report.risk_distribution.items()):
            pct = count / max(report.total_reviews, 1) * 100
            parts.append(f"- **{risk.upper()}**: {count} ({pct:.0f}%)")
        parts.append("")

    if report.severity_distribution:
        parts.append("### Issue Severity")
        parts.append("")
        for sev in ["critical", "warning", "suggestion", "info"]:
            count = report.severity_distribution.get(sev, 0)
            if count:
                parts.append(f"- **{sev.upper()}**: {count}")
        parts.append("")

    if report.category_distribution:
        parts.append("### PR Categories")
        parts.append("")
        for cat, count in sorted(report.category_distribution.items(), key=lambda x: -x[1]):
            parts.append(f"- {cat}: {count}")
        parts.append("")

    if report.top_authors:
        parts.append("### Most Active Authors")
        parts.append("")
        for author, count in report.top_authors:
            parts.append(f"- @{author}: {count} PRs")
        parts.append("")

    parts.extend(
        [
            "---",
            "",
            "*Generated by [AI Code Reviewer](https://github.com/mara-werils/ai-code-reviewer)*",
        ]
    )

    return "\n".join(parts)
