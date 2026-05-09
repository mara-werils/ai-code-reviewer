"""GitHub App authentication — JWT + installation access tokens.

Lightweight module for GitHub App auth without external dependencies
beyond PyJWT (uses cryptography backend for RS256).
"""

from __future__ import annotations

import logging
import time

import httpx
import jwt

logger = logging.getLogger(__name__)

BASE_URL = "https://api.github.com"

# Installation tokens are valid for 1 hour, refresh at 50 min
_TOKEN_TTL = 50 * 60


class GitHubAppAuth:
    """Handles GitHub App authentication.

    Flow:
    1. Generate JWT signed with the App's private key
    2. Exchange JWT for an installation access token
    3. Use the installation token for API calls (valid 1 hour)
    """

    def __init__(self, app_id: str, private_key: str) -> None:
        self.app_id = app_id
        self.private_key = private_key
        self._token_cache: dict[int, tuple[str, float]] = {}

    def _generate_jwt(self) -> str:
        """Generate a JWT for GitHub App authentication.

        JWTs are valid for 10 minutes max.
        """
        now = int(time.time())
        payload = {
            "iat": now - 60,  # issued at (60s leeway for clock drift)
            "exp": now + (9 * 60),  # expires in 9 minutes
            "iss": self.app_id,
        }
        return jwt.encode(payload, self.private_key, algorithm="RS256")

    async def get_installation_token(
        self, installation_id: int, client: httpx.AsyncClient | None = None
    ) -> str:
        """Get an installation access token, using cache when possible.

        Args:
            installation_id: GitHub App installation ID
            client: Optional httpx client to reuse

        Returns:
            Installation access token string
        """
        # Check cache
        cached = self._token_cache.get(installation_id)
        if cached:
            token, expires_at = cached
            if time.time() < expires_at:
                return token

        # Generate new token
        token_jwt = self._generate_jwt()

        should_close = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=30.0)

        try:
            resp = await client.post(
                f"{BASE_URL}/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {token_jwt}",
                    "Accept": "application/vnd.github+json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            token = data["token"]

            # Cache with TTL
            self._token_cache[installation_id] = (token, time.time() + _TOKEN_TTL)
            logger.info(f"Obtained installation token for installation {installation_id}")

            return token
        finally:
            if should_close:
                await client.aclose()

    async def get_app_info(self, client: httpx.AsyncClient | None = None) -> dict:
        """Get the authenticated App's info (for verification)."""
        token_jwt = self._generate_jwt()

        should_close = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=30.0)

        try:
            resp = await client.get(
                f"{BASE_URL}/app",
                headers={
                    "Authorization": f"Bearer {token_jwt}",
                    "Accept": "application/vnd.github+json",
                },
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            if should_close:
                await client.aclose()


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature.

    Args:
        payload: Raw request body bytes
        signature: X-Hub-Signature-256 header value
        secret: Webhook secret configured in the App

    Returns:
        True if signature is valid
    """
    import hashlib
    import hmac as hmac_mod

    if not signature.startswith("sha256="):
        return False

    expected = (
        "sha256="
        + hmac_mod.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
    )

    return hmac_mod.compare_digest(expected, signature)
