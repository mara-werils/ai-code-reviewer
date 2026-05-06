import hashlib
import hmac

from app.core.exceptions import WebhookValidationError


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> None:
    """Validate GitHub webhook HMAC-SHA256 signature."""
    if not signature.startswith("sha256="):
        raise WebhookValidationError("Invalid signature format")

    expected = (
        "sha256="
        + hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
    )

    if not hmac.compare_digest(expected, signature):
        raise WebhookValidationError("Signature mismatch")
