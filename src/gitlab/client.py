"""GitLab API client for merge request reviews."""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from src.github.client import PRFile, PRInfo

logger = logging.getLogger(__name__)


class GitLabAPI:
    """Async GitLab API client for merge request reviews.

    Uses the same PRInfo/PRFile dataclasses as the GitHub client
    so the review engine works identically for both platforms.
    """

    def __init__(
        self,
        token: str,
        base_url: str = "https://gitlab.com",
    ) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=f"{self._base}/api/v4",
            headers={
                "PRIVATE-TOKEN": token,
                "Accept": "application/json",
            },
            timeout=30.0,
        )

    @staticmethod
    def _encode_project(project: str) -> str:
        """URL-encode a project path (e.g. 'group/repo' -> 'group%2Frepo')."""
        return quote(project, safe="")

    async def get_mr(self, project: str, mr_iid: int) -> PRInfo:
        """Get merge request info (mapped to PRInfo for engine compatibility)."""
        pid = self._encode_project(project)
        resp = await self._client.get(f"/projects/{pid}/merge_requests/{mr_iid}")
        resp.raise_for_status()
        data = resp.json()
        return PRInfo(
            number=data["iid"],
            title=data["title"],
            body=data.get("description") or "",
            head_sha=data["sha"],
            base_sha=data["diff_refs"]["base_sha"],
            base_ref=data["target_branch"],
            head_ref=data["source_branch"],
            repo_full_name=project,
            author=data["author"]["username"],
        )

    async def get_mr_diff(self, project: str, mr_iid: int) -> str:
        """Get the full unified diff for a merge request."""
        pid = self._encode_project(project)
        # Get MR versions (each version has diffs)
        resp = await self._client.get(
            f"/projects/{pid}/merge_requests/{mr_iid}/changes",
            params={"access_raw_diffs": "true"},
        )
        resp.raise_for_status()
        data = resp.json()

        # Build unified diff from changes
        parts: list[str] = []
        for change in data.get("changes", []):
            old_path = change.get("old_path", "")
            new_path = change.get("new_path", "")
            diff_text = change.get("diff", "")
            if diff_text:
                parts.append(f"diff --git a/{old_path} b/{new_path}")
                parts.append(diff_text)

        return "\n".join(parts)

    async def get_mr_files(self, project: str, mr_iid: int) -> list[PRFile]:
        """Get changed files in a merge request."""
        pid = self._encode_project(project)
        resp = await self._client.get(
            f"/projects/{pid}/merge_requests/{mr_iid}/changes",
            params={"access_raw_diffs": "true"},
        )
        resp.raise_for_status()
        data = resp.json()

        files: list[PRFile] = []
        for change in data.get("changes", []):
            # Determine status
            if change.get("new_file"):
                status = "added"
            elif change.get("deleted_file"):
                status = "removed"
            elif change.get("renamed_file"):
                status = "renamed"
            else:
                status = "modified"

            diff_text = change.get("diff", "")
            additions = diff_text.count("\n+") - diff_text.count("\n+++")
            deletions = diff_text.count("\n-") - diff_text.count("\n---")

            files.append(
                PRFile(
                    filename=change.get("new_path", change.get("old_path", "")),
                    status=status,
                    additions=max(0, additions),
                    deletions=max(0, deletions),
                    patch=diff_text,
                )
            )

        return files

    async def get_file_content(self, project: str, path: str, ref: str) -> str:
        """Get file content at a specific ref."""
        pid = self._encode_project(project)
        file_path = quote(path, safe="")
        resp = await self._client.get(
            f"/projects/{pid}/repository/files/{file_path}/raw",
            params={"ref": ref},
        )
        if resp.status_code == 404:
            return ""
        resp.raise_for_status()
        return resp.text

    async def post_mr_note(self, project: str, mr_iid: int, body: str) -> int:
        """Post a comment (note) on a merge request."""
        pid = self._encode_project(project)
        resp = await self._client.post(
            f"/projects/{pid}/merge_requests/{mr_iid}/notes",
            json={"body": body},
        )
        resp.raise_for_status()
        return resp.json()["id"]

    async def post_inline_comments(
        self,
        project: str,
        mr_iid: int,
        head_sha: str,
        base_sha: str,
        comments: list[dict],
    ) -> int:
        """Post inline diff comments on a merge request."""
        pid = self._encode_project(project)
        posted = 0

        for c in comments:
            line = c.get("line", 1)
            payload: dict = {
                "body": c["body"],
                "position": {
                    "base_sha": base_sha,
                    "head_sha": head_sha,
                    "start_sha": base_sha,
                    "position_type": "text",
                    "new_path": c["path"],
                    "old_path": c["path"],
                    "new_line": line,
                },
            }
            try:
                resp = await self._client.post(
                    f"/projects/{pid}/merge_requests/{mr_iid}/discussions",
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    posted += 1
                else:
                    logger.warning(
                        f"Failed to post comment on {c['path']}:{line}: "
                        f"{resp.status_code} {resp.text[:300]}"
                    )
            except Exception as e:
                logger.warning(f"Failed to post comment on {c['path']}:{line}: {e}")

        return posted

    async def add_labels(self, project: str, mr_iid: int, labels: list[str]) -> None:
        """Add labels to a merge request."""
        pid = self._encode_project(project)
        # GitLab uses comma-separated labels in PUT
        resp = await self._client.get(f"/projects/{pid}/merge_requests/{mr_iid}")
        resp.raise_for_status()
        existing = resp.json().get("labels", [])
        all_labels = list(set(existing + labels))

        await self._client.put(
            f"/projects/{pid}/merge_requests/{mr_iid}",
            json={"labels": ",".join(all_labels)},
        )

    async def get_existing_notes(self, project: str, mr_iid: int) -> list[dict]:
        """Get existing notes on a merge request."""
        pid = self._encode_project(project)
        resp = await self._client.get(
            f"/projects/{pid}/merge_requests/{mr_iid}/notes",
            params={"per_page": 100, "sort": "desc"},
        )
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._client.aclose()
