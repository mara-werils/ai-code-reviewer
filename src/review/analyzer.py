"""Diff analysis and filtering."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass

from src.github.client import PRFile


@dataclass
class DiffStats:
    total_additions: int
    total_deletions: int
    total_files: int
    filtered_files: int
    languages: set[str]
    is_large_pr: bool


EXTENSION_LANGUAGE = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".h": "C/C++",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".md": "Markdown",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bash": "Shell",
    ".dockerfile": "Docker",
    ".tf": "Terraform",
    ".hcl": "HCL",
}


def filter_files(files: list[PRFile], ignore_patterns: list[str]) -> list[PRFile]:
    """Filter out files matching ignore patterns."""
    filtered = []
    for f in files:
        if any(fnmatch.fnmatch(f.filename, pat) for pat in ignore_patterns):
            continue
        if not f.patch:  # Binary or empty
            continue
        filtered.append(f)
    return filtered


def build_diff_text(files: list[PRFile], max_size: int = 30000) -> str:
    """Build a combined diff from PR files, respecting size limits."""
    parts = []
    total_size = 0

    # Sort by importance: modified > added > renamed > removed
    priority = {"modified": 0, "added": 1, "renamed": 2, "removed": 3}
    sorted_files = sorted(files, key=lambda f: priority.get(f.status, 4))

    for f in sorted_files:
        header = f"--- a/{f.filename}\n+++ b/{f.filename}\n"
        patch = f.patch or ""
        chunk = header + patch

        if total_size + len(chunk) > max_size:
            remaining = max_size - total_size
            if remaining > 200:
                parts.append(chunk[:remaining] + "\n... (truncated)")
            parts.append(
                f"\n... and {len(sorted_files) - len(parts)} more files (truncated due to size)"
            )
            break

        parts.append(chunk)
        total_size += len(chunk)

    return "\n\n".join(parts)


def build_files_summary(files: list[PRFile]) -> str:
    """Build a summary of changed files."""
    lines = []
    for f in files:
        status_icon = {
            "added": "[NEW]",
            "modified": "[MOD]",
            "removed": "[DEL]",
            "renamed": "[REN]",
        }.get(f.status, "[FILE]")
        lines.append(f"- {status_icon} `{f.filename}` (+{f.additions}/-{f.deletions})")
    return "\n".join(lines)


def compute_stats(files: list[PRFile], filtered: list[PRFile]) -> DiffStats:
    """Compute diff statistics."""
    languages = set()
    for f in filtered:
        ext = "." + f.filename.rsplit(".", 1)[-1] if "." in f.filename else ""
        lang = EXTENSION_LANGUAGE.get(ext.lower(), "")
        if lang:
            languages.add(lang)

    total_adds = sum(f.additions for f in filtered)
    total_dels = sum(f.deletions for f in filtered)

    return DiffStats(
        total_additions=total_adds,
        total_deletions=total_dels,
        total_files=len(files),
        filtered_files=len(filtered),
        languages=languages,
        is_large_pr=(total_adds + total_dels) > 500,
    )


def extract_diff_line_map(patch: str) -> dict[int, str]:
    """Extract a mapping of new-file line numbers to diff content."""
    line_map: dict[int, str] = {}
    current_line = 0

    for line in patch.split("\n"):
        hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", line)
        if hunk_match:
            current_line = int(hunk_match.group(1))
            continue

        if line.startswith("+") and not line.startswith("+++"):
            line_map[current_line] = line[1:]
            current_line += 1
        elif line.startswith("-"):
            continue  # Removed line, don't increment
        else:
            current_line += 1

    return line_map
