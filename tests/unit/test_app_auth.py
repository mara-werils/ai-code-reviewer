"""Tests for GitHub App authentication."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.github.app_auth import GitHubAppAuth, verify_webhook_signature


# Generate a real test RSA key at import time
def _make_test_key() -> str:
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


_TEST_PRIVATE_KEY = _make_test_key()


class TestVerifyWebhookSignature:
    def test_valid_signature(self) -> None:
        payload = b'{"action": "opened"}'
        secret = "test-secret"
        import hashlib
        import hmac

        sig = "sha256=" + hmac.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()

        assert verify_webhook_signature(payload, sig, secret) is True

    def test_invalid_signature(self) -> None:
        assert verify_webhook_signature(b"payload", "sha256=bad", "secret") is False

    def test_wrong_format(self) -> None:
        assert verify_webhook_signature(b"payload", "md5=abc", "secret") is False

    def test_empty_payload(self) -> None:
        import hashlib
        import hmac

        payload = b""
        secret = "test"
        sig = "sha256=" + hmac.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        assert verify_webhook_signature(payload, sig, secret) is True


class TestGitHubAppAuth:
    def test_generate_jwt(self) -> None:
        auth = GitHubAppAuth(app_id="12345", private_key=_TEST_PRIVATE_KEY)
        token = auth._generate_jwt()

        import jwt

        decoded = jwt.decode(token, options={"verify_signature": False})
        assert decoded["iss"] == "12345"
        assert "exp" in decoded
        assert "iat" in decoded

    @pytest.mark.asyncio
    async def test_get_installation_token_caches(self) -> None:
        auth = GitHubAppAuth(app_id="12345", private_key=_TEST_PRIVATE_KEY)

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"token": "ghs_test_token_123"}
        mock_response.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_response

        # First call — hits the API
        token1 = await auth.get_installation_token(1001, client=mock_client)
        assert token1 == "ghs_test_token_123"
        assert mock_client.post.call_count == 1

        # Second call — uses cache
        token2 = await auth.get_installation_token(1001, client=mock_client)
        assert token2 == "ghs_test_token_123"
        assert mock_client.post.call_count == 1  # No additional API call

    @pytest.mark.asyncio
    async def test_different_installations_separate_tokens(self) -> None:
        auth = GitHubAppAuth(app_id="12345", private_key=_TEST_PRIVATE_KEY)

        mock_client = AsyncMock()
        call_count = 0

        async def mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.json.return_value = {"token": f"ghs_token_{call_count}"}
            resp.raise_for_status = MagicMock()
            return resp

        mock_client.post = mock_post

        token1 = await auth.get_installation_token(1001, client=mock_client)
        token2 = await auth.get_installation_token(1002, client=mock_client)

        assert token1 != token2
        assert call_count == 2
