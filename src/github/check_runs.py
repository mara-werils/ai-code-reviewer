"""GitHub Check Runs integration — report review results as GitHub Checks.

Instead of (or in addition to) PR comments, report findings as
GitHub Check Run annotations. This integrates with the GitHub UI
Checks tab and shows inline annotations in the Files Changed view.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from src.review.engine import ReviewComment, ReviewResult

logger = logging.getLogger(__name__)

CHECK_RUN_NAME = "AI Code Review"


@dataclass
class CheckAnnotation:
    """A single annotation in a check run."""

    path: str
    start_line: int
    end_line: int
    annotation_level: str  # notice, warning, failure
    message: str
    title: str = ""
    raw_details: str = ""


def _severity_to_level(severity: str) -> str:
    """Map review severity to GitHub annotation level."""
    mapping = {
        "critical": "failure",
        "warning": "warning",
        "suggestion": "notice",
        "info": "notice",
    }
    return mapping.get(severity, "notice")


def build_annotations(comments: list[ReviewComment]) -> list[CheckAnnotation]:
    """Convert review comments to check run annotations."""
    annotations = []
    for comment in comments:
        annotations.append(
            CheckAnnotation(
                path=comment.path,
                start_line=max(1, comment.line),
                end_line=max(1, comment.line),
                annotation_level=_severity_to_level(comment.severity),
                message=comment.body[:64000],  # GitHub limit
                title=f"[{comment.severity.upper()}]",
            )
        )
    return annotations


def build_check_output(result: ReviewResult) -> dict:
    """Build check run output payload."""
    annotations = build_annotations(result.comments)

    # Build summary
    by_severity: dict[str, int] = {}
    for c in result.comments:
        by_severity[c.severity] = by_severity.get(c.severity, 0) + 1

    summary_parts = [
        f"**Risk Level:** {result.risk_level.upper()}",
        f"**Category:** {result.category}",
        f"**Model:** {result.model}",
        f"**Cost:** ${result.cost_usd:.4f}",
        "",
        "### Findings",
        "",
    ]

    for sev, count in sorted(by_severity.items()):
        emoji = {"critical": "🔴", "warning": "🟡", "suggestion": "🔵", "info": "ℹ️"}.get(sev, "")
        summary_parts.append(f"- {emoji} **{sev.upper()}**: {count}")

    summary = "\n".join(summary_parts)

    # Determine conclusion
    critical_count = by_severity.get("critical", 0)
    warning_count = by_severity.get("warning", 0)

    if critical_count > 0:
        conclusion = "failure"
    elif warning_count > 3:
        conclusion = "neutral"
    else:
        conclusion = "success"

    return {
        "name": CHECK_RUN_NAME,
        "conclusion": conclusion,
        "output": {
            "title": f"AI Review: {result.risk_level.upper()} risk, {len(result.comments)} findings",
            "summary": summary,
            "text": result.summary,
            "annotations": [
                {
                    "path": a.path,
                    "start_line": a.start_line,
                    "end_line": a.end_line,
                    "annotation_level": a.annotation_level,
                    "message": a.message,
                    "title": a.title,
                }
                for a in annotations[:50]  # GitHub limit: 50 per request
            ],
        },
    }


async def create_check_run(
    token: str,
    repo: str,
    head_sha: str,
    result: ReviewResult,
) -> str | None:
    """Create a GitHub Check Run with review results."""
    url = f"https://api.github.com/repos/{repo}/check-runs"

    payload = build_check_output(result)
    payload["head_sha"] = head_sha
    payload["status"] = "completed"

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            check_url = data.get("html_url", "")
            logger.info(f"Check run created: {check_url}")
            return check_url
        except httpx.HTTPError as e:
            logger.warning(f"Failed to create check run: {e}")
            return None


async def update_check_run(
    token: str,
    repo: str,
    check_run_id: int,
    result: ReviewResult,
) -> bool:
    """Update an existing check run."""
    url = f"https://api.github.com/repos/{repo}/check-runs/{check_run_id}"

    payload = build_check_output(result)
    payload["status"] = "completed"

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.patch(url, json=payload, headers=headers)
            resp.raise_for_status()
            return True
        except httpx.HTTPError as e:
            logger.warning(f"Failed to update check run: {e}")
            return False
