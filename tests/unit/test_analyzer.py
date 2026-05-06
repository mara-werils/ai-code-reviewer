from src.github.client import PRFile
from src.review.analyzer import (
    build_diff_text,
    build_files_summary,
    compute_stats,
    extract_diff_line_map,
    filter_files,
)


class TestFilterFiles:
    def test_filters_lock_files(self) -> None:
        files = [
            PRFile("src/main.py", "modified", 10, 2, "patch"),
            PRFile("package-lock.json", "modified", 500, 500, "patch"),
            PRFile("yarn.lock", "modified", 100, 100, "patch"),
        ]
        filtered = filter_files(files, ["*.lock", "package-lock.json", "yarn.lock"])
        assert len(filtered) == 1
        assert filtered[0].filename == "src/main.py"

    def test_filters_vendor(self) -> None:
        files = [
            PRFile("src/app.ts", "modified", 5, 3, "patch"),
            PRFile("vendor/lib/dep.go", "modified", 100, 0, "patch"),
        ]
        filtered = filter_files(files, ["vendor/**"])
        assert len(filtered) == 1

    def test_skips_empty_patch(self) -> None:
        files = [
            PRFile("src/app.ts", "modified", 5, 3, "patch"),
            PRFile("image.png", "added", 0, 0, ""),
        ]
        filtered = filter_files(files, [])
        assert len(filtered) == 1


class TestBuildDiffText:
    def test_combines_files(self) -> None:
        files = [
            PRFile("a.py", "modified", 5, 2, "+new line\n-old line"),
            PRFile("b.py", "added", 3, 0, "+line1\n+line2"),
        ]
        text = build_diff_text(files)
        assert "a.py" in text
        assert "b.py" in text

    def test_truncates_large_diff(self) -> None:
        files = [
            PRFile("big.py", "modified", 1000, 0, "x" * 50000),
        ]
        text = build_diff_text(files, max_size=1000)
        assert len(text) <= 1200  # Some overhead for headers


class TestExtractDiffLineMap:
    def test_simple_addition(self) -> None:
        patch = """@@ -1,3 +1,5 @@
 existing line
+new line 1
+new line 2
 another existing
"""
        line_map = extract_diff_line_map(patch)
        assert 2 in line_map
        assert 3 in line_map
        assert line_map[2] == "new line 1"

    def test_multiple_hunks(self) -> None:
        patch = """@@ -1,3 +1,4 @@
 line1
+added at 2
 line3
@@ -10,3 +11,4 @@
 line10
+added at 12
 line12
"""
        line_map = extract_diff_line_map(patch)
        assert 2 in line_map
        assert 12 in line_map


class TestComputeStats:
    def test_stats(self) -> None:
        files = [PRFile("a.py", "modified", 10, 5, "p"), PRFile("b.ts", "added", 20, 0, "p")]
        stats = compute_stats(files, files)
        assert stats.total_additions == 30
        assert stats.total_deletions == 5
        assert stats.total_files == 2
        assert "Python" in stats.languages
        assert "TypeScript" in stats.languages
        assert not stats.is_large_pr


class TestBuildFilesSummary:
    def test_format(self) -> None:
        files = [PRFile("src/main.py", "modified", 10, 5, "p")]
        summary = build_files_summary(files)
        assert "src/main.py" in summary
        assert "+10/-5" in summary
