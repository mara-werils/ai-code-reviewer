"""Tests for graph.py helper functions — diff parsing and identifier extraction."""

from __future__ import annotations

from app.services.reviewer.graph import _parse_diff_by_file, _parse_diff_identifiers


class TestParseDiffIdentifiers:
    """Test extraction of added/modified identifiers from diffs."""

    def test_python_function(self):
        diff = "+def process_data(x):\n+    return x * 2"
        ids = _parse_diff_identifiers(diff)
        assert "process_data" in ids

    def test_python_async_function(self):
        diff = "+async def fetch_data():\n+    pass"
        ids = _parse_diff_identifiers(diff)
        assert "fetch_data" in ids

    def test_python_class(self):
        diff = "+class UserService:\n+    pass"
        ids = _parse_diff_identifiers(diff)
        assert "UserService" in ids

    def test_js_function(self):
        diff = "+function handleClick() {"
        ids = _parse_diff_identifiers(diff)
        assert "handleClick" in ids

    def test_js_const(self):
        diff = "+const API_URL = 'http://example.com'"
        ids = _parse_diff_identifiers(diff)
        assert "API_URL" in ids

    def test_js_export_function(self):
        diff = "+export function processOrder(order) {"
        ids = _parse_diff_identifiers(diff)
        assert "processOrder" in ids

    def test_removed_lines_ignored(self):
        diff = "-def old_function():\n-    pass"
        ids = _parse_diff_identifiers(diff)
        assert len(ids) == 0

    def test_context_lines_ignored(self):
        diff = " def existing_function():\n     pass"
        ids = _parse_diff_identifiers(diff)
        assert len(ids) == 0

    def test_multiple_identifiers(self):
        diff = "+def foo():\n+    pass\n+class Bar:\n+    pass\n+const baz = 1"
        ids = _parse_diff_identifiers(diff)
        assert "foo" in ids
        assert "Bar" in ids
        assert "baz" in ids

    def test_deduplication(self):
        diff = "+def foo():\n+def foo():"
        ids = _parse_diff_identifiers(diff)
        assert ids.count("foo") == 1


class TestParseDiffByFile:
    """Test splitting unified diff into per-file diffs."""

    def test_single_file(self):
        diff = "diff --git a/src/main.py b/src/main.py\n+added line"
        result = _parse_diff_by_file(diff)
        assert "src/main.py" in result
        assert "+added line" in result["src/main.py"]

    def test_multiple_files(self):
        diff = "diff --git a/a.py b/a.py\n+line a\ndiff --git a/b.py b/b.py\n+line b"
        result = _parse_diff_by_file(diff)
        assert "a.py" in result
        assert "b.py" in result

    def test_empty_diff(self):
        result = _parse_diff_by_file("")
        assert len(result) == 0

    def test_preserves_full_diff_content(self):
        diff = (
            "diff --git a/src/app.py b/src/app.py\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1,3 +1,4 @@\n"
            " existing\n"
            "+new line\n"
            " more existing"
        )
        result = _parse_diff_by_file(diff)
        assert "src/app.py" in result
        assert "+new line" in result["src/app.py"]
        assert "@@ -1,3 +1,4 @@" in result["src/app.py"]
