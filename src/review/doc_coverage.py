"""Documentation coverage checker — flags undocumented public APIs.

Zero LLM cost — pattern-based detection of public functions, classes,
and methods that lack docstrings or JSDoc comments in PR diffs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from src.github.client import PRFile
from src.review.analyzer import extract_diff_line_map

logger = logging.getLogger(__name__)


@dataclass
class DocCoverageFinding:
    """A public API without documentation."""

    kind: str  # function, class, method
    name: str
    path: str
    line: int
    language: str
    description: str


_EXT_LANG = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".jsx": "javascript", ".go": "go",
    ".java": "java", ".rs": "rust",
}

# Patterns for public API definitions (language-specific)
_PUBLIC_API_PATTERNS = {
    "python": [
        # Public function (no leading underscore)
        (re.compile(r"^(?:async\s+)?def\s+([a-zA-Z][a-zA-Z0-9_]*)\s*\("), "function"),
        # Public class
        (re.compile(r"^class\s+([A-Z][a-zA-Z0-9_]*)\s*[\(:]"), "class"),
    ],
    "javascript": [
        (re.compile(r"^export\s+(?:async\s+)?function\s+(\w+)"), "function"),
        (re.compile(r"^export\s+class\s+(\w+)"), "class"),
        (re.compile(r"^export\s+(?:const|let)\s+(\w+)\s*=\s*(?:async\s+)?(?:function|\()"), "function"),
    ],
    "typescript": [
        (re.compile(r"^export\s+(?:async\s+)?function\s+(\w+)"), "function"),
        (re.compile(r"^export\s+class\s+(\w+)"), "class"),
        (re.compile(r"^export\s+interface\s+(\w+)"), "interface"),
        (re.compile(r"^export\s+type\s+(\w+)"), "type"),
    ],
    "go": [
        # Exported function (starts with uppercase)
        (re.compile(r"^func\s+(?:\([^)]+\)\s+)?([A-Z]\w*)\s*\("), "function"),
        # Exported type
        (re.compile(r"^type\s+([A-Z]\w*)\s+"), "type"),
    ],
    "java": [
        (re.compile(r"^\s*public\s+(?:static\s+)?(?:\w+\s+)+(\w+)\s*\("), "method"),
        (re.compile(r"^\s*public\s+class\s+(\w+)"), "class"),
        (re.compile(r"^\s*public\s+interface\s+(\w+)"), "interface"),
    ],
    "rust": [
        (re.compile(r"^pub\s+(?:async\s+)?fn\s+(\w+)"), "function"),
        (re.compile(r"^pub\s+struct\s+(\w+)"), "struct"),
        (re.compile(r"^pub\s+enum\s+(\w+)"), "enum"),
        (re.compile(r"^pub\s+trait\s+(\w+)"), "trait"),
    ],
}

# Documentation patterns (what counts as documented)
_DOC_PATTERNS = {
    "python": re.compile(r'^\s*"""'),  # Docstring
    "javascript": re.compile(r"^\s*(?:/\*\*|///)"),  # JSDoc or ///
    "typescript": re.compile(r"^\s*(?:/\*\*|///)"),
    "go": re.compile(r"^\s*//\s*\w"),  # Go doc comment
    "java": re.compile(r"^\s*/\*\*"),  # Javadoc
    "rust": re.compile(r"^\s*///"),  # Rust doc comment
}

_TEST_PATTERNS = ("test_", "_test.", ".test.", ".spec.", "tests/", "__tests__/")


def scan_doc_coverage(files: list[PRFile]) -> list[DocCoverageFinding]:
    """Scan for undocumented public APIs in PR diffs."""
    findings: list[DocCoverageFinding] = []

    for f in files:
        if not f.patch:
            continue

        # Skip test files
        if any(p in f.filename.lower() for p in _TEST_PATTERNS):
            continue

        # Determine language
        lang = ""
        for ext, l in _EXT_LANG.items():
            if f.filename.endswith(ext):
                lang = l
                break
        if not lang:
            continue

        patterns = _PUBLIC_API_PATTERNS.get(lang, [])
        doc_pattern = _DOC_PATTERNS.get(lang)
        if not patterns:
            continue

        line_map = extract_diff_line_map(f.patch)
        sorted_lines = sorted(line_map.items())

        for i, (line_num, line_text) in enumerate(sorted_lines):
            stripped = line_text.strip()

            for api_pattern, kind in patterns:
                match = api_pattern.match(stripped)
                if match:
                    name = match.group(1)

                    # Check if previous line has documentation
                    has_doc = False
                    if doc_pattern and i > 0:
                        prev_text = sorted_lines[i - 1][1].strip()
                        if doc_pattern.match(prev_text):
                            has_doc = True

                        # Check 2 lines back (for multi-line doc headers)
                        if not has_doc and i > 1:
                            prev2_text = sorted_lines[i - 2][1].strip()
                            if doc_pattern.match(prev2_text):
                                has_doc = True

                    if not has_doc:
                        findings.append(
                            DocCoverageFinding(
                                kind=kind,
                                name=name,
                                path=f.filename,
                                line=line_num,
                                language=lang,
                                description=(
                                    f"Public {kind} `{name}` is missing documentation. "
                                    f"Add a {'docstring' if lang == 'python' else 'doc comment'}."
                                ),
                            )
                        )
                    break  # Only match first pattern per line

    logger.info(f"Doc coverage scan: {len(findings)} undocumented APIs found")
    return findings


def format_doc_coverage_summary(findings: list[DocCoverageFinding]) -> str:
    """Format doc coverage findings as markdown."""
    if not findings:
        return ""

    parts = ["### 📝 Documentation Coverage", ""]

    by_kind: dict[str, int] = {}
    for f in findings:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1

    total = len(findings)
    parts.append(f"Found **{total}** undocumented public API{'s' if total != 1 else ''}:")
    parts.append("")

    for kind, count in sorted(by_kind.items()):
        parts.append(f"- **{kind.capitalize()}s**: {count}")

    parts.append("")
    parts.append("<details>")
    parts.append("<summary>Details</summary>")
    parts.append("")

    for finding in findings:
        parts.append(f"- `{finding.path}:{finding.line}` — `{finding.name}` ({finding.kind})")

    parts.append("")
    parts.append("</details>")

    return "\n".join(parts)
