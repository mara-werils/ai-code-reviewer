from src.review.engine import ReviewComment, ReviewResult
from src.review.formatter import (
    build_github_review_comments,
    format_inline_comment,
    format_review_body,
)


def _make_result(**kwargs) -> ReviewResult:  # type: ignore[no-untyped-def]
    defaults = {
        "summary": "Good PR overall.",
        "risk_level": "low",
        "category": "feature",
        "comments": [],
        "labels": [],
        "cost_usd": 0.05,
        "duration_ms": 3000,
        "model": "gpt-4o",
        "input_tokens": 1000,
        "output_tokens": 500,
    }
    defaults.update(kwargs)
    return ReviewResult(**defaults)


class TestFormatReviewBody:
    def test_no_comments(self) -> None:
        result = _make_result()
        body = format_review_body(result)
        assert "AI Code Review" in body
        assert "No issues found" in body
        assert "$0.0500" in body

    def test_with_comments(self) -> None:
        comments = [
            ReviewComment("src/main.py", 10, "RIGHT", "Bug here", "critical"),
            ReviewComment("src/utils.py", 20, "RIGHT", "Consider caching", "suggestion"),
        ]
        result = _make_result(comments=comments)
        body = format_review_body(result)
        assert "2 comments" in body
        assert "critical" in body

    def test_risk_levels(self) -> None:
        for level in ["low", "medium", "high"]:
            result = _make_result(risk_level=level)
            body = format_review_body(result)
            assert level.capitalize() in body


class TestFormatInlineComment:
    def test_critical(self) -> None:
        comment = format_inline_comment("critical", "This will crash in production")
        assert "[CRITICAL]" in comment
        assert "Critical" in comment

    def test_suggestion(self) -> None:
        comment = format_inline_comment("suggestion", "Consider using a list comprehension")
        assert "[SUGGESTION]" in comment


class TestBuildGithubComments:
    def test_filters_no_line(self) -> None:
        comments = [
            ReviewComment("a.py", 10, "RIGHT", "Inline", "warning"),
            ReviewComment("b.py", 0, "RIGHT", "General", "info"),
        ]
        result = _make_result(comments=comments)
        gh_comments = build_github_review_comments(result)
        assert len(gh_comments) == 1
        assert gh_comments[0]["path"] == "a.py"
