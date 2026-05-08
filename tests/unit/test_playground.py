"""Tests for the playground web app."""

from __future__ import annotations

from playground.app import _parse_pr_url, _rate_limit_check, _recent_requests


class TestParsePrUrl:
    def test_full_github_url(self) -> None:
        result = _parse_pr_url("https://github.com/owner/repo/pull/123")
        assert result == ("owner/repo", 123)

    def test_full_url_with_trailing_slash(self) -> None:
        result = _parse_pr_url("https://github.com/owner/repo/pull/42/")
        assert result == ("owner/repo", 42)  # tolerant parsing

    def test_http_url(self) -> None:
        result = _parse_pr_url("http://github.com/org/project/pull/7")
        assert result == ("org/project", 7)

    def test_shorthand(self) -> None:
        result = _parse_pr_url("owner/repo#99")
        assert result == ("owner/repo", 99)

    def test_invalid_url(self) -> None:
        assert _parse_pr_url("not a url") is None
        assert _parse_pr_url("https://gitlab.com/owner/repo/pull/1") is None
        assert _parse_pr_url("") is None

    def test_url_with_spaces(self) -> None:
        result = _parse_pr_url("  https://github.com/a/b/pull/1  ")
        assert result == ("a/b", 1)


class TestRateLimit:
    def setup_method(self) -> None:
        _recent_requests.clear()

    def test_first_request_passes(self) -> None:
        assert _rate_limit_check("1.2.3.4") is None

    def test_second_request_blocked(self) -> None:
        _rate_limit_check("1.2.3.4")
        result = _rate_limit_check("1.2.3.4")
        assert result is not None
        assert "Rate limited" in result

    def test_different_ips_independent(self) -> None:
        assert _rate_limit_check("1.1.1.1") is None
        assert _rate_limit_check("2.2.2.2") is None
