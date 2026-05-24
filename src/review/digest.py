"""Review digest — generates daily/weekly review summaries.

Aggregates review data across PRs to produce team-level insights:
top issues, review velocity, cost tracking, and trend analysis.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ReviewRecord:
    """Record of a single review for digest aggregation."""

    pr_number: int
    repo: str
    title: str
    author: str
    risk_level: str
    category: str
    comment_count: int
    critical_count: int
    warning_count: int
    cost_usd: float
    duration_ms: int
    model: str
    timestamp: str = ""
    labels: list[str] = field(default_factory=list)


@dataclass
class DigestReport:
    """Aggregated review digest."""

    period: str  # "daily", "weekly", "monthly"
    start_date: str
    end_date: str
    total_reviews: int
    total_prs: int
    total_comments: int
    total_critical: int
    total_cost_usd: float
    avg_duration_ms: float
    top_issues: list[tuple[str, int]]  # (category, count)
    risk_distribution: dict[str, int]
    category_distribution: dict[str, int]
    top_authors: list[tuple[str, int]]
    model_usage: dict[str, int]
    highlights: list[str]


def build_digest(
    records: list[ReviewRecord],
    period: str = "weekly",
    start_date: str = "",
    end_date: str = "",
) -> DigestReport:
    """Build a digest report from review records."""
    if not records:
        return DigestReport(
            period=period,
            start_date=start_date,
            end_date=end_date,
            total_reviews=0,
            total_prs=0,
            total_comments=0,
            total_critical=0,
            total_cost_usd=0,
            avg_duration_ms=0,
            top_issues=[],
            risk_distribution={},
            category_distribution={},
            top_authors=[],
            model_usage={},
            highlights=[],
        )

    total_comments = sum(r.comment_count for r in records)
    total_critical = sum(r.critical_count for r in records)
    total_cost = sum(r.cost_usd for r in records)
    avg_duration = sum(r.duration_ms for r in records) / len(records)

    # Risk distribution
    risk_dist = Counter(r.risk_level for r in records)
    cat_dist = Counter(r.category for r in records)
    author_counts = Counter(r.author for r in records)
    model_counts = Counter(r.model for r in records)

    # Unique PRs
    unique_prs = len(set((r.repo, r.pr_number) for r in records))

    # Generate highlights
    highlights: list[str] = []

    high_risk = risk_dist.get("high", 0)
    if high_risk > 0:
        highlights.append(f"⚠️ {high_risk} high-risk PR{'s' if high_risk != 1 else ''} reviewed")

    if total_critical > 0:
        highlights.append(f"🔴 {total_critical} critical issue{'s' if total_critical != 1 else ''} found")

    if total_cost > 1.0:
        highlights.append(f"💰 Total review cost: ${total_cost:.2f}")

    most_active = author_counts.most_common(1)
    if most_active:
        highlights.append(f"👤 Most active author: {most_active[0][0]} ({most_active[0][1]} PRs)")

    return DigestReport(
        period=period,
        start_date=start_date,
        end_date=end_date,
        total_reviews=len(records),
        total_prs=unique_prs,
        total_comments=total_comments,
        total_critical=total_critical,
        total_cost_usd=total_cost,
        avg_duration_ms=avg_duration,
        top_issues=cat_dist.most_common(5),
        risk_distribution=dict(risk_dist),
        category_distribution=dict(cat_dist),
        top_authors=author_counts.most_common(10),
        model_usage=dict(model_counts),
        highlights=highlights,
    )


def format_digest_markdown(report: DigestReport) -> str:
    """Format digest report as markdown."""
    parts = [
        f"# 📊 Review Digest ({report.period.capitalize()})",
        "",
        f"**Period:** {report.start_date} — {report.end_date}",
        "",
        "## Overview",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| PRs reviewed | {report.total_prs} |",
        f"| Total reviews | {report.total_reviews} |",
        f"| Comments generated | {report.total_comments} |",
        f"| Critical issues | {report.total_critical} |",
        f"| Total cost | ${report.total_cost_usd:.2f} |",
        f"| Avg review time | {report.avg_duration_ms:.0f}ms |",
        "",
    ]

    if report.highlights:
        parts.append("## Highlights")
        parts.append("")
        for h in report.highlights:
            parts.append(f"- {h}")
        parts.append("")

    # Risk distribution
    if report.risk_distribution:
        parts.append("## Risk Distribution")
        parts.append("")
        risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}
        for risk, count in sorted(report.risk_distribution.items()):
            emoji = risk_emoji.get(risk, "⚪")
            pct = (count / report.total_reviews * 100) if report.total_reviews else 0
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            parts.append(f"- {emoji} **{risk.capitalize()}**: {count} ({pct:.0f}%) `{bar}`")
        parts.append("")

    # Category distribution
    if report.category_distribution:
        parts.append("## PR Categories")
        parts.append("")
        for cat, count in report.top_issues:
            parts.append(f"- **{cat}**: {count}")
        parts.append("")

    # Top authors
    if report.top_authors:
        parts.append("## Top Authors")
        parts.append("")
        for author, count in report.top_authors[:5]:
            parts.append(f"- @{author}: {count} PR{'s' if count != 1 else ''}")
        parts.append("")

    # Model usage
    if report.model_usage:
        parts.append("## Model Usage")
        parts.append("")
        for model, count in sorted(report.model_usage.items(), key=lambda x: -x[1]):
            parts.append(f"- `{model}`: {count} review{'s' if count != 1 else ''}")
        parts.append("")

    return "\n".join(parts)


def format_digest_slack(report: DigestReport) -> dict:
    """Format digest as Slack webhook payload."""
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📊 {report.period.capitalize()} Review Digest",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*PRs Reviewed:* {report.total_prs}"},
                {"type": "mrkdwn", "text": f"*Comments:* {report.total_comments}"},
                {"type": "mrkdwn", "text": f"*Critical Issues:* {report.total_critical}"},
                {"type": "mrkdwn", "text": f"*Total Cost:* ${report.total_cost_usd:.2f}"},
            ],
        },
    ]

    if report.highlights:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "\n".join(report.highlights),
            },
        })

    return {"blocks": blocks}
