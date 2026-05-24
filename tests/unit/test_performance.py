"""Tests for performance anti-pattern detector."""

from src.github.client import PRFile
from src.review.performance import (
    PerformanceFinding,
    format_performance_summary,
    scan_performance,
)


def _make_file(filename: str, patch: str) -> PRFile:
    return PRFile(
        filename=filename,
        status="modified",
        additions=5,
        deletions=0,
        patch=patch,
    )


class TestPerformanceScan:
    def test_detects_select_star(self):
        patch = """@@ -1,3 +1,5 @@
+query = "SELECT * FROM users"
"""
        files = [_make_file("app/db.py", patch)]
        findings = scan_performance(files)
        assert any(f.rule_id == "PERF004" for f in findings)

    def test_detects_setinterval(self):
        patch = """@@ -1,3 +1,5 @@
+setInterval(() => {
+  fetchData();
+}, 1000);
"""
        files = [_make_file("src/timer.js", patch)]
        findings = scan_performance(files)
        assert any(f.rule_id == "PERF008" for f in findings)

    def test_skips_test_files(self):
        patch = """@@ -1,3 +1,5 @@
+setInterval(() => {}, 1000);
"""
        files = [_make_file("tests/test_timer.js", patch)]
        findings = scan_performance(files)
        assert len(findings) == 0

    def test_language_filtering(self):
        # Go-specific rule should not match Python files
        patch = """@@ -1,3 +1,5 @@
+go func() {
+  doWork()
+}()
"""
        files = [_make_file("main.py", patch)]
        findings = scan_performance(files)
        goroutine_findings = [f for f in findings if f.rule_id == "PERF012"]
        assert len(goroutine_findings) == 0

    def test_format_summary_empty(self):
        assert format_performance_summary([]) == ""

    def test_format_summary_with_findings(self):
        findings = [
            PerformanceFinding(
                rule_id="PERF001",
                rule_name="N+1 Query",
                severity="high",
                category="query",
                description="N+1 query detected",
                fix_hint="Use bulk query",
                path="app.py",
                line=10,
                matched_text="for x in items: db.query()",
            )
        ]
        summary = format_performance_summary(findings)
        assert "Performance Analysis" in summary
        assert "N+1 Query" in summary


class TestPerformanceRuleCount:
    def test_has_enough_rules(self):
        from src.review.performance import PERFORMANCE_RULES

        assert len(PERFORMANCE_RULES) >= 15
