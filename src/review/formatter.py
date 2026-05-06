"""Format review results into GitHub markdown."""

from __future__ import annotations

from src.review.engine import ReviewResult

SEVERITY_LABEL = {
    "critical": "[CRITICAL]",
    "warning": "[WARNING]",
    "suggestion": "[SUGGESTION]",
    "info": "[INFO]",
}

RISK_LABEL = {
    "low": "[LOW]",
    "medium": "[MEDIUM]",
    "high": "[HIGH]",
}

CATEGORY_LABEL = {
    "bugfix": "Bug Fix",
    "feature": "Feature",
    "refactor": "Refactor",
    "docs": "Docs",
    "chore": "Chore",
    "test": "Test",
    "other": "Other",
}


def format_review_body(result: ReviewResult) -> str:
    """Format the main review comment body."""
    risk_label = RISK_LABEL.get(result.risk_level, "[INFO]")
    cat_label = CATEGORY_LABEL.get(result.category, result.category)

    parts = [
        "## AI Code Review",
        "",
        f"> {result.summary}",
        "",
        f"**{cat_label}** | Risk: {risk_label} {result.risk_level.capitalize()}",
        "",
    ]

    if result.comments:
        # Stats
        severity_counts = {}
        for c in result.comments:
            severity_counts[c.severity] = severity_counts.get(c.severity, 0) + 1

        stats_parts = []
        for sev in ["critical", "warning", "suggestion", "info"]:
            count = severity_counts.get(sev, 0)
            if count:
                label = SEVERITY_LABEL[sev]
                stats_parts.append(f"{label} {count} {sev}")

        parts.append(f"**{len(result.comments)} comments:** {' · '.join(stats_parts)}")
        parts.append("")

        # Comments without inline placement go in body
        bodyonly = [c for c in result.comments if not c.line]
        if bodyonly:
            parts.append("<details><summary>General comments</summary>\n")
            for c in bodyonly:
                label = SEVERITY_LABEL.get(c.severity, "[INFO]")
                parts.append(f"- {label} **{c.path}**: {c.body}")
            parts.append("\n</details>")
            parts.append("")
    else:
        parts.append("**No issues found.** This PR looks good!")
        parts.append("")

    # Footer
    parts.extend(
        [
            "---",
            f"<sub>Cost: ${result.cost_usd:.4f} | {result.duration_ms / 1000:.1f}s | "
            f"{result.model}</sub>",
        ]
    )

    return "\n".join(parts)


def format_inline_comment(severity: str, body: str) -> str:
    """Format an inline review comment."""
    label = SEVERITY_LABEL.get(severity, "[INFO]")
    sev_name = severity.capitalize()
    return f"**{label} {sev_name}**\n\n{body}"


def build_github_review_comments(result: ReviewResult) -> list[dict]:
    """Build list of inline comments for GitHub review API."""
    comments = []
    for c in result.comments:
        if not c.line:
            continue  # General comments go in the body

        comment: dict = {
            "path": c.path,
            "body": format_inline_comment(c.severity, c.body),
        }
        if c.position:
            comment["position"] = c.position
        else:
            comment["line"] = c.line
            comment["side"] = c.side
        comments.append(comment)

    return comments
