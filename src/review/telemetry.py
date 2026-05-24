"""Telemetry module — tracks review metrics for local analysis.

Privacy-first: all data stored locally, opt-in, no external calls.
Tracks review duration, cost, comment counts, model usage for
understanding review patterns and optimizing configuration.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TELEMETRY_DIR = ".pr-reviewer-telemetry"


@dataclass
class ReviewEvent:
    """A single review telemetry event."""

    timestamp: str
    repo: str
    pr_number: int
    provider: str
    model: str
    risk_level: str
    category: str
    comment_count: int
    critical_count: int
    warning_count: int
    suggestion_count: int
    cost_usd: float
    duration_ms: int
    input_tokens: int
    output_tokens: int
    files_reviewed: int
    lines_changed: int
    persona: str = ""
    review_style: str = ""
    security_findings: int = 0
    performance_findings: int = 0


@dataclass
class TelemetryStats:
    """Aggregated telemetry statistics."""

    total_reviews: int = 0
    total_cost_usd: float = 0.0
    total_comments: int = 0
    total_critical: int = 0
    avg_duration_ms: float = 0.0
    avg_cost_usd: float = 0.0
    avg_comments: float = 0.0
    model_distribution: dict[str, int] = field(default_factory=dict)
    provider_distribution: dict[str, int] = field(default_factory=dict)
    risk_distribution: dict[str, int] = field(default_factory=dict)
    category_distribution: dict[str, int] = field(default_factory=dict)
    cost_trend: list[float] = field(default_factory=list)
    reviews_per_day: dict[str, int] = field(default_factory=dict)


class TelemetryCollector:
    """Collects and stores review telemetry data locally."""

    def __init__(self, storage_dir: str = "") -> None:
        self._dir = Path(storage_dir or os.getenv("PR_REVIEWER_TELEMETRY_DIR", DEFAULT_TELEMETRY_DIR))
        self._enabled = os.getenv("PR_REVIEWER_TELEMETRY", "true").lower() != "false"

    @property
    def enabled(self) -> bool:
        return self._enabled

    def record(self, event: ReviewEvent) -> None:
        """Record a review event."""
        if not self._enabled:
            return

        try:
            self._dir.mkdir(parents=True, exist_ok=True)

            # Append to daily log file
            date_str = event.timestamp[:10]  # YYYY-MM-DD
            log_file = self._dir / f"reviews-{date_str}.jsonl"

            with open(log_file, "a") as f:
                f.write(json.dumps(asdict(event)) + "\n")

            logger.debug(f"Telemetry recorded for PR #{event.pr_number}")

        except Exception as e:
            logger.debug(f"Telemetry write failed (non-critical): {e}")

    def get_stats(self, days: int = 30) -> TelemetryStats:
        """Compute statistics from recent telemetry data."""
        events = self._load_events(days)
        if not events:
            return TelemetryStats()

        stats = TelemetryStats(
            total_reviews=len(events),
            total_cost_usd=sum(e.cost_usd for e in events),
            total_comments=sum(e.comment_count for e in events),
            total_critical=sum(e.critical_count for e in events),
        )

        stats.avg_duration_ms = sum(e.duration_ms for e in events) / len(events)
        stats.avg_cost_usd = stats.total_cost_usd / len(events)
        stats.avg_comments = stats.total_comments / len(events)

        for e in events:
            stats.model_distribution[e.model] = stats.model_distribution.get(e.model, 0) + 1
            stats.provider_distribution[e.provider] = stats.provider_distribution.get(e.provider, 0) + 1
            stats.risk_distribution[e.risk_level] = stats.risk_distribution.get(e.risk_level, 0) + 1
            stats.category_distribution[e.category] = stats.category_distribution.get(e.category, 0) + 1
            stats.cost_trend.append(e.cost_usd)

            day = e.timestamp[:10]
            stats.reviews_per_day[day] = stats.reviews_per_day.get(day, 0) + 1

        return stats

    def _load_events(self, days: int = 30) -> list[ReviewEvent]:
        """Load events from recent log files."""
        events: list[ReviewEvent] = []

        if not self._dir.exists():
            return events

        for log_file in sorted(self._dir.glob("reviews-*.jsonl"))[-days:]:
            try:
                with open(log_file) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            data = json.loads(line)
                            events.append(ReviewEvent(**data))
            except Exception as e:
                logger.debug(f"Failed to load {log_file}: {e}")

        return events

    def clear(self, days: int = 0) -> int:
        """Clear telemetry data. If days=0, clear all."""
        if not self._dir.exists():
            return 0

        count = 0
        for f in self._dir.glob("reviews-*.jsonl"):
            f.unlink()
            count += 1

        return count


def create_event(
    repo: str,
    pr_number: int,
    config,
    result,
    files_count: int = 0,
    lines_changed: int = 0,
    security_findings: int = 0,
    performance_findings: int = 0,
) -> ReviewEvent:
    """Create a telemetry event from review config and result."""
    return ReviewEvent(
        timestamp=datetime.now(timezone.utc).isoformat(),
        repo=repo,
        pr_number=pr_number,
        provider=config.provider,
        model=result.model,
        risk_level=result.risk_level,
        category=result.category,
        comment_count=len(result.comments),
        critical_count=sum(1 for c in result.comments if c.severity == "critical"),
        warning_count=sum(1 for c in result.comments if c.severity == "warning"),
        suggestion_count=sum(1 for c in result.comments if c.severity == "suggestion"),
        cost_usd=result.cost_usd,
        duration_ms=result.duration_ms,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        files_reviewed=files_count,
        lines_changed=lines_changed,
        persona=getattr(config, "persona", ""),
        review_style=config.review_style,
        security_findings=security_findings,
        performance_findings=performance_findings,
    )


def format_stats(stats: TelemetryStats) -> str:
    """Format telemetry stats as readable output."""
    if stats.total_reviews == 0:
        return "No telemetry data available."

    parts = [
        "## 📈 Review Telemetry",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total reviews | {stats.total_reviews} |",
        f"| Total cost | ${stats.total_cost_usd:.2f} |",
        f"| Avg cost/review | ${stats.avg_cost_usd:.4f} |",
        f"| Avg duration | {stats.avg_duration_ms:.0f}ms |",
        f"| Avg comments | {stats.avg_comments:.1f} |",
        f"| Critical issues | {stats.total_critical} |",
        "",
    ]

    if stats.model_distribution:
        parts.append("**Models:**")
        for model, count in sorted(stats.model_distribution.items(), key=lambda x: -x[1]):
            parts.append(f"- `{model}`: {count}")
        parts.append("")

    if stats.risk_distribution:
        parts.append("**Risk distribution:**")
        for risk, count in sorted(stats.risk_distribution.items()):
            pct = count / stats.total_reviews * 100
            parts.append(f"- {risk}: {count} ({pct:.0f}%)")

    return "\n".join(parts)
