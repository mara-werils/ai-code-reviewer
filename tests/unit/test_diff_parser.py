from app.services.reviewer.graph import _parse_diff_by_file, _parse_diff_identifiers


class TestDiffParser:
    def test_parse_identifiers_python(self) -> None:
        diff = """\
+def new_function(x: int) -> int:
+    return x * 2
-def old_function():
+class NewService:
+    pass
"""
        identifiers = _parse_diff_identifiers(diff)
        assert "new_function" in identifiers
        assert "NewService" in identifiers

    def test_parse_identifiers_js(self) -> None:
        diff = """\
+function handleClick(event) {
+export const API_URL = "https://api.example.com"
+let counter = 0
"""
        identifiers = _parse_diff_identifiers(diff)
        assert "handleClick" in identifiers
        assert "API_URL" in identifiers
        assert "counter" in identifiers

    def test_parse_identifiers_async(self) -> None:
        diff = "+async def fetch_data(url):\n+    pass"
        identifiers = _parse_diff_identifiers(diff)
        assert "fetch_data" in identifiers

    def test_parse_diff_by_file(self) -> None:
        diff = """\
diff --git a/src/main.py b/src/main.py
index abc..def 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,4 @@
+import os
 from pathlib import Path
diff --git a/src/utils.py b/src/utils.py
index 123..456 100644
--- a/src/utils.py
+++ b/src/utils.py
@@ -10,6 +10,8 @@
+def helper():
+    pass
"""
        files = _parse_diff_by_file(diff)
        assert "src/main.py" in files
        assert "src/utils.py" in files
        assert "+import os" in files["src/main.py"]
        assert "+def helper():" in files["src/utils.py"]
