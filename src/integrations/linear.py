"""Linear integration — links PRs to Linear issues and posts review summaries.

Features:
- Auto-detect Linear issue IDs from PR title/branch (e.g., ENG-123)
- Post review summary as Linear comment
- Update issue status based on review outcome
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Linear issue IDs follow the same pattern as Jira (TEAM-123)
LINEAR_ISSUE_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")

LINEAR_API_URL = "https://api.linear.app/graphql"


@dataclass
class LinearConfig:
    """Linear integration configuration."""

    api_key: str = ""
    enabled: bool = False
    post_review_comment: bool = True
    update_status_on_review: str = ""  # e.g., "In Review"
    update_status_on_approval: str = ""  # e.g., "Ready to Merge"


@dataclass
class LinearIssueInfo:
    """Basic Linear issue information."""

    id: str
    identifier: str  # e.g., ENG-123
    title: str
    status: str
    assignee: str
    priority: int


class LinearClient:
    """Linear GraphQL API client."""

    def __init__(self, config: LinearConfig) -> None:
        self.config = config
        self._headers = {
            "Authorization": config.api_key,
            "Content-Type": "application/json",
        }

    async def _query(self, query: str, variables: dict | None = None) -> dict:
        """Execute a GraphQL query."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                LINEAR_API_URL,
                json={"query": query, "variables": variables or {}},
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_issue(self, identifier: str) -> LinearIssueInfo | None:
        """Fetch a Linear issue by identifier (e.g., ENG-123)."""
        query = """
        query IssueByIdentifier($identifier: String!) {
            issueSearch(filter: { identifier: { eq: $identifier } }, first: 1) {
                nodes {
                    id
                    identifier
                    title
                    state { name }
                    assignee { name }
                    priority
                }
            }
        }
        """
        try:
            result = await self._query(query, {"identifier": identifier})
            nodes = result.get("data", {}).get("issueSearch", {}).get("nodes", [])
            if not nodes:
                return None

            node = nodes[0]
            return LinearIssueInfo(
                id=node["id"],
                identifier=node["identifier"],
                title=node["title"],
                status=node.get("state", {}).get("name", ""),
                assignee=(node.get("assignee") or {}).get("name", "Unassigned"),
                priority=node.get("priority", 0),
            )
        except Exception as e:
            logger.warning(f"Failed to fetch Linear issue {identifier}: {e}")
            return None

    async def add_comment(self, issue_id: str, body: str) -> bool:
        """Add a comment to a Linear issue."""
        mutation = """
        mutation CommentCreate($input: CommentCreateInput!) {
            commentCreate(input: $input) {
                success
            }
        }
        """
        try:
            result = await self._query(
                mutation,
                {"input": {"issueId": issue_id, "body": body}},
            )
            return result.get("data", {}).get("commentCreate", {}).get("success", False)
        except Exception as e:
            logger.warning(f"Failed to comment on Linear issue: {e}")
            return False

    async def update_status(self, issue_id: str, status_name: str) -> bool:
        """Update issue status by finding the matching workflow state."""
        # First get workflow states for the issue's team
        query = """
        query Issue($id: String!) {
            issue(id: $id) {
                team {
                    states {
                        nodes {
                            id
                            name
                        }
                    }
                }
            }
        }
        """
        try:
            result = await self._query(query, {"id": issue_id})
            states = (
                result.get("data", {})
                .get("issue", {})
                .get("team", {})
                .get("states", {})
                .get("nodes", [])
            )

            target_state = next(
                (s for s in states if s["name"].lower() == status_name.lower()),
                None,
            )
            if not target_state:
                logger.warning(f"Status '{status_name}' not found in team workflow")
                return False

            mutation = """
            mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) {
                issueUpdate(id: $id, input: $input) {
                    success
                }
            }
            """
            result = await self._query(
                mutation,
                {"id": issue_id, "input": {"stateId": target_state["id"]}},
            )
            return result.get("data", {}).get("issueUpdate", {}).get("success", False)
        except Exception as e:
            logger.warning(f"Failed to update Linear status: {e}")
            return False


def extract_linear_ids(text: str) -> list[str]:
    """Extract Linear issue IDs from text."""
    matches = LINEAR_ISSUE_PATTERN.findall(text)
    return list(dict.fromkeys(matches))


def format_linear_review_comment(
    pr_number: int,
    pr_title: str,
    risk_level: str,
    comment_count: int,
    critical_count: int,
    pr_url: str = "",
) -> str:
    """Format review summary for Linear comment (markdown)."""
    risk_icon = {"low": "✅", "medium": "⚠️", "high": "🔴"}.get(risk_level, "ℹ️")

    parts = [
        f"## 🤖 AI Code Review",
        f"**PR #{pr_number}**: {pr_title}",
        "",
        f"- **Risk**: {risk_icon} {risk_level.upper()}",
        f"- **Comments**: {comment_count}",
        f"- **Critical**: {critical_count}",
    ]

    if pr_url:
        parts.append(f"- **PR**: [{pr_title}]({pr_url})")

    return "\n".join(parts)
