"""Retry decorator for LLM provider calls.

Implements exponential backoff with jitter for transient failures:
- Rate limit errors (429)
- Server errors (500, 502, 503)
- Connection timeouts
- Overloaded errors (Anthropic)
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Exceptions that should trigger a retry
_RETRYABLE_STRINGS = [
    "rate_limit",
    "rate limit",
    "overloaded",
    "too many requests",
    "capacity",
    "server_error",
    "internal server error",
    "bad gateway",
    "service unavailable",
    "timeout",
    "connection",
    "529",  # Anthropic overloaded
]

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}


def _is_retryable(exc: Exception) -> bool:
    """Check if an exception is transient and should be retried."""
    exc_str = str(exc).lower()

    # Check by string matching
    for pattern in _RETRYABLE_STRINGS:
        if pattern in exc_str:
            return True

    # Check for HTTP status code attributes
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status and int(status) in _RETRYABLE_STATUS_CODES:
        return True

    # Check for httpx/openai/anthropic specific attributes
    response = getattr(exc, "response", None)
    if response is not None:
        resp_status = getattr(response, "status_code", None)
        if resp_status and int(resp_status) in _RETRYABLE_STATUS_CODES:
            return True

    return False


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float = 0.5,
) -> Callable:
    """Decorator that adds exponential backoff retry to async functions.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay between retries
        jitter: Random jitter factor (0-1) to prevent thundering herd
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e

                    if attempt == max_retries or not _is_retryable(e):
                        raise

                    # Calculate delay with exponential backoff + jitter
                    delay = min(base_delay * (2**attempt), max_delay)
                    delay += random.uniform(0, delay * jitter)

                    # Extract retry-after header if available
                    retry_after = _extract_retry_after(e)
                    if retry_after:
                        delay = max(delay, retry_after)

                    logger.warning(
                        "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1,
                        max_retries + 1,
                        delay,
                        str(e)[:200],
                    )

                    await asyncio.sleep(delay)

            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator


def _extract_retry_after(exc: Exception) -> float | None:
    """Try to extract Retry-After value from an exception's response."""
    response = getattr(exc, "response", None)
    if response is None:
        return None

    headers = getattr(response, "headers", {})
    retry_after = headers.get("retry-after") or headers.get("Retry-After")
    if retry_after:
        try:
            return float(retry_after)
        except (ValueError, TypeError):
            pass

    return None
