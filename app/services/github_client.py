import time
from typing import Any

import httpx
import jwt
import structlog
from pydantic import BaseModel
from redis.asyncio import Redis

from app.config import get_settings

logger = structlog.get_logger()


class FileChange(BaseModel):
    filename: str
    status: str  # added, removed, modified, renamed
    additions: int
    deletions: int
    patch: str | None = None


class TreeEntry(BaseModel):
    path: str
    mode: str
    type: str  # blob, tree
    sha: str
    size: int | None = None


class GitHubClient:
    BASE_URL = "https://api.github.com"

    def __init__(self, redis: Redis | None = None) -> None:  # type: ignore[type-arg]
        self._settings = get_settings()
        self._redis = redis
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    async def _get_app_jwt(self) -> str:
        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + (10 * 60),
            "iss": self._settings.github_app_id,
        }
        private_key = self._settings.github_private_key_path.read_text()
        return jwt.encode(payload, private_key, algorithm="RS256")

    async def authenticate_as_installation(self, installation_id: int) -> str:
        cache_key = f"github:token:{installation_id}"

        if self._redis:
            cached = await self._redis.get(cache_key)
            if cached:
                return str(cached)

        app_jwt = await self._get_app_jwt()
        resp = await self._client.post(
            f"/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {app_jwt}"},
        )
        resp.raise_for_status()
        token = resp.json()["token"]

        if self._redis:
            await self._redis.setex(cache_key, 3000, token)  # 50 min TTL

        return str(token)

    async def _authed_headers(self, installation_id: int) -> dict[str, str]:
        token = await self.authenticate_as_installation(installation_id)
        return {"Authorization": f"token {token}"}

    async def get_pull_request_diff(self, repo: str, pr_number: int, installation_id: int) -> str:
        headers = await self._authed_headers(installation_id)
        headers["Accept"] = "application/vnd.github.v3.diff"
        resp = await self._client.get(
            f"/repos/{repo}/pulls/{pr_number}",
            headers=headers,
        )
        resp.raise_for_status()
        return resp.text

    async def get_pull_request_files(
        self, repo: str, pr_number: int, installation_id: int
    ) -> list[FileChange]:
        headers = await self._authed_headers(installation_id)
        resp = await self._client.get(
            f"/repos/{repo}/pulls/{pr_number}/files",
            headers=headers,
            params={"per_page": 100},
        )
        resp.raise_for_status()
        return [FileChange(**f) for f in resp.json()]

    async def get_repo_tree(self, repo: str, sha: str, installation_id: int) -> list[TreeEntry]:
        headers = await self._authed_headers(installation_id)
        resp = await self._client.get(
            f"/repos/{repo}/git/trees/{sha}",
            headers=headers,
            params={"recursive": "true"},
        )
        resp.raise_for_status()
        return [TreeEntry(**t) for t in resp.json().get("tree", [])]

    async def get_file_content(self, repo: str, path: str, sha: str, installation_id: int) -> str:
        headers = await self._authed_headers(installation_id)
        headers["Accept"] = "application/vnd.github.v3.raw"
        resp = await self._client.get(
            f"/repos/{repo}/contents/{path}",
            headers=headers,
            params={"ref": sha},
        )
        resp.raise_for_status()
        return resp.text

    async def post_review(
        self,
        repo: str,
        pr_number: int,
        body: str,
        comments: list[dict[str, Any]],
        installation_id: int,
    ) -> int:
        headers = await self._authed_headers(installation_id)
        payload: dict[str, Any] = {
            "body": body,
            "event": "COMMENT",
        }
        if comments:
            payload["comments"] = comments

        resp = await self._client.post(
            f"/repos/{repo}/pulls/{pr_number}/reviews",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        return int(resp.json()["id"])

    async def close(self) -> None:
        await self._client.aclose()
