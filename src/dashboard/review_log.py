"""Review log — lightweight JSON-based analytics storage.

Logs each review to .pr-reviewer-log.json in the repo root.
No database required — works in GitHub Actions, GitLab CI, etc.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_LOG_FILE = ".pr-reviewer-log.json"
_MAX_ENTRIES = 500


@dataclass
class ReviewLogEntry:
    """A single review log entry."""

    pr_number: int
    title: str
    author: str
    repo: str
    risk_level: str
    category: str
    comments_count: int
    cost_usd: float
    duration_ms: int
    model: str
    provider: str
    timestamp: str = ""
    files_changed: int = 0
    lines_added: int = 0
    lines_deleted: int = 0
    severity_counts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


@dataclass
class ReviewLog:
    """Collection of review log entries with computed analytics."""

    entries: list[ReviewLogEntry] = field(default_factory=list)

    def add(self, entry: ReviewLogEntry) -> None:
        self.entries.append(entry)
        if len(self.entries) > _MAX_ENTRIES:
            self.entries = self.entries[-_MAX_ENTRIES:]

    @property
    def total_reviews(self) -> int:
        return len(self.entries)

    @property
    def total_cost(self) -> float:
        return sum(e.cost_usd for e in self.entries)

    @property
    def avg_cost(self) -> float:
        if not self.entries:
            return 0.0
        return self.total_cost / len(self.entries)

    @property
    def avg_duration_ms(self) -> float:
        if not self.entries:
            return 0.0
        return sum(e.duration_ms for e in self.entries) / len(self.entries)

    @property
    def total_comments(self) -> int:
        return sum(e.comments_count for e in self.entries)

    def risk_distribution(self) -> dict[str, int]:
        dist: dict[str, int] = {}
        for e in self.entries:
            dist[e.risk_level] = dist.get(e.risk_level, 0) + 1
        return dist

    def category_distribution(self) -> dict[str, int]:
        dist: dict[str, int] = {}
        for e in self.entries:
            dist[e.category] = dist.get(e.category, 0) + 1
        return dist

    def top_authors(self, n: int = 10) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for e in self.entries:
            counts[e.author] = counts.get(e.author, 0) + 1
        return sorted(counts.items(), key=lambda x: x[1], reverse=True)[:n]

    def cost_by_day(self) -> list[dict[str, str | float]]:
        by_day: dict[str, float] = {}
        for e in self.entries:
            day = e.timestamp[:10]  # YYYY-MM-DD
            by_day[day] = by_day.get(day, 0) + e.cost_usd
        return [{"date": d, "cost": round(c, 4)} for d, c in sorted(by_day.items())]

    def reviews_by_day(self) -> list[dict[str, str | int]]:
        by_day: dict[str, int] = {}
        for e in self.entries:
            day = e.timestamp[:10]
            by_day[day] = by_day.get(day, 0) + 1
        return [{"date": d, "count": c} for d, c in sorted(by_day.items())]

    def severity_totals(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for e in self.entries:
            for sev, count in e.severity_counts.items():
                totals[sev] = totals.get(sev, 0) + count
        return totals

    def to_analytics(self) -> dict:
        """Generate full analytics summary."""
        return {
            "total_reviews": self.total_reviews,
            "total_cost_usd": round(self.total_cost, 4),
            "avg_cost_usd": round(self.avg_cost, 4),
            "avg_duration_ms": round(self.avg_duration_ms),
            "total_comments": self.total_comments,
            "risk_distribution": self.risk_distribution(),
            "category_distribution": self.category_distribution(),
            "severity_totals": self.severity_totals(),
            "top_authors": self.top_authors(),
            "cost_by_day": self.cost_by_day(),
            "reviews_by_day": self.reviews_by_day(),
        }


def load_log(path: Path | None = None) -> ReviewLog:
    if path is None:
        path = Path(_LOG_FILE)

    if not path.exists():
        return ReviewLog()

    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load review log from {path}: {e}")
        return ReviewLog()

    entries = []
    for item in data.get("entries", []):
        entries.append(ReviewLogEntry(
            pr_number=item.get("pr_number", 0),
            title=item.get("title", ""),
            author=item.get("author", ""),
            repo=item.get("repo", ""),
            risk_level=item.get("risk_level", ""),
            category=item.get("category", ""),
            comments_count=item.get("comments_count", 0),
            cost_usd=item.get("cost_usd", 0),
            duration_ms=item.get("duration_ms", 0),
            model=item.get("model", ""),
            provider=item.get("provider", ""),
            timestamp=item.get("timestamp", ""),
            files_changed=item.get("files_changed", 0),
            lines_added=item.get("lines_added", 0),
            lines_deleted=item.get("lines_deleted", 0),
            severity_counts=item.get("severity_counts", {}),
        ))

    return ReviewLog(entries=entries)


def save_log(log: ReviewLog, path: Path | None = None) -> None:
    if path is None:
        path = Path(_LOG_FILE)

    data = {"entries": [asdict(e) for e in log.entries]}

    with open(path, "w") as f:
        json.dump(data, f, indent=2)
