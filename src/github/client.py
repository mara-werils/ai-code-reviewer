"""Lightweight GitHub client for PR review actions."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.github.com"


@dataclass
class PRInfo:
    number: int
    title: str
    body: str
    head_sha: str
    base_sha: str
    base_ref: str
    head_ref: str
    repo_full_name: str
    author: str


@dataclass
class PRFile:
    filename: str
    status: str  # added, removed, modified, renamed
    additions: int
    deletions: int
    patch: str


class GitHubAPI:
    """Async GitHub API client using token auth."""

    def __init__(self, token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    async def get_pr(self, repo: str, pr_number: int) -> PRInfo:
        resp = await self._client.get(f"/repos/{repo}/pulls/{pr_number}")
        resp.raise_for_status()
        data = resp.json()
        return PRInfo(
            number=data["number"],
            title=data["title"],
            body=data.get("body") or "",
            head_sha=data["head"]["sha"],
            base_sha=data["base"]["sha"],
            base_ref=data["base"]["ref"],
            head_ref=data["head"]["ref"],
            repo_full_name=repo,
            author=data["user"]["login"],
        )

    async def get_pr_diff(self, repo: str, pr_number: int) -> str:
        resp = await self._client.get(
            f"/repos/{repo}/pulls/{pr_number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        resp.raise_for_status()
        return resp.text

    async def get_pr_files(self, repo: str, pr_number: int) -> list[PRFile]:
        files: list[PRFile] = []
        page = 1
        while True:
            resp = await self._client.get(
                f"/repos/{repo}/pulls/{pr_number}/files",
                params={"per_page": 100, "page": page},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            for f in data:
                files.append(
                    PRFile(
                        filename=f["filename"],
                        status=f["status"],
                        additions=f["additions"],
                        deletions=f["deletions"],
                        patch=f.get("patch", ""),
                    )
                )
            if len(data) < 100:
                break
            page += 1
        return files

    async def get_file_content(self, repo: str, path: str, ref: str) -> str:
        resp = await self._client.get(
            f"/repos/{repo}/contents/{path}",
            params={"ref": ref},
            headers={"Accept": "application/vnd.github.v3.raw"},
        )
        if resp.status_code == 404:
            return ""
        resp.raise_for_status()
        return resp.text

    async def post_review(
        self,
        repo: str,
        pr_number: int,
        body: str,
        comments: list[dict] | None = None,
        event: str = "COMMENT",
        commit_id: str | None = None,
    ) -> int:
        payload: dict = {
            "body": body,
            "event": event,
        }
        if commit_id:
            payload["commit_id"] = commit_id
        if comments:
            payload["comments"] = comments

        resp = await self._client.post(
            f"/repos/{repo}/pulls/{pr_number}/reviews",
            json=payload,
        )
        if resp.status_code == 422:
            logger.error(f"GitHub rejected review: {resp.text}")
        resp.raise_for_status()
        return resp.json()["id"]

    async def post_inline_comments(
        self,
        repo: str,
        pr_number: int,
        commit_id: str,
        comments: list[dict],
    ) -> int:
        """Post inline comments individually using the review comment API."""
        posted = 0
        for c in comments:
            payload: dict = {
                "commit_id": commit_id,
                "path": c["path"],
                "body": c["body"],
            }
            if "position" in c:
                payload["position"] = c["position"]
            else:
                payload["position"] = c.get("line", 1)
            try:
                resp = await self._client.post(
                    f"/repos/{repo}/pulls/{pr_number}/comments",
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    posted += 1
                else:
                    line_info = c.get("line") or c.get("position", "?")
                    logger.warning(
                        f"Failed to post comment on {c['path']}:{line_info}: "
                        f"{resp.status_code} {resp.text[:300]}"
                    )
            except Exception as e:
                line_info = c.get("line") or c.get("position", "?")
                logger.warning(f"Failed to post comment on {c['path']}:{line_info}: {e}")
        return posted

    async def post_comment(self, repo: str, pr_number: int, body: str) -> int:
        resp = await self._client.post(
            f"/repos/{repo}/issues/{pr_number}/comments",
            json={"body": body},
        )
        resp.raise_for_status()
        return resp.json()["id"]

    async def add_labels(self, repo: str, pr_number: int, labels: list[str]) -> None:
        await self._client.post(
            f"/repos/{repo}/issues/{pr_number}/labels",
            json={"labels": labels},
        )

    async def get_existing_reviews(self, repo: str, pr_number: int) -> list[dict]:
        resp = await self._client.get(
            f"/repos/{repo}/pulls/{pr_number}/reviews",
            params={"per_page": 100},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_review_comments(self, repo: str, pr_number: int) -> list[dict]:
        """Get all review comments (inline comments) on a PR."""
        comments: list[dict] = []
        page = 1
        while True:
            resp = await self._client.get(
                f"/repos/{repo}/pulls/{pr_number}/comments",
                params={"per_page": 100, "page": page},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            comments.extend(data)
            if len(data) < 100:
                break
            page += 1
        return comments

    async def get_issue_comments(self, repo: str, pr_number: int) -> list[dict]:
        """Get all issue-level comments on a PR."""
        resp = await self._client.get(
            f"/repos/{repo}/issues/{pr_number}/comments",
            params={"per_page": 100},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_file_sha(self, repo: str, path: str, ref: str) -> str:
        """Get the blob SHA for a file (needed for updates via Contents API)."""
        resp = await self._client.get(
            f"/repos/{repo}/contents/{path}",
            params={"ref": ref},
        )
        if resp.status_code == 404:
            return ""
        resp.raise_for_status()
        return resp.json().get("sha", "")

    async def create_or_update_file(
        self,
        repo: str,
        path: str,
        content: str,
        message: str,
        branch: str,
        file_sha: str = "",
    ) -> str:
        """Create or update a file via the Contents API. Returns the new commit SHA."""
        encoded = base64.b64encode(content.encode()).decode()
        payload: dict = {
            "message": message,
            "content": encoded,
            "branch": branch,
        }
        if file_sha:
            payload["sha"] = file_sha

        resp = await self._client.put(
            f"/repos/{repo}/contents/{path}",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["commit"]["sha"]

    async def get_review_comment(self, repo: str, comment_id: int) -> dict:
        """Get a single review comment by ID."""
        resp = await self._client.get(f"/repos/{repo}/pulls/comments/{comment_id}")
        resp.raise_for_status()
        return resp.json()

    async def get_review_comment_thread(
        self, repo: str, pr_number: int, comment_id: int
    ) -> list[dict]:
        """Get all comments in a review comment thread (same in_reply_to chain).

        Returns comments sorted chronologically.
        """
        all_comments = await self.get_review_comments(repo, pr_number)

        # Find the root comment ID (thread anchor)
        target = None
        for c in all_comments:
            if c["id"] == comment_id:
                target = c
                break

        if not target:
            return []

        # The root is either this comment or the one it replies to
        root_id = target.get("in_reply_to_id") or target["id"]

        # Collect all comments in this thread
        thread = []
        for c in all_comments:
            if c["id"] == root_id or c.get("in_reply_to_id") == root_id:
                thread.append(c)

        thread.sort(key=lambda c: c.get("created_at", ""))
        return thread

    async def reply_to_review_comment(
        self, repo: str, pr_number: int, comment_id: int, body: str
    ) -> int:
        """Reply to a review comment (creates a comment in the same thread)."""
        resp = await self._client.post(
            f"/repos/{repo}/pulls/{pr_number}/comments",
            json={
                "body": body,
                "in_reply_to": comment_id,
            },
        )
        resp.raise_for_status()
        return resp.json()["id"]

    async def close(self) -> None:
        await self._client.aclose()
