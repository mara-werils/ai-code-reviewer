"""Smart reviewer suggestion — suggests the best human reviewers.

Analyzes CODEOWNERS, git blame, and file paths to recommend
who should review the PR based on code ownership and expertise.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from src.github.client import PRFile

logger = logging.getLogger(__name__)


@dataclass
class ReviewerCandidate:
    """A suggested reviewer with rationale."""

    username: str
    score: int  # 0-100 relevance
    reasons: list[str] = field(default_factory=list)
    owned_files: list[str] = field(default_factory=list)


@dataclass
class ReviewerSuggestion:
    """Complete reviewer recommendation."""

    candidates: list[ReviewerCandidate]
    codeowners_found: bool
    total_files: int


# ── CODEOWNERS parsing ────────────────────────────────────────────────────────

_CODEOWNERS_LOCATIONS = [
    "CODEOWNERS",
    ".github/CODEOWNERS",
    "docs/CODEOWNERS",
]


def parse_codeowners(content: str) -> list[tuple[str, list[str]]]:
    """Parse CODEOWNERS file into (pattern, owners) pairs."""
    rules: list[tuple[str, list[str]]] = []

    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        if len(parts) < 2:
            continue

        pattern = parts[0]
        owners = [p for p in parts[1:] if p.startswith("@") or "/" in p]
        # Normalize owner names
        owners = [o.lstrip("@") for o in owners]

        if owners:
            rules.append((pattern, owners))

    return rules


def _match_codeowners_pattern(path: str, pattern: str) -> bool:
    """Match a file path against a CODEOWNERS pattern."""
    import fnmatch

    # Handle directory patterns
    if pattern.endswith("/"):
        return path.startswith(pattern) or fnmatch.fnmatch(path, pattern + "*")

    # Handle glob patterns
    if "*" in pattern:
        return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch("/" + path, pattern)

    # Exact match or directory prefix
    return path == pattern or path.startswith(pattern + "/") or path.endswith("/" + pattern)


def suggest_reviewers(
    files: list[PRFile],
    codeowners_content: str = "",
    blame_data: dict[str, list[str]] | None = None,
    pr_author: str = "",
    max_suggestions: int = 5,
) -> ReviewerSuggestion:
    """Suggest reviewers based on code ownership and expertise."""
    owner_scores: Counter[str] = Counter()
    owner_files: dict[str, list[str]] = {}
    owner_reasons: dict[str, list[str]] = {}
    codeowners_found = bool(codeowners_content.strip())

    # Parse CODEOWNERS
    if codeowners_content:
        rules = parse_codeowners(codeowners_content)

        for f in files:
            for pattern, owners in reversed(rules):  # Last matching rule wins
                if _match_codeowners_pattern(f.filename, pattern):
                    for owner in owners:
                        owner_scores[owner] += 10
                        owner_files.setdefault(owner, []).append(f.filename)
                        reason = f"CODEOWNERS: `{pattern}`"
                        owner_reasons.setdefault(owner, [])
                        if reason not in owner_reasons[owner]:
                            owner_reasons[owner].append(reason)
                    break  # Only apply last matching rule

    # Use blame data for authorship-based suggestions
    if blame_data:
        for filepath, authors in blame_data.items():
            for f in files:
                if f.filename == filepath:
                    for author in authors:
                        if author != pr_author:
                            owner_scores[author] += 5
                            owner_files.setdefault(author, []).append(filepath)
                            owner_reasons.setdefault(author, [])
                            if "Recent contributor" not in " ".join(owner_reasons.get(author, [])):
                                owner_reasons.setdefault(author, []).append(
                                    f"Recent contributor to `{filepath}`"
                                )

    # Directory-based expertise inference
    dir_experts: dict[str, Counter[str]] = {}
    for f in files:
        parts = f.filename.split("/")
        if len(parts) > 1:
            top_dir = parts[0]
            for owner, owned in owner_files.items():
                if any(o.startswith(top_dir + "/") for o in owned):
                    owner_scores[owner] += 3
                    owner_reasons.setdefault(owner, [])
                    reason = f"Expertise in `{top_dir}/`"
                    if reason not in owner_reasons.get(owner, []):
                        owner_reasons[owner].append(reason)

    # Remove PR author from suggestions
    if pr_author:
        owner_scores.pop(pr_author, None)

    # Build candidates
    candidates: list[ReviewerCandidate] = []
    for owner, score in owner_scores.most_common(max_suggestions):
        candidates.append(
            ReviewerCandidate(
                username=owner,
                score=min(100, score),
                reasons=owner_reasons.get(owner, []),
                owned_files=owner_files.get(owner, [])[:10],
            )
        )

    return ReviewerSuggestion(
        candidates=candidates,
        codeowners_found=codeowners_found,
        total_files=len(files),
    )


def format_reviewer_suggestion(suggestion: ReviewerSuggestion) -> str:
    """Format reviewer suggestions as markdown."""
    if not suggestion.candidates:
        hint = ""
        if not suggestion.codeowners_found:
            hint = " (tip: add a CODEOWNERS file for automatic suggestions)"
        return f"No reviewer suggestions available{hint}."

    parts = ["### 👥 Suggested Reviewers", ""]

    for i, candidate in enumerate(suggestion.candidates, 1):
        parts.append(
            f"{i}. **@{candidate.username}** (relevance: {candidate.score}/100)"
        )
        for reason in candidate.reasons[:3]:
            parts.append(f"   - {reason}")
        if candidate.owned_files:
            files_str = ", ".join(f"`{f}`" for f in candidate.owned_files[:3])
            if len(candidate.owned_files) > 3:
                files_str += f" +{len(candidate.owned_files) - 3} more"
            parts.append(f"   - Owns: {files_str}")
        parts.append("")

    if not suggestion.codeowners_found:
        parts.append("_Tip: Add a CODEOWNERS file for more accurate suggestions._")

    return "\n".join(parts)
