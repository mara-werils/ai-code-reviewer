"""Tests for review formatter — including suggestion block handling."""

from __future__ import annotations

from src.review.engine import ReviewComment, ReviewResult
from src.review.formatter import (
    build_github_review_comments,
    format_inline_comment,
    format_review_body,
)


class TestFormatInlineComment:
    """Test inline comment formatting."""

    def test_basic_format(self):
        result = format_inline_comment("warning", "This could cause issues")
        assert "**[WARNING] Warning**" in result
        assert "This could cause issues" in result

    def test_suggestion_block_preserved(self):
        """GitHub suggestion blocks should be preserved in the output."""
        body = "Missing null check.\n\n```suggestion\nif x is not None:\n    process(x)\n```"
        result = format_inline_comment("critical", body)
        assert "```suggestion" in result
        assert "if x is not None:" in result

    def test_severity_labels(self):
        for sev in ["critical", "warning", "suggestion", "info"]:
            result = format_inline_comment(sev, "test")
            assert f"[{sev.upper()}]" in result

    def test_unknown_severity(self):
        result = format_inline_comment("unknown", "test")
        assert "[INFO]" in result  # Falls back to INFO


class TestBuildGithubReviewComments:
    """Test building GitHub API-compatible review comments."""

    def test_basic_comments(self):
        result = ReviewResult(
            summary="test",
            risk_level="low",
            category="bugfix",
            comments=[
                ReviewComment(path="a.py", line=10, side="RIGHT", body="fix this", severity="warning"),
            ],
            labels=[],
            cost_usd=0,
            duration_ms=0,
            model="",
            input_tokens=0,
            output_tokens=0,
        )
        comments = build_github_review_comments(result)
        assert len(comments) == 1
        assert comments[0]["path"] == "a.py"

    def test_position_used_when_available(self):
        result = ReviewResult(
            summary="test",
            risk_level="low",
            category="bugfix",
            comments=[
                ReviewComment(path="a.py", line=10, side="RIGHT", body="fix", severity="warning", position=42),
            ],
            labels=[],
            cost_usd=0,
            duration_ms=0,
            model="",
            input_tokens=0,
            output_tokens=0,
        )
        comments = build_github_review_comments(result)
        assert comments[0]["position"] == 42
        assert "line" not in comments[0]

    def test_line_used_without_position(self):
        result = ReviewResult(
            summary="test",
            risk_level="low",
            category="bugfix",
            comments=[
                ReviewComment(path="a.py", line=10, side="RIGHT", body="fix", severity="warning", position=0),
            ],
            labels=[],
            cost_usd=0,
            duration_ms=0,
            model="",
            input_tokens=0,
            output_tokens=0,
        )
        comments = build_github_review_comments(result)
        assert comments[0]["line"] == 10
        assert comments[0]["side"] == "RIGHT"

    def test_body_only_comments_excluded(self):
        """Comments without line numbers should not appear as inline comments."""
        result = ReviewResult(
            summary="test",
            risk_level="low",
            category="bugfix",
            comments=[
                ReviewComment(path="a.py", line=0, side="RIGHT", body="general", severity="info"),
            ],
            labels=[],
            cost_usd=0,
            duration_ms=0,
            model="",
            input_tokens=0,
            output_tokens=0,
        )
        comments = build_github_review_comments(result)
        assert len(comments) == 0


class TestFormatReviewBody:
    """Test review body formatting."""

    def test_no_comments_lgtm(self):
        result = ReviewResult(
            summary="Clean PR",
            risk_level="low",
            category="feature",
            comments=[],
            labels=[],
            cost_usd=0.0012,
            duration_ms=3500,
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=200,
        )
        body = format_review_body(result)
        assert "No issues found" in body
        assert "AI Code Review" in body
        assert "$0.0012" in body

    def test_with_comments_shows_stats(self):
        result = ReviewResult(
            summary="Found issues",
            risk_level="high",
            category="bugfix",
            comments=[
                ReviewComment(path="a.py", line=1, side="RIGHT", body="bug", severity="critical"),
                ReviewComment(path="b.py", line=2, side="RIGHT", body="warn", severity="warning"),
            ],
            labels=[],
            cost_usd=0.05,
            duration_ms=5000,
            model="claude-sonnet-4-20250514",
            input_tokens=5000,
            output_tokens=1000,
        )
        body = format_review_body(result)
        assert "2 comments" in body
        assert "[CRITICAL]" in body
        assert "[WARNING]" in body
