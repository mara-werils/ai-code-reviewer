"""Tests for the fix engine."""

from __future__ import annotations

from src.review.fixer import (
    FixResult,
    FixSummary,
    _detect_language,
    _extract_ai_review_comments,
    _extract_severity,
    format_fix_comment,
)


class TestExtractSeverity:
    def test_critical(self) -> None:
        assert _extract_severity("**[CRITICAL] Bug**: SQL injection") == "critical"

    def test_warning(self) -> None:
        assert _extract_severity("**[WARNING] Performance**: N+1 query") == "warning"

    def test_suggestion(self) -> None:
        assert _extract_severity("**[SUGGESTION] Design**: Consider using...") == "suggestion"

    def test_unknown(self) -> None:
        assert _extract_severity("some other text") == "info"


class TestDetectLanguage:
    def test_python(self) -> None:
        assert _detect_language("src/main.py") == "python"

    def test_typescript(self) -> None:
        assert _detect_language("app/index.ts") == "typescript"

    def test_go(self) -> None:
        assert _detect_language("cmd/server.go") == "go"

    def test_unknown(self) -> None:
        assert _detect_language("Makefile") == ""


class TestExtractAiReviewComments:
    def test_extracts_inline_comments(self) -> None:
        review_comments = [
            {
                "body": "**[CRITICAL] Bug**: SQL injection in query builder",
                "path": "src/db.py",
                "line": 42,
                "original_line": 42,
            },
            {
                "body": "**[WARNING] Performance**: Missing index on user_id",
                "path": "src/models.py",
                "line": 10,
                "original_line": 10,
            },
            {
                "body": "Looks good!",  # Not an AI review comment
                "path": "src/other.py",
                "line": 1,
            },
        ]
        result = _extract_ai_review_comments(review_comments, [])
        assert "src/db.py" in result
        assert "src/models.py" in result
        assert "src/other.py" not in result
        assert len(result["src/db.py"]) == 1
        assert result["src/db.py"][0]["severity"] == "critical"

    def test_extracts_from_summary_comment(self) -> None:
        issue_comments = [
            {
                "body": (
                    "## AI Code Review\n\n"
                    "> Summary\n\n"
                    "<details><summary>General comments</summary>\n\n"
                    "- [WARNING] **src/api.py**: Missing auth check on admin endpoint\n"
                    "</details>"
                ),
            },
        ]
        result = _extract_ai_review_comments([], issue_comments)
        assert "src/api.py" in result
        assert len(result["src/api.py"]) == 1

    def test_empty_comments(self) -> None:
        result = _extract_ai_review_comments([], [])
        assert result == {}


class TestFormatFixComment:
    def test_no_fixes(self) -> None:
        summary = FixSummary(files_fixed=0, total_applied=0, total_skipped=0, fixes=[], cost_usd=0)
        result = format_fix_comment(summary)
        assert "No fixable issues" in result

    def test_with_fixes(self) -> None:
        summary = FixSummary(
            files_fixed=1,
            total_applied=2,
            total_skipped=0,
            fixes=[
                FixResult(
                    path="src/db.py",
                    applied=["Fixed SQL injection", "Added parameterized query"],
                    skipped=[],
                    commit_sha="abc12345",
                ),
            ],
            cost_usd=0.003,
        )
        result = format_fix_comment(summary)
        assert "## AI Code Fix" in result
        assert "2 fixes" in result
        assert "1 files" in result
        assert "src/db.py" in result
        assert "abc12345" in result
        assert "$0.0030" in result

    def test_with_skipped(self) -> None:
        summary = FixSummary(
            files_fixed=1,
            total_applied=1,
            total_skipped=1,
            fixes=[
                FixResult(
                    path="src/api.py",
                    applied=["Added null check"],
                    skipped=["Would break API contract"],
                    commit_sha="def67890",
                ),
            ],
            cost_usd=0.001,
        )
        result = format_fix_comment(summary)
        assert "Skipped" in result
        assert "Would break API contract" in result
