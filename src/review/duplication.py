"""Code duplication (clone) detector — finds copy-paste patterns in PR diffs.

Zero LLM cost — uses fingerprinting to detect similar code blocks.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

from src.github.client import PRFile
from src.review.analyzer import extract_diff_line_map

logger = logging.getLogger(__name__)

# Minimum number of consecutive lines to consider a duplicate
MIN_CLONE_LINES = 4
# Minimum number of non-whitespace chars per line to count
MIN_LINE_LENGTH = 10


@dataclass
class DuplicationFinding:
    """A code duplication found across files in the PR."""

    path_a: str
    line_a: int
    path_b: str
    line_b: int
    num_lines: int
    similarity: float  # 0.0-1.0
    snippet: str
    description: str


def _normalize_line(line: str) -> str:
    """Normalize a line for comparison (strip whitespace, lowercase identifiers)."""
    line = line.strip()
    # Remove comments
    line = re.sub(r"//.*$", "", line)
    line = re.sub(r"#.*$", "", line)
    # Normalize whitespace
    line = re.sub(r"\s+", " ", line)
    return line


def _fingerprint(lines: list[str], window: int = MIN_CLONE_LINES) -> dict[str, list[tuple[int, list[str]]]]:
    """Create rolling hash fingerprints of line windows."""
    fingerprints: dict[str, list[tuple[int, list[str]]]] = {}

    for i in range(len(lines) - window + 1):
        window_lines = lines[i : i + window]
        normalized = [_normalize_line(l) for l in window_lines]

        # Skip windows with too many short/empty lines
        meaningful = sum(1 for l in normalized if len(l) >= MIN_LINE_LENGTH)
        if meaningful < window // 2:
            continue

        key = hashlib.md5("\n".join(normalized).encode()).hexdigest()
        fingerprints.setdefault(key, []).append((i, window_lines))

    return fingerprints


def scan_duplication(files: list[PRFile]) -> list[DuplicationFinding]:
    """Scan for duplicated code blocks across files in a PR."""
    findings: list[DuplicationFinding] = []

    # Collect added lines per file
    file_lines: list[tuple[str, list[tuple[int, str]]]] = []

    for f in files:
        if not f.patch:
            continue

        line_map = extract_diff_line_map(f.patch)
        if not line_map:
            continue

        sorted_lines = sorted(line_map.items())
        file_lines.append((f.filename, sorted_lines))

    if len(file_lines) < 2:
        return findings

    # Build fingerprints per file
    file_fingerprints: list[tuple[str, list[tuple[int, str]], dict]] = []

    for path, lines in file_lines:
        texts = [text for _, text in lines]
        fps = _fingerprint(texts)
        if fps:
            file_fingerprints.append((path, lines, fps))

    # Compare fingerprints across files
    seen_pairs: set[tuple[str, str]] = set()

    for i, (path_a, lines_a, fps_a) in enumerate(file_fingerprints):
        for j in range(i + 1, len(file_fingerprints)):
            path_b, lines_b, fps_b = file_fingerprints[j]

            pair_key = (min(path_a, path_b), max(path_a, path_b))
            if pair_key in seen_pairs:
                continue

            # Find matching fingerprints
            common_keys = set(fps_a.keys()) & set(fps_b.keys())
            if not common_keys:
                continue

            seen_pairs.add(pair_key)

            for key in list(common_keys)[:3]:  # Limit findings per pair
                locs_a = fps_a[key]
                locs_b = fps_b[key]

                for idx_a, snippet_a in locs_a[:1]:
                    for idx_b, snippet_b in locs_b[:1]:
                        line_num_a = lines_a[idx_a][0] if idx_a < len(lines_a) else 1
                        line_num_b = lines_b[idx_b][0] if idx_b < len(lines_b) else 1

                        snippet_text = "\n".join(snippet_a[:4])
                        if len(snippet_text) > 200:
                            snippet_text = snippet_text[:200] + "..."

                        findings.append(
                            DuplicationFinding(
                                path_a=path_a,
                                line_a=line_num_a,
                                path_b=path_b,
                                line_b=line_num_b,
                                num_lines=MIN_CLONE_LINES,
                                similarity=1.0,
                                snippet=snippet_text,
                                description=(
                                    f"Duplicated code block ({MIN_CLONE_LINES}+ lines) "
                                    f"found in `{path_a}` and `{path_b}`. "
                                    f"Consider extracting to a shared function."
                                ),
                            )
                        )

    logger.info(f"Duplication scan: {len(findings)} clones found")
    return findings


def format_duplication_summary(findings: list[DuplicationFinding]) -> str:
    """Format duplication findings into markdown summary."""
    if not findings:
        return ""

    parts = ["### 📋 Code Duplication Analysis", ""]
    total = len(findings)
    parts.append(f"Found **{total}** code clone{'s' if total != 1 else ''}:")
    parts.append("")

    for finding in findings:
        parts.append(
            f"- `{finding.path_a}:{finding.line_a}` ↔ `{finding.path_b}:{finding.line_b}` "
            f"— {finding.num_lines} duplicated lines"
        )
        parts.append(f"  ```")
        parts.append(f"  {finding.snippet[:150]}")
        parts.append(f"  ```")

    return "\n".join(parts)
