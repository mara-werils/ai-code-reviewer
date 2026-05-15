"""Bitbucket Cloud API client for pull request reviews.

Uses the same PRInfo/PRFile dataclasses as the GitHub client
so the review engine works identically across all platforms.

Auth: Bitbucket App Password or OAuth token.
API docs: https://developer.atlassian.com/cloud/bitbucket/rest/intro/
"""

from __future__ import annotations

import logging

import httpx

from src.github.client import PRFile, PRInfo

logger = logging.getLogger(__name__)

BASE_URL = "https://api.bitbucket.org/2.0"


class BitbucketAPI:
    """Async Bitbucket Cloud API client for PR reviews."""

    def __init__(
        self,
        username: str,
        app_password: str,
        base_url: str = BASE_URL,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            auth=(username, app_password),
            headers={"Accept": "application/json"},
            timeout=30.0,
        )

    async def get_pr(self, workspace: str, repo_slug: str, pr_id: int) -> PRInfo:
        """Get pull request info (mapped to PRInfo for engine compatibility)."""
        resp = await self._client.get(
            f"/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}",
        )
        resp.raise_for_status()
        data = resp.json()

        source = data.get("source", {})
        dest = data.get("destination", {})
        author = data.get("author", {})

        return PRInfo(
            number=data["id"],
            title=data["title"],
            body=data.get("description") or "",
            head_sha=source.get("commit", {}).get("hash", ""),
            base_sha=dest.get("commit", {}).get("hash", ""),
            base_ref=dest.get("branch", {}).get("name", "main"),
            head_ref=source.get("branch", {}).get("name", ""),
            repo_full_name=f"{workspace}/{repo_slug}",
            author=author.get("display_name", author.get("nickname", "")),
        )

    async def get_pr_diff(self, workspace: str, repo_slug: str, pr_id: int) -> str:
        """Get the unified diff for a pull request."""
        resp = await self._client.get(
            f"/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/diff",
            headers={"Accept": "text/plain"},
        )
        resp.raise_for_status()
        return resp.text

    async def get_pr_files(self, workspace: str, repo_slug: str, pr_id: int) -> list[PRFile]:
        """Get changed files in a pull request via the diffstat endpoint."""
        files: list[PRFile] = []
        url = f"/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/diffstat"

        while url:
            resp = await self._client.get(url)
            resp.raise_for_status()
            data = resp.json()

            for entry in data.get("values", []):
                status_map = {
                    "added": "added",
                    "removed": "removed",
                    "modified": "modified",
                    "renamed": "renamed",
                }
                bb_status = entry.get("status", "modified")
                status = status_map.get(bb_status, "modified")

                new_path = entry.get("new", {})
                old_path = entry.get("old", {})
                filename = ""
                if new_path:
                    filename = new_path.get("path", "")
                elif old_path:
                    filename = old_path.get("path", "")

                lines_added = entry.get("lines_added", 0)
                lines_removed = entry.get("lines_removed", 0)

                files.append(
                    PRFile(
                        filename=filename,
                        status=status,
                        additions=lines_added,
                        deletions=lines_removed,
                        patch="",  # Patches come from the diff endpoint
                    )
                )

            url = data.get("next", "")

        # Enrich files with patch data from the diff
        if files:
            diff = await self.get_pr_diff(workspace, repo_slug, pr_id)
            patches = _parse_diff_patches(diff)
            for f in files:
                f.patch = patches.get(f.filename, "")

        return files

    async def get_file_content(self, workspace: str, repo_slug: str, path: str, ref: str) -> str:
        """Get file content at a specific commit."""
        resp = await self._client.get(
            f"/repositories/{workspace}/{repo_slug}/src/{ref}/{path}",
        )
        if resp.status_code == 404:
            return ""
        resp.raise_for_status()
        return resp.text

    async def post_comment(self, workspace: str, repo_slug: str, pr_id: int, body: str) -> int:
        """Post a general comment on a pull request."""
        resp = await self._client.post(
            f"/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/comments",
            json={"content": {"raw": body}},
        )
        resp.raise_for_status()
        return resp.json()["id"]

    async def post_inline_comments(
        self,
        workspace: str,
        repo_slug: str,
        pr_id: int,
        comments: list[dict],
    ) -> int:
        """Post inline comments on specific lines in the diff."""
        posted = 0
        for c in comments:
            path = c.get("path", "")
            line = c.get("line", 1)
            body = c.get("body", "")

            payload: dict = {
                "content": {"raw": body},
                "inline": {
                    "path": path,
                    "to": line,
                },
            }

            try:
                resp = await self._client.post(
                    f"/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/comments",
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    posted += 1
                else:
                    logger.warning(
                        f"Failed to post comment on {path}:{line}: "
                        f"{resp.status_code} {resp.text[:300]}"
                    )
            except Exception as e:
                logger.warning(f"Failed to post comment on {path}:{line}: {e}")

        return posted

    async def get_pr_comments(self, workspace: str, repo_slug: str, pr_id: int) -> list[dict]:
        """Get all comments on a pull request."""
        comments: list[dict] = []
        url = f"/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/comments"

        while url:
            resp = await self._client.get(url)
            resp.raise_for_status()
            data = resp.json()
            comments.extend(data.get("values", []))
            url = data.get("next", "")

        return comments

    async def close(self) -> None:
        await self._client.aclose()


def _parse_diff_patches(diff: str) -> dict[str, str]:
    """Parse a unified diff into per-file patches.

    Returns dict of filename → patch content.
    """
    patches: dict[str, str] = {}
    current_file = ""
    current_patch: list[str] = []

    for line in diff.split("\n"):
        if line.startswith("diff --git"):
            # Save previous file
            if current_file and current_patch:
                patches[current_file] = "\n".join(current_patch)

            # Parse new file path from "diff --git a/path b/path"
            parts = line.split(" b/", 1)
            current_file = parts[1] if len(parts) > 1 else ""
            current_patch = []
        elif line.startswith("@@") or (current_file and current_patch):
            current_patch.append(line)

    # Save last file
    if current_file and current_patch:
        patches[current_file] = "\n".join(current_patch)

    return patches
