"""Tests for review export."""

import json

from src.review.engine import ReviewComment, ReviewResult
from src.review.export import export_csv, export_json, export_markdown, export_sarif


def _make_result() -> ReviewResult:
    return ReviewResult(
        summary="Test review summary",
        risk_level="medium",
        category="feature",
        comments=[
            ReviewComment(
                path="src/app.py",
                line=10,
                side="RIGHT",
                body="Fix this bug",
                severity="warning",
            ),
            ReviewComment(
                path="src/db.py",
                line=20,
                side="RIGHT",
                body="SQL injection risk",
                severity="critical",
            ),
        ],
        labels=["feature"],
        cost_usd=0.005,
        duration_ms=1500,
        model="gpt-4o",
        input_tokens=1000,
        output_tokens=500,
    )


class TestExportJson:
    def test_valid_json(self):
        result = export_json(_make_result())
        data = json.loads(result)
        assert data["summary"] == "Test review summary"
        assert len(data["comments"]) == 2

    def test_includes_stats(self):
        data = json.loads(export_json(_make_result()))
        assert "stats" in data
        assert data["stats"]["total_comments"] == 2


class TestExportSarif:
    def test_valid_sarif(self):
        result = export_sarif(_make_result())
        data = json.loads(result)
        assert data["version"] == "2.1.0"
        assert len(data["runs"]) == 1

    def test_sarif_has_results(self):
        data = json.loads(export_sarif(_make_result()))
        results = data["runs"][0]["results"]
        assert len(results) == 2

    def test_sarif_severity_mapping(self):
        data = json.loads(export_sarif(_make_result()))
        results = data["runs"][0]["results"]
        levels = [r["level"] for r in results]
        assert "error" in levels  # critical maps to error
        assert "warning" in levels


class TestExportCsv:
    def test_has_header(self):
        csv_output = export_csv(_make_result())
        lines = csv_output.strip().split("\n")
        assert lines[0].startswith("path,")
        assert len(lines) == 3  # header + 2 comments


class TestExportMarkdown:
    def test_has_title(self):
        md = export_markdown(_make_result())
        assert "AI Code Review Report" in md

    def test_has_findings(self):
        md = export_markdown(_make_result())
        assert "src/app.py" in md
        assert "src/db.py" in md
