"""Tests for auto-labeling."""

from src.github.client import PRFile, PRInfo
from src.review.auto_label import suggest_labels


def _pr(title: str = "test", body: str = "") -> PRInfo:
    return PRInfo(
        number=1, title=title, body=body,
        head_sha="abc", base_sha="def",
        base_ref="main", head_ref="feat/test",
        repo_full_name="owner/repo", author="dev",
    )


def _file(name: str, additions: int = 10, deletions: int = 0) -> PRFile:
    return PRFile(filename=name, status="modified", additions=additions, deletions=deletions, patch="")


class TestAutoLabel:
    def test_size_xs(self):
        labels = suggest_labels(_pr(), [_file("a.py", 5, 3)])
        names = [l.name for l in labels]
        assert "size/XS" in names

    def test_size_xl(self):
        labels = suggest_labels(_pr(), [_file("a.py", 400, 200)])
        names = [l.name for l in labels]
        assert "size/XL" in names

    def test_type_feature(self):
        labels = suggest_labels(_pr("feat: add new dashboard"), [_file("a.py")])
        names = [l.name for l in labels]
        assert "type/feature" in names

    def test_type_bugfix(self):
        labels = suggest_labels(_pr("fix: resolve crash on login"), [_file("a.py")])
        names = [l.name for l in labels]
        assert "type/bugfix" in names

    def test_area_frontend(self):
        labels = suggest_labels(_pr(), [_file("src/components/Button.tsx")])
        names = [l.name for l in labels]
        assert "area/frontend" in names

    def test_area_infra(self):
        labels = suggest_labels(_pr(), [_file("Dockerfile")])
        names = [l.name for l in labels]
        assert "area/infra" in names

    def test_has_migration(self):
        labels = suggest_labels(_pr(), [_file("db/migrations/001.sql")])
        names = [l.name for l in labels]
        assert "has-migration" in names

    def test_breaking_change(self):
        labels = suggest_labels(_pr("BREAKING: remove old API"), [_file("api.py")])
        names = [l.name for l in labels]
        assert "breaking-change" in names
