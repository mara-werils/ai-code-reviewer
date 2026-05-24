"""Jira integration — links PRs to Jira tickets and posts review summaries.

Features:
- Auto-detect Jira ticket IDs from PR title/branch (e.g., PROJ-123)
- Post review summary as Jira comment
- Transition ticket status based on review outcome
- Add labels to Jira tickets
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Pattern to detect Jira ticket IDs
JIRA_TICKET_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


@dataclass
class JiraConfig:
    """Jira integration configuration."""

    base_url: str = ""  # e.g., https://yourcompany.atlassian.net
    email: str = ""
    api_token: str = ""
    enabled: bool = False
    post_review_comment: bool = True
    transition_on_approval: str = ""  # e.g., "In Review" → "Ready to Merge"
    add_labels: bool = True


@dataclass
class JiraTicketInfo:
    """Basic Jira ticket information."""

    key: str  # e.g., PROJ-123
    summary: str
    status: str
    assignee: str
    issue_type: str


class JiraClient:
    """Jira REST API client."""

    def __init__(self, config: JiraConfig) -> None:
        self.config = config
        self._base = config.base_url.rstrip("/")
        self._auth = (config.email, config.api_token)

    async def get_issue(self, ticket_key: str) -> JiraTicketInfo | None:
        """Fetch a Jira issue by key."""
        url = f"{self._base}/rest/api/3/issue/{ticket_key}"

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(url, auth=self._auth)
                resp.raise_for_status()
                data = resp.json()

                fields = data.get("fields", {})
                return JiraTicketInfo(
                    key=data.get("key", ticket_key),
                    summary=fields.get("summary", ""),
                    status=fields.get("status", {}).get("name", ""),
                    assignee=(fields.get("assignee") or {}).get("displayName", "Unassigned"),
                    issue_type=fields.get("issuetype", {}).get("name", ""),
                )
            except httpx.HTTPError as e:
                logger.warning(f"Failed to fetch Jira issue {ticket_key}: {e}")
                return None

    async def add_comment(self, ticket_key: str, body: str) -> bool:
        """Add a comment to a Jira issue (Atlassian Document Format)."""
        url = f"{self._base}/rest/api/3/issue/{ticket_key}/comment"

        # Convert markdown to ADF (simplified)
        adf_body = {
            "body": {
                "version": 1,
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": body}
                        ],
                    }
                ],
            }
        }

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    url,
                    json=adf_body,
                    auth=self._auth,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                return True
            except httpx.HTTPError as e:
                logger.warning(f"Failed to comment on Jira {ticket_key}: {e}")
                return False

    async def transition_issue(self, ticket_key: str, transition_name: str) -> bool:
        """Transition a Jira issue to a new status."""
        # First, get available transitions
        url = f"{self._base}/rest/api/3/issue/{ticket_key}/transitions"

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(url, auth=self._auth)
                resp.raise_for_status()
                transitions = resp.json().get("transitions", [])

                target = next(
                    (t for t in transitions if t["name"].lower() == transition_name.lower()),
                    None,
                )
                if not target:
                    logger.warning(f"Transition '{transition_name}' not found for {ticket_key}")
                    return False

                resp = await client.post(
                    url,
                    json={"transition": {"id": target["id"]}},
                    auth=self._auth,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                return True
            except httpx.HTTPError as e:
                logger.warning(f"Failed to transition {ticket_key}: {e}")
                return False

    async def add_label(self, ticket_key: str, label: str) -> bool:
        """Add a label to a Jira issue."""
        url = f"{self._base}/rest/api/3/issue/{ticket_key}"

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.put(
                    url,
                    json={"update": {"labels": [{"add": label}]}},
                    auth=self._auth,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                return True
            except httpx.HTTPError as e:
                logger.warning(f"Failed to add label to {ticket_key}: {e}")
                return False


def extract_ticket_ids(text: str) -> list[str]:
    """Extract Jira ticket IDs from text (PR title, branch name, body)."""
    matches = JIRA_TICKET_PATTERN.findall(text)
    return list(dict.fromkeys(matches))  # Deduplicate while preserving order


def format_jira_review_comment(
    pr_number: int,
    pr_title: str,
    risk_level: str,
    comment_count: int,
    critical_count: int,
    cost_usd: float,
    pr_url: str = "",
) -> str:
    """Format review summary for Jira comment."""
    risk_icon = {"low": "✅", "medium": "⚠️", "high": "🔴"}.get(risk_level, "ℹ️")

    parts = [
        f"🤖 AI Code Review — PR #{pr_number}: {pr_title}",
        "",
        f"Risk: {risk_icon} {risk_level.upper()}",
        f"Comments: {comment_count}",
        f"Critical issues: {critical_count}",
        f"Review cost: ${cost_usd:.4f}",
    ]

    if pr_url:
        parts.append(f"PR: {pr_url}")

    return "\n".join(parts)
