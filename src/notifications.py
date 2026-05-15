"""Notification webhooks — send review summaries to Slack/Discord/Teams.

Configure in .pr-reviewer.yml:
    notifications:
      slack_webhook: https://hooks.slack.com/services/T.../B.../xxx
      discord_webhook: https://discord.com/api/webhooks/.../...
      teams_webhook: https://outlook.office.com/webhook/...
      notify_on: [high, critical]  # risk levels that trigger notification
"""

from __future__ import annotations

import logging

import httpx

from src.review.engine import ReviewResult

logger = logging.getLogger(__name__)

RISK_ICON = {
    "low": "white_check_mark",
    "medium": "warning",
    "high": "rotating_light",
}


def _build_summary(result: ReviewResult, repo: str, pr_number: int, pr_title: str) -> str:
    """Build a plain-text summary for notifications."""
    severity_counts = {}
    for c in result.comments:
        severity_counts[c.severity] = severity_counts.get(c.severity, 0) + 1

    parts = [
        f"AI Code Review: {repo}#{pr_number}",
        f"Title: {pr_title}",
        f"Risk: {result.risk_level.upper()} | {len(result.comments)} comments",
        f"Cost: ${result.cost_usd:.4f} | Model: {result.model}",
    ]

    if severity_counts:
        counts = ", ".join(f"{k}: {v}" for k, v in sorted(severity_counts.items()))
        parts.append(f"Breakdown: {counts}")

    return "\n".join(parts)


async def notify_slack(
    webhook_url: str,
    result: ReviewResult,
    repo: str,
    pr_number: int,
    pr_title: str,
    pr_url: str,
) -> None:
    """Send review summary to Slack via incoming webhook."""
    icon = RISK_ICON.get(result.risk_level, "speech_balloon")
    summary = _build_summary(result, repo, pr_number, pr_title)

    payload = {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":{icon}: *<{pr_url}|{repo}#{pr_number}>* — {pr_title}\n"
                        f"Risk: *{result.risk_level.upper()}* | "
                        f"{len(result.comments)} comments | "
                        f"${result.cost_usd:.4f}"
                    ),
                },
            },
        ],
    }

    if result.summary:
        payload["blocks"].append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": result.summary[:300]}],
        })

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info(f"Slack notification sent for PR #{pr_number}")
    except httpx.HTTPError as e:
        logger.warning(f"Slack notification failed: {e}")


async def notify_discord(
    webhook_url: str,
    result: ReviewResult,
    repo: str,
    pr_number: int,
    pr_title: str,
    pr_url: str,
) -> None:
    """Send review summary to Discord via webhook."""
    color_map = {"low": 0x2ECC71, "medium": 0xF39C12, "high": 0xE74C3C}
    color = color_map.get(result.risk_level, 0x3498DB)

    payload = {
        "embeds": [
            {
                "title": f"AI Code Review: {repo}#{pr_number}",
                "description": pr_title,
                "url": pr_url,
                "color": color,
                "fields": [
                    {"name": "Risk", "value": result.risk_level.upper(), "inline": True},
                    {"name": "Comments", "value": str(len(result.comments)), "inline": True},
                    {"name": "Cost", "value": f"${result.cost_usd:.4f}", "inline": True},
                ],
                "footer": {"text": f"Model: {result.model}"},
            }
        ],
    }

    if result.summary:
        payload["embeds"][0]["fields"].append({
            "name": "Summary",
            "value": result.summary[:1024],
            "inline": False,
        })

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info(f"Discord notification sent for PR #{pr_number}")
    except httpx.HTTPError as e:
        logger.warning(f"Discord notification failed: {e}")


async def notify_teams(
    webhook_url: str,
    result: ReviewResult,
    repo: str,
    pr_number: int,
    pr_title: str,
    pr_url: str,
) -> None:
    """Send review summary to Microsoft Teams via webhook."""
    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "summary": f"AI Code Review: {repo}#{pr_number}",
        "themeColor": "E74C3C" if result.risk_level == "high" else "2ECC71",
        "title": f"AI Code Review: {repo}#{pr_number}",
        "sections": [
            {
                "activityTitle": pr_title,
                "facts": [
                    {"name": "Risk", "value": result.risk_level.upper()},
                    {"name": "Comments", "value": str(len(result.comments))},
                    {"name": "Cost", "value": f"${result.cost_usd:.4f}"},
                    {"name": "Model", "value": result.model},
                ],
                "text": result.summary[:500] if result.summary else "",
            }
        ],
        "potentialAction": [
            {
                "@type": "OpenUri",
                "name": "View PR",
                "targets": [{"os": "default", "uri": pr_url}],
            }
        ],
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info(f"Teams notification sent for PR #{pr_number}")
    except httpx.HTTPError as e:
        logger.warning(f"Teams notification failed: {e}")


async def send_notifications(
    config_notifications: dict,
    result: ReviewResult,
    repo: str,
    pr_number: int,
    pr_title: str,
) -> None:
    """Send notifications based on config.

    config_notifications example:
        {
            "slack_webhook": "https://hooks.slack.com/...",
            "discord_webhook": "https://discord.com/api/webhooks/...",
            "teams_webhook": "https://outlook.office.com/webhook/...",
            "notify_on": ["high", "critical"],
        }
    """
    if not config_notifications:
        return

    notify_on = config_notifications.get("notify_on", ["high"])
    if result.risk_level not in notify_on:
        return

    pr_url = f"https://github.com/{repo}/pull/{pr_number}"

    slack_url = config_notifications.get("slack_webhook", "")
    if slack_url:
        await notify_slack(slack_url, result, repo, pr_number, pr_title, pr_url)

    discord_url = config_notifications.get("discord_webhook", "")
    if discord_url:
        await notify_discord(discord_url, result, repo, pr_number, pr_title, pr_url)

    teams_url = config_notifications.get("teams_webhook", "")
    if teams_url:
        await notify_teams(teams_url, result, repo, pr_number, pr_title, pr_url)
