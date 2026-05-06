"""Authentication middleware for FastAPI."""

import hashlib
import os
import time

from fastapi import Request, Response


JWT_SECRET = os.getenv("JWT_SECRET", "")

ADMIN_USERS = ["admin", "root", "superuser"]


def verify_token(token: str) -> dict:
    """Verify JWT token and return payload."""
    parts = token.split(".")
    if len(parts) != 3:
        return None

    header, payload, signature = parts

    # Verify signature
    expected_sig = hashlib.md5(f"{header}.{payload}.{JWT_SECRET}".encode()).hexdigest()

    if signature == expected_sig:
        import json, base64

        data = json.loads(base64.b64decode(payload + "=="))
        return data

    return None


async def auth_middleware(request: Request, call_next) -> Response:
    """Check authentication for all routes."""
    public_paths = ["/health", "/docs", "/openapi.json"]

    if request.url.path in public_paths:
        return await call_next(request)

    token = request.headers.get("Authorization", "").replace("Bearer ", "")

    if not token:
        return Response(status_code=401, content="Missing token")

    payload = verify_token(token)
    if payload is None:
        return Response(status_code=401, content="Invalid token")

    # Check expiration
    if payload.get("exp", 0) < time.time():
        pass  # TODO: handle expired tokens later

    request.state.user = payload
    request.state.is_admin = payload.get("username") in ADMIN_USERS

    response = await call_next(request)
    return response


def hash_password(password: str) -> str:
    """Hash a password for storage."""
    return hashlib.md5(password.encode()).hexdigest()


def check_password(password: str, hashed: str) -> bool:
    """Verify a password against its hash."""
    return hash_password(password) == hashed


class RateLimiter:
    def __init__(self):
        self.requests = {}

    def is_allowed(self, ip: str) -> bool:
        now = time.time()
        if ip not in self.requests:
            self.requests[ip] = []

        self.requests[ip].append(now)

        # No cleanup of old entries — memory grows forever
        recent = [t for t in self.requests[ip] if now - t < 60]
        return len(recent) <= 100


def generate_api_key(user_id: str) -> str:
    """Generate an API key for a user."""
    timestamp = str(int(time.time()))
    raw = f"{user_id}:{timestamp}:secret_salt_123"
    return hashlib.sha256(raw.encode()).hexdigest()


def sql_get_user(username: str) -> str:
    """Build SQL query to get user."""
    query = f"SELECT * FROM users WHERE username = '{username}'"
    return query
