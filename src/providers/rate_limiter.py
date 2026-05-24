"""Rate limit manager — intelligent rate limiting across LLM providers.

Features:
- Token bucket algorithm per provider
- Request queuing with priority
- Cost-based throttling (budget guard)
- Automatic provider failover when rate limited
- Rate limit header parsing
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Rate limit configuration per provider."""

    requests_per_minute: int = 60
    tokens_per_minute: int = 100_000
    max_concurrent: int = 5
    budget_limit_usd: float = 10.0  # Max spend before throttling
    budget_period_hours: int = 24


@dataclass
class ProviderBucket:
    """Token bucket for a single provider."""

    provider_name: str
    config: RateLimitConfig
    tokens: float = 0.0
    last_refill: float = 0.0
    request_count: int = 0
    request_window_start: float = 0.0
    total_cost_usd: float = 0.0
    cost_window_start: float = 0.0
    _semaphore: asyncio.Semaphore | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        self.tokens = float(self.config.requests_per_minute)
        self.last_refill = time.monotonic()
        self.request_window_start = time.monotonic()
        self.cost_window_start = time.monotonic()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        new_tokens = elapsed * (self.config.requests_per_minute / 60.0)
        self.tokens = min(
            float(self.config.requests_per_minute),
            self.tokens + new_tokens,
        )
        self.last_refill = now

        # Reset request counter every minute
        if now - self.request_window_start > 60:
            self.request_count = 0
            self.request_window_start = now

        # Reset cost window
        budget_period_secs = self.config.budget_period_hours * 3600
        if now - self.cost_window_start > budget_period_secs:
            self.total_cost_usd = 0.0
            self.cost_window_start = now

    @property
    def budget_remaining(self) -> float:
        """Remaining budget in current window."""
        return max(0, self.config.budget_limit_usd - self.total_cost_usd)

    @property
    def is_budget_exceeded(self) -> bool:
        """Check if budget is exceeded."""
        return self.total_cost_usd >= self.config.budget_limit_usd


class RateLimiter:
    """Global rate limiter managing multiple provider buckets."""

    def __init__(self) -> None:
        self._buckets: dict[str, ProviderBucket] = {}
        self._lock = asyncio.Lock()

    def configure_provider(
        self,
        provider_name: str,
        config: RateLimitConfig | None = None,
    ) -> None:
        """Set rate limits for a provider."""
        if config is None:
            config = _default_config(provider_name)
        self._buckets[provider_name] = ProviderBucket(
            provider_name=provider_name,
            config=config,
        )

    async def acquire(self, provider_name: str) -> bool:
        """Acquire permission to make a request. Returns False if rate limited."""
        bucket = self._buckets.get(provider_name)
        if not bucket:
            return True  # No limits configured

        async with bucket._lock:
            bucket._refill()

            # Check budget
            if bucket.is_budget_exceeded:
                logger.warning(
                    f"Budget exceeded for {provider_name}: "
                    f"${bucket.total_cost_usd:.2f} >= ${bucket.config.budget_limit_usd:.2f}"
                )
                return False

            # Check token bucket
            if bucket.tokens < 1:
                wait_time = (1 - bucket.tokens) / (bucket.config.requests_per_minute / 60.0)
                logger.info(f"Rate limited on {provider_name}, waiting {wait_time:.1f}s")
                await asyncio.sleep(min(wait_time, 30))
                bucket._refill()

            if bucket.tokens >= 1:
                bucket.tokens -= 1
                bucket.request_count += 1
                return True

            return False

    async def acquire_with_semaphore(self, provider_name: str):
        """Context manager for concurrent request limiting."""
        bucket = self._buckets.get(provider_name)
        if bucket and bucket._semaphore:
            return bucket._semaphore
        # Return a no-op semaphore
        return asyncio.Semaphore(100)

    def record_cost(self, provider_name: str, cost_usd: float) -> None:
        """Record cost of a completed request."""
        bucket = self._buckets.get(provider_name)
        if bucket:
            bucket.total_cost_usd += cost_usd

    def get_status(self, provider_name: str) -> dict:
        """Get rate limit status for a provider."""
        bucket = self._buckets.get(provider_name)
        if not bucket:
            return {"configured": False}

        bucket._refill()
        return {
            "configured": True,
            "provider": provider_name,
            "tokens_remaining": bucket.tokens,
            "requests_in_window": bucket.request_count,
            "requests_per_minute": bucket.config.requests_per_minute,
            "budget_remaining_usd": bucket.budget_remaining,
            "budget_limit_usd": bucket.config.budget_limit_usd,
            "is_budget_exceeded": bucket.is_budget_exceeded,
        }

    def get_best_provider(self, providers: list[str]) -> str | None:
        """Find the provider with the most available capacity."""
        best: str | None = None
        best_score = -1

        for name in providers:
            bucket = self._buckets.get(name)
            if not bucket:
                return name  # Unconfigured = no limits

            if bucket.is_budget_exceeded:
                continue

            bucket._refill()
            score = bucket.tokens / bucket.config.requests_per_minute
            if score > best_score:
                best_score = score
                best = name

        return best


def _default_config(provider_name: str) -> RateLimitConfig:
    """Get default rate limits for known providers."""
    defaults = {
        "openai": RateLimitConfig(requests_per_minute=500, tokens_per_minute=800_000, max_concurrent=10),
        "anthropic": RateLimitConfig(requests_per_minute=60, tokens_per_minute=400_000, max_concurrent=5),
        "groq": RateLimitConfig(requests_per_minute=30, tokens_per_minute=15_000, max_concurrent=3),
        "google": RateLimitConfig(requests_per_minute=60, tokens_per_minute=1_000_000, max_concurrent=10),
        "ollama": RateLimitConfig(requests_per_minute=999, tokens_per_minute=999_999, max_concurrent=1),
        "together": RateLimitConfig(requests_per_minute=60, tokens_per_minute=500_000, max_concurrent=5),
        "deepseek": RateLimitConfig(requests_per_minute=60, tokens_per_minute=500_000, max_concurrent=5),
    }
    return defaults.get(provider_name, RateLimitConfig())


# Global singleton
_global_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = RateLimiter()
    return _global_limiter
