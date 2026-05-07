"""Tests for retry decorator with exponential backoff."""

from __future__ import annotations

import pytest

from src.providers.retry import _is_retryable, with_retry


class FakeRateLimitError(Exception):
    status_code = 429


class FakeServerError(Exception):
    status_code = 500


class FakeAuthError(Exception):
    status_code = 401


class FakeOverloadedError(Exception):
    def __str__(self):
        return "Error: overloaded_error"


class FakeTimeoutError(Exception):
    def __str__(self):
        return "Connection timeout"


class TestIsRetryable:
    """Test which exceptions are considered retryable."""

    def test_rate_limit_by_status(self):
        assert _is_retryable(FakeRateLimitError()) is True

    def test_server_error_by_status(self):
        assert _is_retryable(FakeServerError()) is True

    def test_auth_error_not_retryable(self):
        assert _is_retryable(FakeAuthError()) is False

    def test_overloaded_by_string(self):
        assert _is_retryable(FakeOverloadedError()) is True

    def test_timeout_by_string(self):
        assert _is_retryable(FakeTimeoutError()) is True

    def test_generic_error_not_retryable(self):
        assert _is_retryable(ValueError("bad input")) is False

    def test_rate_limit_by_string(self):
        assert _is_retryable(Exception("rate limit exceeded")) is True

    def test_service_unavailable_by_string(self):
        assert _is_retryable(Exception("service unavailable")) is True


class TestWithRetry:
    """Test the retry decorator."""

    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_retryable_error(self):
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise FakeRateLimitError("rate limited")
            return "ok"

        result = await fail_then_succeed()
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable(self):
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("bad input")

        with pytest.raises(ValueError):
            await always_fail()
        assert call_count == 1  # No retry

    @pytest.mark.asyncio
    async def test_exhausts_retries(self):
        call_count = 0

        @with_retry(max_retries=2, base_delay=0.01)
        async def always_rate_limit():
            nonlocal call_count
            call_count += 1
            raise FakeRateLimitError("rate limited")

        with pytest.raises(FakeRateLimitError):
            await always_rate_limit()
        assert call_count == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_retries_on_timeout_string(self):
        call_count = 0

        @with_retry(max_retries=1, base_delay=0.01)
        async def timeout_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Connection timeout after 30s")
            return "ok"

        result = await timeout_once()
        assert result == "ok"
        assert call_count == 2
