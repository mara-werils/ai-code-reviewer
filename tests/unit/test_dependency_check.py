"""Tests for dependency vulnerability checker."""

from src.github.client import PRFile
from src.review.dependency_check import scan_dependencies, format_dependency_summary


def _make_file(filename: str, patch: str) -> PRFile:
    return PRFile(filename=filename, status="modified", additions=3, deletions=0, patch=patch)


class TestDependencyCheck:
    def test_detects_compromised_package(self):
        patch = """@@ -1,3 +1,5 @@
+    "event-stream": "^3.3.4"
"""
        files = [_make_file("package.json", patch)]
        findings = scan_dependencies(files)
        assert any(f.package == "event-stream" for f in findings)
        assert any(f.severity == "critical" for f in findings)

    def test_detects_deprecated_package(self):
        patch = """@@ -1,3 +1,5 @@
+    "moment": "^2.29.0"
"""
        files = [_make_file("package.json", patch)]
        findings = scan_dependencies(files)
        assert any(f.package == "moment" for f in findings)

    def test_detects_unpinned_version(self):
        patch = """@@ -1,3 +1,5 @@
+    "some-lib": "*"
"""
        files = [_make_file("package.json", patch)]
        findings = scan_dependencies(files)
        assert any(f.kind == "unpinned" for f in findings)

    def test_skips_non_manifest_files(self):
        patch = """@@ -1,3 +1,5 @@
+    "event-stream": "^3.3.4"
"""
        files = [_make_file("src/app.py", patch)]
        findings = scan_dependencies(files)
        assert len(findings) == 0

    def test_format_empty(self):
        assert format_dependency_summary([]) == ""


class TestPipDependencies:
    def test_detects_pycrypto(self):
        patch = """@@ -1,3 +1,5 @@
+pycrypto==2.6.1
"""
        files = [_make_file("requirements.txt", patch)]
        findings = scan_dependencies(files)
        assert any(f.package == "pycrypto" for f in findings)
