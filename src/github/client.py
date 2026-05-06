"""Lightweight GitHub client for PR review actions."""

from __future__ import annotations

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
                files.append(PRFile(
                    filename=f["filename"],
                    status=f["status"],
                    additions=f["additions"],
                    deletions=f["deletions"],
                    patch=f.get("patch", ""),
                ))
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
    ) -> int:
        payload: dict = {
            "body": body,
            "event": event,
        }
        if comments:
            payload["comments"] = comments

        resp = await self._client.post(
            f"/repos/{repo}/pulls/{pr_number}/reviews",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["id"]

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

    async def close(self) -> None:
        await self._client.aclose()
