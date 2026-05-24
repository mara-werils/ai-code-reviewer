"""Tests for PR split suggestion."""

from src.github.client import PRFile
from src.review.split_suggestion import suggest_split, format_split_suggestion


def _file(name: str, additions: int = 10, deletions: int = 0) -> PRFile:
    return PRFile(filename=name, status="modified", additions=additions, deletions=deletions, patch="")


class TestSplitSuggestion:
    def test_small_pr_no_split(self):
        files = [_file("a.py", 5)]
        result = suggest_split(files)
        assert not result.should_split

    def test_large_pr_suggests_split(self):
        files = [_file(f"src/file{i}.py", 40) for i in range(20)]
        result = suggest_split(files)
        assert result.should_split
        assert len(result.groups) > 0

    def test_categorizes_tests(self):
        files = [
            _file("src/app.py", 20),
            _file("tests/test_app.py", 20),
        ] * 10
        result = suggest_split(files)
        if result.should_split:
            group_names = [g.name for g in result.groups]
            assert any("Test" in n for n in group_names)

    def test_categorizes_docs(self):
        files = [
            _file("src/app.py", 20),
            _file("docs/guide.md", 20),
        ] * 10
        result = suggest_split(files)
        if result.should_split:
            group_names = [g.name for g in result.groups]
            assert any("Doc" in n for n in group_names)

    def test_format_no_split(self):
        files = [_file("a.py")]
        result = suggest_split(files)
        formatted = format_split_suggestion(result)
        assert "fine" in formatted.lower() or "manageable" in formatted.lower()
