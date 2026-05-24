"""Enhanced auto-labeling — semantically labels PRs based on content analysis.

Analyzes file paths, diff content, PR title, and description to
automatically apply labels: size (XS/S/M/L/XL), type (feature/bugfix),
area (frontend/backend/infra), and custom labels.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.github.client import PRFile, PRInfo


@dataclass
class LabelSuggestion:
    """A suggested label with confidence and rationale."""

    name: str
    color: str  # Hex color
    description: str
    confidence: float  # 0.0-1.0
    reason: str


# ── Size labels ──────────────────────────────────────────────────────────────

SIZE_THRESHOLDS = [
    (10, "size/XS", "3CB371", "Tiny change"),
    (50, "size/S", "7CFC00", "Small change"),
    (200, "size/M", "FFD700", "Medium change"),
    (500, "size/L", "FF8C00", "Large change"),
    (float("inf"), "size/XL", "FF4500", "Extra-large change"),
]


def _size_label(files: list[PRFile]) -> LabelSuggestion:
    """Determine PR size label."""
    total_changes = sum(f.additions + f.deletions for f in files)
    for threshold, name, color, desc in SIZE_THRESHOLDS:
        if total_changes <= threshold:
            return LabelSuggestion(
                name=name,
                color=color,
                description=desc,
                confidence=1.0,
                reason=f"{total_changes} lines changed",
            )
    # Fallback (shouldn't reach here due to inf)
    return LabelSuggestion(
        name="size/XL", color="FF4500",
        description="Extra-large change",
        confidence=1.0, reason=f"{total_changes} lines changed",
    )


# ── Type labels ──────────────────────────────────────────────────────────────

_TYPE_PATTERNS = [
    (r"\b(?:feat|feature|add|new)\b", "type/feature", "1D76DB", "New feature"),
    (r"\b(?:fix|bug|patch|hotfix|resolve)\b", "type/bugfix", "D93F0B", "Bug fix"),
    (r"\b(?:refactor|clean|restructure)\b", "type/refactor", "E4E669", "Code refactoring"),
    (r"\b(?:doc|docs|readme|documentation)\b", "type/docs", "0075CA", "Documentation"),
    (r"\b(?:test|spec|coverage)\b", "type/test", "BFD4F2", "Tests"),
    (r"\b(?:chore|deps|dependency|bump|upgrade)\b", "type/chore", "EDEDED", "Maintenance"),
    (r"\b(?:perf|performance|optimize|speed)\b", "type/performance", "F9D0C4", "Performance"),
    (r"\b(?:ci|cd|pipeline|workflow|deploy)\b", "type/ci", "C2E0C6", "CI/CD"),
    (r"\b(?:security|vuln|cve|auth)\b", "type/security", "EE0701", "Security"),
    (r"\b(?:style|css|ui|design|layout)\b", "type/ui", "D4C5F9", "UI/Styles"),
    (r"\b(?:breaking|deprecat)\b", "type/breaking", "B60205", "Breaking change"),
    (r"\b(?:revert)\b", "type/revert", "FBCA04", "Revert"),
]


def _type_labels(pr: PRInfo) -> list[LabelSuggestion]:
    """Determine PR type labels from title and description."""
    text = f"{pr.title} {pr.body or ''}"
    labels = []

    for pattern, name, color, desc in _TYPE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            labels.append(
                LabelSuggestion(
                    name=name, color=color, description=desc,
                    confidence=0.8, reason=f"Matched pattern in PR title/body",
                )
            )

    return labels


# ── Area labels ──────────────────────────────────────────────────────────────

_AREA_PATTERNS = [
    (r"(?:src/(?:components|pages|views|ui)/|\.tsx?$|\.jsx?$|\.css$|\.scss$)", "area/frontend", "7057FF"),
    (r"(?:src/(?:api|server|routes|controllers|services)/|\.go$|\.py$|\.rs$|\.java$)", "area/backend", "0E8A16"),
    (r"(?:\.github/|Dockerfile|docker-compose|terraform|k8s|helm|\.tf$)", "area/infra", "006B75"),
    (r"(?:test_|_test\.|\.test\.|\.spec\.|tests/|__tests__/)", "area/testing", "BFD4F2"),
    (r"(?:\.sql$|migration|alembic|flyway|schema)", "area/database", "5319E7"),
    (r"(?:\.md$|docs/|README|CHANGELOG)", "area/docs", "0075CA"),
    (r"(?:package\.json|pyproject|Cargo|go\.mod|Gemfile)", "area/deps", "EDEDED"),
    (r"(?:\.proto$|graphql|swagger|openapi)", "area/api-spec", "1D76DB"),
]


def _area_labels(files: list[PRFile]) -> list[LabelSuggestion]:
    """Determine area labels from file paths."""
    labels: list[LabelSuggestion] = []
    seen_areas: set[str] = set()

    for f in files:
        for pattern, name, color in _AREA_PATTERNS:
            if name not in seen_areas and re.search(pattern, f.filename, re.IGNORECASE):
                seen_areas.add(name)
                area_name = name.split("/")[1]
                labels.append(
                    LabelSuggestion(
                        name=name, color=color,
                        description=f"{area_name.capitalize()} changes",
                        confidence=0.9,
                        reason=f"File `{f.filename}` matches {area_name} pattern",
                    )
                )

    return labels


# ── Special labels ───────────────────────────────────────────────────────────

def _special_labels(pr: PRInfo, files: list[PRFile]) -> list[LabelSuggestion]:
    """Detect special conditions that warrant labels."""
    labels = []

    # First-time contributor
    # (Would need API call to check, leaving as placeholder logic)

    # Needs review
    total_changes = sum(f.additions + f.deletions for f in files)
    if total_changes > 500:
        labels.append(
            LabelSuggestion(
                name="needs-careful-review", color="FF0000",
                description="Large PR needs careful review",
                confidence=0.9, reason=f"{total_changes} lines changed",
            )
        )

    # Has migrations
    if any("migration" in f.filename.lower() for f in files):
        labels.append(
            LabelSuggestion(
                name="has-migration", color="E4E669",
                description="Contains database migrations",
                confidence=1.0, reason="Migration file detected",
            )
        )

    # Has breaking changes (title/branch indicators)
    if re.search(r"\b(?:breaking|BREAKING)\b", pr.title):
        labels.append(
            LabelSuggestion(
                name="breaking-change", color="B60205",
                description="Contains breaking changes",
                confidence=0.9, reason="Breaking change indicated in title",
            )
        )

    return labels


def suggest_labels(pr: PRInfo, files: list[PRFile]) -> list[LabelSuggestion]:
    """Generate all label suggestions for a PR."""
    labels: list[LabelSuggestion] = []

    # Size label (always one)
    labels.append(_size_label(files))

    # Type labels
    labels.extend(_type_labels(pr))

    # Area labels
    labels.extend(_area_labels(files))

    # Special labels
    labels.extend(_special_labels(pr, files))

    # Deduplicate by name
    seen: set[str] = set()
    unique: list[LabelSuggestion] = []
    for label in labels:
        if label.name not in seen:
            seen.add(label.name)
            unique.append(label)

    return unique


def format_label_suggestions(labels: list[LabelSuggestion]) -> str:
    """Format label suggestions as markdown."""
    if not labels:
        return ""

    parts = ["### 🏷️ Suggested Labels", ""]
    for label in labels:
        conf_pct = int(label.confidence * 100)
        parts.append(f"- `{label.name}` ({conf_pct}%) — {label.reason}")

    return "\n".join(parts)
