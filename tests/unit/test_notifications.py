"""Tests for notification webhooks."""

from unittest.mock import AsyncMock, patch

import pytest

from src.notifications import _build_summary, send_notifications
from src.review.engine import ReviewComment, ReviewResult


def _result(risk: str = "high", comments: int = 3) -> ReviewResult:
    return ReviewResult(
        summary="Found potential SQL injection.",
        risk_level=risk,
        category="bugfix",
        comments=[
            ReviewComment(
                path=f"src/file{i}.py",
                line=10,
                side="RIGHT",
                body="issue",
                severity="warning",
            )
            for i in range(comments)
        ],
        labels=[],
        cost_usd=0.005,
        duration_ms=1500,
        model="llama-3.3-70b",
        input_tokens=1000,
        output_tokens=200,
    )


class TestBuildSummary:
    def test_summary_contains_repo(self) -> None:
        summary = _build_summary(_result(), "org/repo", 42, "Fix auth")
        assert "org/repo" in summary
        assert "42" in summary

    def test_summary_contains_risk(self) -> None:
        summary = _build_summary(_result(risk="high"), "org/repo", 1, "test")
        assert "HIGH" in summary

    def test_summary_contains_cost(self) -> None:
        summary = _build_summary(_result(), "org/repo", 1, "test")
        assert "$0.0050" in summary


class TestSendNotifications:
    @pytest.mark.asyncio
    async def test_skips_when_risk_below_threshold(self) -> None:
        config = {"slack_webhook": "https://hooks.slack.com/test", "notify_on": ["high"]}
        with patch("src.notifications.notify_slack", new_callable=AsyncMock) as mock:
            await send_notifications(config, _result(risk="low"), "org/repo", 1, "test")
            mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_when_risk_matches(self) -> None:
        config = {"slack_webhook": "https://hooks.slack.com/test", "notify_on": ["high"]}
        with patch("src.notifications.notify_slack", new_callable=AsyncMock) as mock:
            await send_notifications(config, _result(risk="high"), "org/repo", 1, "test")
            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_config_does_nothing(self) -> None:
        await send_notifications({}, _result(), "org/repo", 1, "test")

    @pytest.mark.asyncio
    async def test_none_config_does_nothing(self) -> None:
        await send_notifications(None, _result(), "org/repo", 1, "test")
