"""Diff-aware review cache — skip re-reviewing unchanged files.

When a PR is updated (new commits pushed), the reviewer often re-reviews
the entire diff. This module identifies which files actually changed between
the last review and the current push, so only new/modified files go to LLM.

This can reduce LLM costs by 30-70% on iterative PRs.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from src.github.client import PRFile

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".pr-reviewer" / "cache"


@dataclass
class CacheEntry:
    """Cached review state for a PR."""

    repo: str
    pr_number: int
    commit_sha: str
    file_hashes: dict[str, str]  # filename → patch hash
    reviewed_at: str


def _hash_patch(patch: str | None) -> str:
    """Hash file patch content."""
    content = (patch or "").encode()
    return hashlib.sha256(content).hexdigest()[:16]


def _cache_path(repo: str, pr_number: int) -> Path:
    """Get cache file path for a PR."""
    safe_repo = repo.replace("/", "_")
    return CACHE_DIR / f"{safe_repo}_{pr_number}.json"


def load_cache(repo: str, pr_number: int) -> CacheEntry | None:
    """Load cached review state."""
    path = _cache_path(repo, pr_number)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return CacheEntry(**data)
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


def save_cache(entry: CacheEntry) -> None:
    """Save review state to cache."""
    path = _cache_path(entry.repo, entry.pr_number)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "repo": entry.repo,
        "pr_number": entry.pr_number,
        "commit_sha": entry.commit_sha,
        "file_hashes": entry.file_hashes,
        "reviewed_at": entry.reviewed_at,
    }
    path.write_text(json.dumps(data, indent=2))


def filter_changed_files(
    files: list[PRFile],
    repo: str,
    pr_number: int,
) -> tuple[list[PRFile], list[PRFile]]:
    """Split files into changed (need review) and unchanged (skip).

    Returns:
        (changed_files, unchanged_files)
    """
    cached = load_cache(repo, pr_number)
    if not cached:
        return files, []

    changed: list[PRFile] = []
    unchanged: list[PRFile] = []

    for f in files:
        current_hash = _hash_patch(f.patch)
        cached_hash = cached.file_hashes.get(f.filename, "")

        if current_hash == cached_hash:
            unchanged.append(f)
        else:
            changed.append(f)

    if unchanged:
        logger.info(
            f"Cache hit: {len(unchanged)} unchanged files skipped, {len(changed)} files need review"
        )

    return changed, unchanged


def update_cache(
    repo: str,
    pr_number: int,
    commit_sha: str,
    files: list[PRFile],
) -> None:
    """Update cache after a review."""
    import datetime

    file_hashes = {f.filename: _hash_patch(f.patch) for f in files}

    entry = CacheEntry(
        repo=repo,
        pr_number=pr_number,
        commit_sha=commit_sha,
        file_hashes=file_hashes,
        reviewed_at=datetime.datetime.now(datetime.UTC).isoformat(),
    )
    save_cache(entry)
