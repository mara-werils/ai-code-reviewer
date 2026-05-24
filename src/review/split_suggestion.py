"""PR split suggestion — recommends how to break large PRs into smaller ones.

Uses dependency analysis and file clustering to suggest logical splits.
Zero LLM cost for basic analysis; optional LLM for detailed recommendations.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field

from src.github.client import PRFile

logger = logging.getLogger(__name__)

# Threshold for suggesting a split
SPLIT_THRESHOLD_FILES = 15
SPLIT_THRESHOLD_LINES = 500


@dataclass
class SplitGroup:
    """A suggested group of files for a split PR."""

    name: str
    description: str
    files: list[str]
    total_additions: int = 0
    total_deletions: int = 0
    priority: int = 0  # 1 = should merge first


@dataclass
class SplitSuggestion:
    """Complete split recommendation."""

    should_split: bool
    reason: str
    groups: list[SplitGroup] = field(default_factory=list)
    total_files: int = 0
    total_lines: int = 0


# ── File category patterns ──────────────────────────────────────────────────

_CATEGORIES: list[tuple[str, str, list[str]]] = [
    ("migrations", "Database Migrations", [
        r"migration", r"migrate", r"alembic", r"flyway",
        r"\.sql$", r"db/", r"schema",
    ]),
    ("tests", "Tests", [
        r"test_", r"_test\.", r"\.test\.", r"\.spec\.",
        r"tests/", r"__tests__/", r"e2e/", r"cypress/",
    ]),
    ("docs", "Documentation", [
        r"\.md$", r"docs/", r"\.rst$", r"README",
        r"CHANGELOG", r"CONTRIBUTING", r"\.txt$",
    ]),
    ("ci", "CI/CD Configuration", [
        r"\.github/", r"\.gitlab-ci", r"Jenkinsfile",
        r"\.circleci/", r"bitbucket-pipelines",
        r"Dockerfile", r"docker-compose", r"\.dockerignore",
    ]),
    ("config", "Configuration", [
        r"\.env", r"\.yaml$", r"\.yml$", r"\.toml$",
        r"\.json$", r"\.ini$", r"\.cfg$",
        r"package\.json", r"tsconfig", r"webpack",
        r"pyproject\.toml", r"setup\.py", r"Cargo\.toml",
    ]),
    ("styles", "Styles/UI", [
        r"\.css$", r"\.scss$", r"\.less$", r"\.sass$",
        r"\.styled\.", r"tailwind",
    ]),
    ("api", "API Layer", [
        r"api/", r"routes/", r"endpoints/", r"controllers/",
        r"handlers/", r"views/", r"graphql/",
    ]),
    ("models", "Data Models", [
        r"models/", r"entities/", r"schemas/", r"types/",
        r"\.model\.", r"\.entity\.", r"\.schema\.",
    ]),
    ("services", "Business Logic", [
        r"services/", r"usecases/", r"domain/",
        r"\.service\.", r"\.usecase\.",
    ]),
]


def _categorize_file(path: str) -> str:
    """Assign a file to a category."""
    lower = path.lower()
    for cat_id, _, patterns in _CATEGORIES:
        for pattern in patterns:
            if re.search(pattern, lower):
                return cat_id
    return "core"


def _get_directory_group(path: str) -> str:
    """Get the top-level directory grouping."""
    parts = path.split("/")
    if len(parts) > 1:
        return parts[0]
    return "(root)"


def suggest_split(files: list[PRFile]) -> SplitSuggestion:
    """Analyze PR files and suggest how to split."""
    total_lines = sum(f.additions + f.deletions for f in files)
    total_files = len(files)

    # Check if split is needed
    if total_files < SPLIT_THRESHOLD_FILES and total_lines < SPLIT_THRESHOLD_LINES:
        return SplitSuggestion(
            should_split=False,
            reason=f"PR size is manageable ({total_files} files, {total_lines} lines changed).",
            total_files=total_files,
            total_lines=total_lines,
        )

    # Group files by category
    category_files: dict[str, list[PRFile]] = defaultdict(list)
    for f in files:
        cat = _categorize_file(f.filename)
        category_files[cat].append(f)

    # Build split groups
    groups: list[SplitGroup] = []
    priority = 1

    cat_labels = {cat_id: label for cat_id, label, _ in _CATEGORIES}
    cat_labels["core"] = "Core Changes"

    # Prioritize: migrations first, then core, then tests, then docs
    priority_order = ["migrations", "models", "api", "services", "core", "config", "ci", "styles", "tests", "docs"]

    for cat in priority_order:
        cat_files = category_files.get(cat, [])
        if not cat_files:
            continue

        group = SplitGroup(
            name=cat_labels.get(cat, cat.capitalize()),
            description=f"{len(cat_files)} file{'s' if len(cat_files) != 1 else ''}",
            files=[f.filename for f in cat_files],
            total_additions=sum(f.additions for f in cat_files),
            total_deletions=sum(f.deletions for f in cat_files),
            priority=priority,
        )
        groups.append(group)
        priority += 1

    # If categories don't produce good splits, try directory-based
    if len(groups) <= 1:
        dir_files: dict[str, list[PRFile]] = defaultdict(list)
        for f in files:
            dir_group = _get_directory_group(f.filename)
            dir_files[dir_group].append(f)

        groups = []
        for dir_name, dir_f in sorted(dir_files.items()):
            groups.append(
                SplitGroup(
                    name=f"`{dir_name}/` changes",
                    description=f"{len(dir_f)} files",
                    files=[f.filename for f in dir_f],
                    total_additions=sum(f.additions for f in dir_f),
                    total_deletions=sum(f.deletions for f in dir_f),
                    priority=len(groups) + 1,
                )
            )

    reasons = []
    if total_files >= SPLIT_THRESHOLD_FILES:
        reasons.append(f"{total_files} files changed (threshold: {SPLIT_THRESHOLD_FILES})")
    if total_lines >= SPLIT_THRESHOLD_LINES:
        reasons.append(f"{total_lines} lines changed (threshold: {SPLIT_THRESHOLD_LINES})")

    return SplitSuggestion(
        should_split=True,
        reason=f"PR is large: {'; '.join(reasons)}. Consider splitting into {len(groups)} PRs.",
        groups=groups,
        total_files=total_files,
        total_lines=total_lines,
    )


def format_split_suggestion(suggestion: SplitSuggestion) -> str:
    """Format split suggestion into markdown."""
    if not suggestion.should_split:
        return f"✅ **PR size is fine** — {suggestion.reason}"

    parts = [
        "### ✂️ PR Split Suggestion",
        "",
        f"⚠️ {suggestion.reason}",
        "",
        "**Suggested split:**",
        "",
    ]

    for i, group in enumerate(suggestion.groups, 1):
        lines = group.total_additions + group.total_deletions
        parts.append(
            f"**PR {i}: {group.name}** "
            f"({len(group.files)} files, +{group.total_additions}/-{group.total_deletions})"
        )
        if group.priority == 1:
            parts.append("  _(merge first)_")

        parts.append("<details>")
        parts.append(f"<summary>Files ({len(group.files)})</summary>")
        parts.append("")
        for fname in group.files[:20]:
            parts.append(f"  - `{fname}`")
        if len(group.files) > 20:
            parts.append(f"  - _...and {len(group.files) - 20} more_")
        parts.append("")
        parts.append("</details>")
        parts.append("")

    parts.append("---")
    parts.append("_Smaller PRs are easier to review, less risky, and merge faster._")

    return "\n".join(parts)
