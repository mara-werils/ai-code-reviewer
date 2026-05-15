"""PR complexity scoring — helps teams enforce small, reviewable PRs.

Computes a 1-100 complexity score based on objective metrics:
lines changed, files touched, languages mixed, coupling signals, etc.

Zero LLM cost — purely algorithmic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.github.client import PRFile

# Thresholds for complexity buckets
SCORE_LOW = 30
SCORE_MEDIUM = 60
SCORE_HIGH = 80


@dataclass
class ComplexityResult:
    """PR complexity analysis."""

    score: int  # 1-100
    level: str  # trivial, low, medium, high, critical
    breakdown: dict[str, int]  # component → points
    suggestions: list[str]


# File extensions grouped by language family
_LANG_GROUPS: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".swift": "swift",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".css": "css",
    ".scss": "css",
    ".less": "css",
    ".html": "html",
    ".yaml": "config",
    ".yml": "config",
    ".toml": "config",
    ".json": "config",
    ".xml": "config",
}

# Patterns that indicate high-risk changes
_HIGH_RISK_PATTERNS = [
    re.compile(r"(?:DROP|ALTER|TRUNCATE)\s+TABLE", re.IGNORECASE),
    re.compile(r"(?:migration|migrate)", re.IGNORECASE),
    re.compile(r"(?:DELETE|REMOVE)\s+(?:FROM|WHERE)", re.IGNORECASE),
    re.compile(r"(?:api|endpoint|route).*(?:v\d|version)", re.IGNORECASE),
    re.compile(r"(?:auth|permission|rbac|acl)", re.IGNORECASE),
    re.compile(r"(?:password|secret|token|credential)", re.IGNORECASE),
]

# Files that amplify complexity when changed
_SENSITIVE_PATHS = [
    "Dockerfile",
    "docker-compose",
    ".github/workflows",
    "Makefile",
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    ".env",
    "schema",
    "migration",
]


def compute_complexity(files: list[PRFile]) -> ComplexityResult:
    """Compute PR complexity score from file-level metrics.

    Scoring components:
    - Size: lines added + deleted (0-30 pts)
    - Spread: number of files changed (0-15 pts)
    - Languages: number of distinct language families (0-10 pts)
    - Coupling: cross-directory changes (0-15 pts)
    - Risk: sensitive file patterns (0-15 pts)
    - Churn: ratio of deletions to additions (0-15 pts)
    """
    if not files:
        return ComplexityResult(score=0, level="trivial", breakdown={}, suggestions=[])

    breakdown: dict[str, int] = {}
    suggestions: list[str] = []

    total_added = sum(f.additions for f in files)
    total_deleted = sum(f.deletions for f in files)
    total_changed = total_added + total_deleted
    file_count = len(files)

    # 1. Size score (0-30)
    if total_changed <= 50:
        size_score = 0
    elif total_changed <= 150:
        size_score = 5
    elif total_changed <= 300:
        size_score = 10
    elif total_changed <= 500:
        size_score = 18
    elif total_changed <= 1000:
        size_score = 25
    else:
        size_score = 30
        suggestions.append(
            f"This PR changes {total_changed} lines. "
            "Consider splitting into smaller, focused PRs for easier review."
        )
    breakdown["size"] = size_score

    # 2. Spread score (0-15)
    if file_count <= 3:
        spread_score = 0
    elif file_count <= 7:
        spread_score = 5
    elif file_count <= 15:
        spread_score = 10
    else:
        spread_score = 15
        suggestions.append(
            f"This PR touches {file_count} files across the codebase. "
            "Large surface area increases risk of unintended side effects."
        )
    breakdown["spread"] = spread_score

    # 3. Language diversity (0-10)
    languages = set()
    for f in files:
        for ext, lang in _LANG_GROUPS.items():
            if f.filename.endswith(ext):
                languages.add(lang)
                break

    lang_count = len(languages)
    if lang_count <= 1:
        lang_score = 0
    elif lang_count == 2:
        lang_score = 3
    elif lang_count == 3:
        lang_score = 6
    else:
        lang_score = 10
        suggestions.append(
            f"PR spans {lang_count} language families ({', '.join(sorted(languages))}). "
            "Cross-language PRs are harder to review thoroughly."
        )
    breakdown["languages"] = lang_score

    # 4. Coupling score (0-15) — how many distinct directories are touched
    directories = set()
    for f in files:
        parts = f.filename.split("/")
        if len(parts) > 1:
            directories.add(parts[0] + "/" + parts[1] if len(parts) > 2 else parts[0])

    dir_count = len(directories)
    if dir_count <= 2:
        coupling_score = 0
    elif dir_count <= 4:
        coupling_score = 5
    elif dir_count <= 7:
        coupling_score = 10
    else:
        coupling_score = 15
    breakdown["coupling"] = coupling_score

    # 5. Risk score (0-15) — sensitive files and patterns
    risk_score = 0
    risk_files: list[str] = []
    for f in files:
        for sensitive in _SENSITIVE_PATHS:
            if sensitive.lower() in f.filename.lower():
                risk_score = min(risk_score + 3, 10)
                risk_files.append(f.filename)
                break

        if f.patch:
            for pattern in _HIGH_RISK_PATTERNS:
                if pattern.search(f.patch):
                    risk_score = min(risk_score + 5, 15)
                    break

    if risk_files:
        suggestions.append(
            f"Sensitive files changed: {', '.join(risk_files[:5])}. "
            "Extra review attention recommended."
        )
    breakdown["risk"] = risk_score

    # 6. Churn score (0-15) — high deletion ratio suggests refactoring
    if total_added > 0:
        churn_ratio = total_deleted / total_added
    else:
        churn_ratio = 0

    if churn_ratio > 3:
        churn_score = 15
    elif churn_ratio > 2:
        churn_score = 10
    elif churn_ratio > 1:
        churn_score = 5
    else:
        churn_score = 0
    breakdown["churn"] = churn_score

    # Total
    total = sum(breakdown.values())
    score = min(total, 100)

    if score <= 10:
        level = "trivial"
    elif score <= SCORE_LOW:
        level = "low"
    elif score <= SCORE_MEDIUM:
        level = "medium"
    elif score <= SCORE_HIGH:
        level = "high"
    else:
        level = "critical"

    return ComplexityResult(
        score=score,
        level=level,
        breakdown=breakdown,
        suggestions=suggestions,
    )


def format_complexity_badge(result: ComplexityResult) -> str:
    """Format complexity as a one-line badge for the review summary."""
    icons = {
        "trivial": "1/5",
        "low": "2/5",
        "medium": "3/5",
        "high": "4/5",
        "critical": "5/5",
    }
    icon = icons.get(result.level, "?/5")
    return f"**Complexity: {result.score}/100** ({result.level.upper()} {icon})"


def format_complexity_section(result: ComplexityResult) -> str:
    """Format full complexity breakdown for review body."""
    if result.score <= 10:
        return ""

    parts = [
        "",
        "### PR Complexity",
        "",
        format_complexity_badge(result),
        "",
    ]

    if result.breakdown:
        component_labels = {
            "size": "Lines changed",
            "spread": "Files touched",
            "languages": "Language mix",
            "coupling": "Cross-module",
            "risk": "Sensitive files",
            "churn": "Code churn",
        }
        items = []
        for key, pts in result.breakdown.items():
            if pts > 0:
                label = component_labels.get(key, key)
                items.append(f"{label}: +{pts}")
        parts.append("Breakdown: " + " | ".join(items))
        parts.append("")

    if result.suggestions:
        for s in result.suggestions:
            parts.append(f"> {s}")
        parts.append("")

    return "\n".join(parts)
