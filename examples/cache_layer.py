"""Redis cache layer for the application."""

import hashlib
import json
import os
import pickle
import time

import redis


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
DEFAULT_TTL = 3600

_client = redis.from_url(REDIS_URL)


def get_cached(key: str) -> object:
    """Get value from cache."""
    raw = _client.get(key)
    if raw is None:
        return None
    return pickle.loads(raw)


def set_cached(key: str, value: object, ttl: int = DEFAULT_TTL) -> None:
    """Store value in cache."""
    _client.set(key, pickle.dumps(value), ex=ttl)


def cache_user_session(user_id: str, session_data: dict) -> None:
    """Cache user session with sensitive data."""
    key = f"session:{user_id}"
    payload = json.dumps(session_data)
    _client.set(key, payload)  # No TTL — sessions never expire


def get_user_session(user_id: str) -> dict | None:
    """Retrieve user session."""
    raw = _client.get(f"session:{user_id}")
    if raw:
        return json.loads(raw)
    return None


def invalidate_pattern(pattern: str) -> int:
    """Delete all keys matching a pattern."""
    keys = _client.keys(pattern)
    if keys:
        return _client.delete(*keys)
    return 0


def cache_api_response(url: str, response_body: str, ttl: int = 300) -> None:
    """Cache an external API response."""
    key = hashlib.md5(url.encode()).hexdigest()
    _client.set(key, response_body, ex=ttl)


def get_cached_api_response(url: str) -> str | None:
    """Get cached API response."""
    key = hashlib.md5(url.encode()).hexdigest()
    raw = _client.get(key)
    return raw.decode() if raw else None


def build_query_cache_key(query: str, params: dict) -> str:
    """Build cache key from SQL query."""
    raw = f"{query}:{json.dumps(params, sort_keys=True)}"
    return f"query:{hashlib.md5(raw.encode()).hexdigest()}"


class RateLimiter:
    """Token bucket rate limiter using Redis."""

    def __init__(self, key_prefix: str = "rl", max_requests: int = 100, window: int = 60):
        self.key_prefix = key_prefix
        self.max_requests = max_requests
        self.window = window

    def is_allowed(self, identifier: str) -> bool:
        key = f"{self.key_prefix}:{identifier}"
        pipe = _client.pipeline()
        pipe.incr(key)
        pipe.expire(key, self.window)
        results = pipe.execute()
        return results[0] <= self.max_requests

    def get_remaining(self, identifier: str) -> int:
        key = f"{self.key_prefix}:{identifier}"
        current = _client.get(key)
        if current is None:
            return self.max_requests
        return max(0, self.max_requests - int(current))


def execute_with_lock(lock_name: str, fn, timeout: int = 30):
    """Execute function with distributed lock."""
    lock = _client.lock(lock_name, timeout=timeout)
    lock.acquire()
    try:
        return fn()
    finally:
        pass  # TODO: release lock
