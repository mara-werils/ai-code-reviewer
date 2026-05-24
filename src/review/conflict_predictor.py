"""Merge conflict predictor — identifies files likely to conflict.

Analyzes open PRs in the same repo to find overlapping file changes
that may cause merge conflicts. Zero LLM cost.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.github.client import PRFile, PRInfo

logger = logging.getLogger(__name__)


@dataclass
class ConflictRisk:
    """A potential merge conflict."""

    file: str
    conflicting_pr: int
    conflicting_title: str
    conflicting_author: str
    overlap_lines: int
    risk_level: str  # high, medium, low


@dataclass
class ConflictPrediction:
    """Complete conflict prediction for a PR."""

    risks: list[ConflictRisk] = field(default_factory=list)
    total_risky_files: int = 0
    high_risk_count: int = 0


def predict_conflicts(
    current_pr: PRInfo,
    current_files: list[PRFile],
    other_prs: list[tuple[PRInfo, list[PRFile]]],
) -> ConflictPrediction:
    """Predict merge conflicts by comparing files across open PRs."""
    prediction = ConflictPrediction()

    current_file_set = {f.filename for f in current_files}
    current_file_changes = {f.filename: f.additions + f.deletions for f in current_files}

    for other_pr, other_files in other_prs:
        if other_pr.number == current_pr.number:
            continue

        other_file_set = {f.filename for f in other_files}
        overlapping = current_file_set & other_file_set

        for filename in overlapping:
            other_file = next(f for f in other_files if f.filename == filename)
            current_changes = current_file_changes.get(filename, 0)
            other_changes = other_file.additions + other_file.deletions

            # Estimate risk based on change volume
            total_changes = current_changes + other_changes
            if total_changes > 100:
                risk_level = "high"
            elif total_changes > 30:
                risk_level = "medium"
            else:
                risk_level = "low"

            prediction.risks.append(
                ConflictRisk(
                    file=filename,
                    conflicting_pr=other_pr.number,
                    conflicting_title=other_pr.title,
                    conflicting_author=other_pr.author,
                    overlap_lines=total_changes,
                    risk_level=risk_level,
                )
            )

    prediction.total_risky_files = len(set(r.file for r in prediction.risks))
    prediction.high_risk_count = sum(1 for r in prediction.risks if r.risk_level == "high")

    return prediction


def format_conflict_prediction(prediction: ConflictPrediction) -> str:
    """Format conflict prediction as markdown."""
    if not prediction.risks:
        return ""

    risk_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}

    parts = ["### 🔀 Merge Conflict Prediction", ""]

    if prediction.high_risk_count > 0:
        parts.append(
            f"⚠️ **{prediction.high_risk_count} high-risk conflict{'s' if prediction.high_risk_count != 1 else ''}** "
            f"with other open PRs."
        )
        parts.append("")

    parts.append(
        f"**{prediction.total_risky_files}** file{'s' if prediction.total_risky_files != 1 else ''} "
        f"modified by other open PRs:"
    )
    parts.append("")

    for risk in sorted(prediction.risks, key=lambda r: ["high", "medium", "low"].index(r.risk_level)):
        emoji = risk_emoji.get(risk.risk_level, "⚪")
        parts.append(
            f"- {emoji} `{risk.file}` — conflicts with PR #{risk.conflicting_pr} "
            f"({risk.conflicting_title}) by @{risk.conflicting_author}"
        )

    parts.append("")
    parts.append("_Consider coordinating with authors or merging/rebasing to avoid conflicts._")

    return "\n".join(parts)
