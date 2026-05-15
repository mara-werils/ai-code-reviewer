"""Tests for diff-aware review cache."""

from src.github.client import PRFile
from src.review.cache import (
    _hash_patch,
    filter_changed_files,
    load_cache,
    save_cache,
    update_cache,
    CacheEntry,
)


def _file(name: str, patch: str = "@@ +1 @@\n+hello") -> PRFile:
    return PRFile(filename=name, status="modified", additions=1, deletions=0, patch=patch)


class TestHashPatch:
    def test_same_input_same_hash(self) -> None:
        assert _hash_patch("hello") == _hash_patch("hello")

    def test_different_input_different_hash(self) -> None:
        assert _hash_patch("hello") != _hash_patch("world")

    def test_none_is_handled(self) -> None:
        h = _hash_patch(None)
        assert isinstance(h, str)
        assert len(h) == 16


class TestFilterChangedFiles:
    def test_no_cache_returns_all(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.review.cache.CACHE_DIR", tmp_path / "cache")
        files = [_file("a.py"), _file("b.py")]
        changed, unchanged = filter_changed_files(files, "org/repo", 1)
        assert len(changed) == 2
        assert len(unchanged) == 0

    def test_cached_files_are_skipped(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.review.cache.CACHE_DIR", tmp_path / "cache")

        files = [_file("a.py", "patch1"), _file("b.py", "patch2")]

        # First run — update cache
        update_cache("org/repo", 1, "sha1", files)

        # Same files — all unchanged
        changed, unchanged = filter_changed_files(files, "org/repo", 1)
        assert len(changed) == 0
        assert len(unchanged) == 2

    def test_modified_file_is_detected(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.review.cache.CACHE_DIR", tmp_path / "cache")

        files = [_file("a.py", "patch1"), _file("b.py", "patch2")]
        update_cache("org/repo", 1, "sha1", files)

        # Modify one file
        files_v2 = [_file("a.py", "patch1-modified"), _file("b.py", "patch2")]
        changed, unchanged = filter_changed_files(files_v2, "org/repo", 1)
        assert len(changed) == 1
        assert changed[0].filename == "a.py"
        assert len(unchanged) == 1


class TestCachePersistence:
    def test_save_and_load(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.review.cache.CACHE_DIR", tmp_path / "cache")

        entry = CacheEntry(
            repo="org/repo",
            pr_number=42,
            commit_sha="abc123",
            file_hashes={"a.py": "hash1"},
            reviewed_at="2026-01-01T00:00:00",
        )
        save_cache(entry)

        loaded = load_cache("org/repo", 42)
        assert loaded is not None
        assert loaded.commit_sha == "abc123"
        assert loaded.file_hashes == {"a.py": "hash1"}

    def test_load_missing_returns_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.review.cache.CACHE_DIR", tmp_path / "cache")
        assert load_cache("org/repo", 999) is None
