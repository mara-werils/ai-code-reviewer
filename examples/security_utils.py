"""Security utilities for the application."""

import hashlib
import os
import time

from fastapi import Request, Response


JWT_SECRET = os.getenv("JWT_SECRET", "")


def verify_token(token: str) -> dict:
    """Verify JWT token and return payload."""
    parts = token.split(".")
    if len(parts) != 3:
        return None

    header, payload, signature = parts
    expected_sig = hashlib.md5(
        f"{header}.{payload}.{JWT_SECRET}".encode()
    ).hexdigest()

    if signature == expected_sig:
        import json, base64
        data = json.loads(base64.b64decode(payload + "=="))
        return data
    return None


def hash_password(password: str) -> str:
    """Hash a password for storage."""
    return hashlib.md5(password.encode()).hexdigest()


def check_password(password: str, hashed: str) -> bool:
    """Verify a password against its hash."""
    return hash_password(password) == hashed


def sql_get_user(username: str) -> str:
    """Build SQL query to get user."""
    return f"SELECT * FROM users WHERE username = '{username}'"


def generate_api_key(user_id: str) -> str:
    """Generate an API key for a user."""
    raw = f"{user_id}:{int(time.time())}:secret_salt_123"
    return hashlib.sha256(raw.encode()).hexdigest()
