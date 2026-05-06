import pytest

from app.core.exceptions import WebhookValidationError
from app.core.security import verify_webhook_signature
from tests.conftest import make_signature


class TestWebhookSignatureValidation:
    def test_valid_signature(self) -> None:
        secret = "test-secret"
        payload = b'{"action": "opened"}'
        signature = make_signature(payload, secret)

        # Should not raise
        verify_webhook_signature(payload, signature, secret)

    def test_invalid_signature(self) -> None:
        secret = "test-secret"
        payload = b'{"action": "opened"}'
        signature = make_signature(payload, "wrong-secret")

        with pytest.raises(WebhookValidationError, match="Signature mismatch"):
            verify_webhook_signature(payload, signature, secret)

    def test_invalid_format(self) -> None:
        with pytest.raises(WebhookValidationError, match="Invalid signature format"):
            verify_webhook_signature(b"payload", "invalid-format", "secret")

    def test_empty_payload(self) -> None:
        secret = "test-secret"
        payload = b""
        signature = make_signature(payload, secret)
        verify_webhook_signature(payload, signature, secret)
