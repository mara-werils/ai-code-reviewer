"""Multi-model ensemble review — runs multiple LLMs and merges results.

Uses multiple providers in parallel and combines their findings for
higher confidence reviews. Deduplicates overlapping comments and
assigns confidence scores based on model agreement.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from src.config import ReviewConfig
from src.github.client import PRFile, PRInfo
from src.review.engine import ReviewComment, ReviewEngine, ReviewResult

logger = logging.getLogger(__name__)


@dataclass
class EnsembleConfig:
    """Configuration for ensemble review."""

    providers: list[dict[str, str]] = field(default_factory=list)
    # e.g. [{"provider": "openai", "model": "gpt-4o"}, {"provider": "anthropic", "model": "..."}]
    strategy: str = "union"  # union, intersection, majority
    min_agreement: int = 2  # For majority strategy


@dataclass
class EnsembleComment(ReviewComment):
    """A review comment with agreement metadata."""

    agreement_count: int = 1
    total_models: int = 1
    confidence: float = 1.0
    sources: list[str] = field(default_factory=list)


@dataclass
class EnsembleResult:
    """Result of an ensemble review."""

    results: list[ReviewResult]
    merged_comments: list[EnsembleComment]
    summary: str
    risk_level: str
    total_cost_usd: float
    total_duration_ms: int
    models_used: list[str]


def _comments_overlap(a: ReviewComment, b: ReviewComment) -> bool:
    """Check if two comments refer to the same issue."""
    if a.path != b.path:
        return False
    # Same line or within 3 lines
    if abs(a.line - b.line) > 3:
        return False
    # Check for keyword overlap in body
    a_words = set(a.body.lower().split())
    b_words = set(b.body.lower().split())
    overlap = len(a_words & b_words) / max(len(a_words | b_words), 1)
    return overlap > 0.3


def _merge_comments(
    all_comments: list[tuple[str, ReviewComment]],
    strategy: str = "union",
    min_agreement: int = 2,
    total_models: int = 2,
) -> list[EnsembleComment]:
    """Merge comments from multiple models."""
    if not all_comments:
        return []

    # Group overlapping comments
    groups: list[list[tuple[str, ReviewComment]]] = []

    for model_name, comment in all_comments:
        placed = False
        for group in groups:
            # Check if this comment overlaps with any in the group
            if any(_comments_overlap(comment, gc) for _, gc in group):
                group.append((model_name, comment))
                placed = True
                break
        if not placed:
            groups.append([(model_name, comment)])

    # Build merged comments based on strategy
    merged: list[EnsembleComment] = []

    for group in groups:
        agreement = len(group)
        sources = list(set(m for m, _ in group))

        if strategy == "intersection" and agreement < total_models:
            continue
        if strategy == "majority" and agreement < min_agreement:
            continue

        # Pick the most detailed comment
        best_model, best_comment = max(group, key=lambda x: len(x[1].body))

        # Determine severity by consensus
        severities = [c.severity for _, c in group]
        severity_order = ["critical", "warning", "suggestion", "info"]
        most_severe = min(severities, key=lambda s: severity_order.index(s) if s in severity_order else 99)

        confidence = agreement / total_models

        merged.append(
            EnsembleComment(
                path=best_comment.path,
                line=best_comment.line,
                side=best_comment.side,
                body=best_comment.body,
                severity=most_severe,
                position=best_comment.position,
                agreement_count=agreement,
                total_models=total_models,
                confidence=confidence,
                sources=sources,
            )
        )

    # Sort by confidence (highest first), then severity
    severity_rank = {"critical": 0, "warning": 1, "suggestion": 2, "info": 3}
    merged.sort(key=lambda c: (-c.confidence, severity_rank.get(c.severity, 99)))

    return merged


async def ensemble_review(
    configs: list[ReviewConfig],
    pr: PRInfo,
    files: list[PRFile],
    diff: str | None = None,
    strategy: str = "union",
    min_agreement: int = 2,
) -> EnsembleResult:
    """Run ensemble review with multiple models in parallel."""
    if not configs:
        raise ValueError("At least one config required for ensemble review")

    # Create engines
    engines = [ReviewEngine(config) for config in configs]

    # Run all reviews in parallel
    tasks = [engine.review_pr(pr, files, diff) for engine in engines]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter out errors
    valid_results: list[ReviewResult] = []
    models_used: list[str] = []

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(f"Ensemble model {configs[i].provider}/{configs[i].model} failed: {result}")
        else:
            valid_results.append(result)
            models_used.append(result.model)

    if not valid_results:
        raise RuntimeError("All ensemble models failed")

    # Collect all comments with model attribution
    all_comments: list[tuple[str, ReviewComment]] = []
    for result in valid_results:
        for comment in result.comments:
            all_comments.append((result.model, comment))

    # Merge comments
    merged = _merge_comments(
        all_comments,
        strategy=strategy,
        min_agreement=min_agreement,
        total_models=len(valid_results),
    )

    # Determine consensus risk level
    risk_levels = [r.risk_level for r in valid_results]
    risk_order = {"high": 0, "medium": 1, "low": 2}
    consensus_risk = min(risk_levels, key=lambda r: risk_order.get(r, 99))

    # Build consensus summary
    summaries = [r.summary for r in valid_results if r.summary]
    summary = summaries[0] if summaries else "No summary available."

    return EnsembleResult(
        results=valid_results,
        merged_comments=merged,
        summary=summary,
        risk_level=consensus_risk,
        total_cost_usd=sum(r.cost_usd for r in valid_results),
        total_duration_ms=max(r.duration_ms for r in valid_results),
        models_used=models_used,
    )


def format_ensemble_header(result: EnsembleResult) -> str:
    """Format ensemble review header."""
    parts = [
        "### 🔀 Ensemble Review",
        "",
        f"**Models:** {', '.join(result.models_used)}",
        f"**Strategy:** merged results | **Total cost:** ${result.total_cost_usd:.4f}",
        "",
    ]

    # Confidence distribution
    high_conf = sum(1 for c in result.merged_comments if c.confidence >= 0.8)
    med_conf = sum(1 for c in result.merged_comments if 0.5 <= c.confidence < 0.8)
    low_conf = sum(1 for c in result.merged_comments if c.confidence < 0.5)

    if result.merged_comments:
        parts.append(
            f"**Comment confidence:** "
            f"🟢 High ({high_conf}) | 🟡 Medium ({med_conf}) | 🔴 Low ({low_conf})"
        )
        parts.append("")

    return "\n".join(parts)
