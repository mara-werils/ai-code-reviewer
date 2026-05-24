"""Review export — exports review results to SARIF, JSON, CSV, and Markdown.

SARIF format integrates with GitHub Code Scanning, IDE extensions,
and security dashboards. CSV for spreadsheet analysis.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone

from src.review.engine import ReviewComment, ReviewResult

logger = logging.getLogger(__name__)

SARIF_VERSION = "2.1.0"
TOOL_NAME = "ai-code-reviewer"
TOOL_VERSION = "0.5.0"
TOOL_URI = "https://github.com/your-org/ai-code-reviewer"


def export_json(result: ReviewResult, pretty: bool = True) -> str:
    """Export review result as JSON."""
    data = {
        "tool": TOOL_NAME,
        "version": TOOL_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": result.summary,
        "risk_level": result.risk_level,
        "category": result.category,
        "model": result.model,
        "cost_usd": result.cost_usd,
        "duration_ms": result.duration_ms,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "labels": result.labels,
        "comments": [
            {
                "path": c.path,
                "line": c.line,
                "side": c.side,
                "severity": c.severity,
                "body": c.body,
            }
            for c in result.comments
        ],
        "stats": {
            "total_comments": len(result.comments),
            "by_severity": _count_by_severity(result.comments),
        },
    }
    return json.dumps(data, indent=2 if pretty else None, ensure_ascii=False)


def export_sarif(result: ReviewResult, repo: str = "") -> str:
    """Export review result as SARIF (Static Analysis Results Interchange Format).

    SARIF is the standard format for static analysis tools and integrates
    with GitHub Code Scanning, VS Code, and security platforms.
    """
    severity_to_sarif = {
        "critical": "error",
        "warning": "warning",
        "suggestion": "note",
        "info": "note",
    }

    level_to_rank = {
        "critical": 1.0,
        "warning": 5.0,
        "suggestion": 8.0,
        "info": 9.0,
    }

    # Build rules from unique comment types
    rules = []
    rule_indices: dict[str, int] = {}

    for comment in result.comments:
        rule_id = f"ai-review-{comment.severity}"
        if rule_id not in rule_indices:
            rule_indices[rule_id] = len(rules)
            rules.append({
                "id": rule_id,
                "name": f"AI Review ({comment.severity.capitalize()})",
                "shortDescription": {
                    "text": f"AI-detected {comment.severity} issue"
                },
                "defaultConfiguration": {
                    "level": severity_to_sarif.get(comment.severity, "note")
                },
                "properties": {
                    "precision": "medium",
                    "tags": ["ai-review", comment.severity],
                },
            })

    # Build results
    results = []
    for comment in result.comments:
        rule_id = f"ai-review-{comment.severity}"
        results.append({
            "ruleId": rule_id,
            "ruleIndex": rule_indices.get(rule_id, 0),
            "level": severity_to_sarif.get(comment.severity, "note"),
            "message": {
                "text": comment.body,
            },
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": comment.path,
                            "uriBaseId": "%SRCROOT%",
                        },
                        "region": {
                            "startLine": max(1, comment.line),
                        },
                    }
                }
            ],
            "properties": {
                "severity": comment.severity,
                "reviewSide": comment.side,
            },
            "rank": level_to_rank.get(comment.severity, 9.0),
        })

    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": TOOL_NAME,
                        "version": TOOL_VERSION,
                        "informationUri": TOOL_URI,
                        "rules": rules,
                    }
                },
                "results": results,
                "invocations": [
                    {
                        "executionSuccessful": True,
                        "endTimeUtc": datetime.now(timezone.utc).isoformat(),
                    }
                ],
                "properties": {
                    "summary": result.summary,
                    "riskLevel": result.risk_level,
                    "category": result.category,
                    "model": result.model,
                    "costUsd": result.cost_usd,
                },
            }
        ],
    }

    return json.dumps(sarif, indent=2, ensure_ascii=False)


def export_csv(result: ReviewResult) -> str:
    """Export review comments as CSV."""
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "path", "line", "severity", "side", "body",
        "risk_level", "category", "model", "cost_usd",
    ])

    for comment in result.comments:
        writer.writerow([
            comment.path,
            comment.line,
            comment.severity,
            comment.side,
            comment.body.replace("\n", " "),
            result.risk_level,
            result.category,
            result.model,
            f"{result.cost_usd:.4f}",
        ])

    return output.getvalue()


def export_markdown(result: ReviewResult) -> str:
    """Export review as a standalone markdown report."""
    parts = [
        f"# AI Code Review Report",
        "",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Model:** {result.model}",
        f"**Risk Level:** {result.risk_level.upper()}",
        f"**Category:** {result.category}",
        f"**Cost:** ${result.cost_usd:.4f}",
        f"**Duration:** {result.duration_ms}ms",
        "",
        "## Summary",
        "",
        result.summary,
        "",
        "## Findings",
        "",
        f"Total: **{len(result.comments)}** comments",
        "",
    ]

    severity_counts = _count_by_severity(result.comments)
    for sev, count in severity_counts.items():
        parts.append(f"- **{sev.upper()}**: {count}")
    parts.append("")

    # Group by file
    by_file: dict[str, list[ReviewComment]] = {}
    for c in result.comments:
        by_file.setdefault(c.path, []).append(c)

    for path, comments in sorted(by_file.items()):
        parts.append(f"### `{path}`")
        parts.append("")
        for c in sorted(comments, key=lambda x: x.line):
            parts.append(f"**Line {c.line}** [{c.severity.upper()}]:")
            parts.append(f"> {c.body}")
            parts.append("")

    return "\n".join(parts)


def _count_by_severity(comments: list[ReviewComment]) -> dict[str, int]:
    """Count comments by severity."""
    counts: dict[str, int] = {}
    for c in comments:
        counts[c.severity] = counts.get(c.severity, 0) + 1
    return counts
