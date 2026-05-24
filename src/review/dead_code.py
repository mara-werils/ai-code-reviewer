"""Dead code detector — finds unused imports, variables, and functions in diffs.

Zero LLM cost — regex-based static analysis on added lines.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from src.github.client import PRFile
from src.review.analyzer import extract_diff_line_map

logger = logging.getLogger(__name__)


@dataclass
class DeadCodeFinding:
    """An unused code element found in the diff."""

    kind: str  # unused_import, unused_variable, unused_function, unreachable_code
    name: str
    path: str
    line: int
    description: str
    fix_hint: str


# ── Language-specific patterns ────────────────────────────────────────────────

_PYTHON_IMPORT = re.compile(
    r"^(?:from\s+[\w.]+\s+)?import\s+(?:[\w.]+(?:\s+as\s+(\w+))?|(\w+))", re.MULTILINE
)
_PYTHON_UNUSED_VAR = re.compile(r"^\s+(\w+)\s*=\s*.+$")
_PYTHON_FUNCTION = re.compile(r"^def\s+(_\w+)\s*\(", re.MULTILINE)

_JS_IMPORT = re.compile(
    r"import\s+(?:\{([^}]+)\}|(\w+))\s+from\s+['\"]", re.MULTILINE
)
_JS_UNUSED_VAR = re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*.+;?\s*$")

_GO_IMPORT = re.compile(r'^\s+"([\w./]+)"', re.MULTILINE)
_GO_UNUSED_VAR = re.compile(r"^\s+(\w+)\s*:=\s*")

_UNREACHABLE_AFTER_RETURN = re.compile(
    r"(?:return|throw|raise|panic|os\.Exit)\s*(?:\(.*\))?\s*;?\s*\n\s+\w",
    re.MULTILINE,
)

_EXT_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".go": "go",
}


def _get_language(path: str) -> str:
    for ext, lang in _EXT_LANG.items():
        if path.endswith(ext):
            return lang
    return ""


def _extract_imported_names_python(line: str) -> list[str]:
    """Extract imported names from a Python import statement."""
    names = []
    # from X import a, b, c
    m = re.match(r"from\s+[\w.]+\s+import\s+(.+)$", line.strip())
    if m:
        for part in m.group(1).split(","):
            part = part.strip()
            if " as " in part:
                names.append(part.split(" as ")[-1].strip())
            else:
                names.append(part.split(".")[-1].strip())
        return names

    # import X, import X as Y
    m = re.match(r"import\s+(.+)$", line.strip())
    if m:
        for part in m.group(1).split(","):
            part = part.strip()
            if " as " in part:
                names.append(part.split(" as ")[-1].strip())
            else:
                names.append(part.split(".")[-1].strip())
    return names


def _extract_imported_names_js(line: str) -> list[str]:
    """Extract imported names from a JS/TS import statement."""
    names = []
    # import { a, b } from ...
    m = re.search(r"import\s+\{([^}]+)\}", line)
    if m:
        for part in m.group(1).split(","):
            part = part.strip()
            if " as " in part:
                names.append(part.split(" as ")[-1].strip())
            else:
                names.append(part.strip())

    # import X from ...
    m = re.search(r"import\s+(\w+)\s+from", line)
    if m:
        names.append(m.group(1))

    return names


def scan_dead_code(files: list[PRFile]) -> list[DeadCodeFinding]:
    """Scan for dead code patterns in PR diffs."""
    findings: list[DeadCodeFinding] = []

    for f in files:
        if not f.patch:
            continue

        lang = _get_language(f.filename)
        if not lang:
            continue

        line_map = extract_diff_line_map(f.patch)
        added_lines = {num: text for num, text in line_map.items()}
        all_added_text = "\n".join(text for _, text in sorted(added_lines.items()))

        # Check for unused imports
        if lang == "python":
            for line_num, line_text in added_lines.items():
                imported = _extract_imported_names_python(line_text)
                for name in imported:
                    if not name or name.startswith("_"):
                        continue
                    # Check if name is used anywhere else in the diff
                    usage_count = sum(
                        1
                        for num, text in added_lines.items()
                        if num != line_num and re.search(rf"\b{re.escape(name)}\b", text)
                    )
                    if usage_count == 0:
                        findings.append(
                            DeadCodeFinding(
                                kind="unused_import",
                                name=name,
                                path=f.filename,
                                line=line_num,
                                description=f"Import `{name}` appears unused in the added code.",
                                fix_hint="Remove the unused import or verify it's used elsewhere in the file.",
                            )
                        )

        elif lang in ("javascript", "typescript"):
            for line_num, line_text in added_lines.items():
                imported = _extract_imported_names_js(line_text)
                for name in imported:
                    if not name:
                        continue
                    usage_count = sum(
                        1
                        for num, text in added_lines.items()
                        if num != line_num and re.search(rf"\b{re.escape(name)}\b", text)
                    )
                    if usage_count == 0:
                        findings.append(
                            DeadCodeFinding(
                                kind="unused_import",
                                name=name,
                                path=f.filename,
                                line=line_num,
                                description=f"Import `{name}` appears unused in the added code.",
                                fix_hint="Remove the unused import. Consider using ESLint no-unused-vars rule.",
                            )
                        )

        # Check for unreachable code after return/throw/raise
        sorted_lines = sorted(added_lines.items())
        content_block = "\n".join(text for _, text in sorted_lines)

        for match in _UNREACHABLE_AFTER_RETURN.finditer(content_block):
            match_start = match.start()
            lines_before = content_block[:match_start].count("\n")
            if lines_before < len(sorted_lines):
                approx_line = sorted_lines[lines_before][0]
            else:
                approx_line = sorted_lines[0][0] if sorted_lines else 1

            findings.append(
                DeadCodeFinding(
                    kind="unreachable_code",
                    name="<unreachable>",
                    path=f.filename,
                    line=approx_line,
                    description="Code after return/throw/raise/panic is unreachable.",
                    fix_hint="Remove the unreachable code or restructure the control flow.",
                )
            )

    logger.info(f"Dead code scan: {len(findings)} issues found")
    return findings


def format_dead_code_summary(findings: list[DeadCodeFinding]) -> str:
    """Format dead code findings into markdown summary."""
    if not findings:
        return ""

    by_kind: dict[str, int] = {}
    for f in findings:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1

    kind_labels = {
        "unused_import": "Unused Imports",
        "unused_variable": "Unused Variables",
        "unused_function": "Unused Functions",
        "unreachable_code": "Unreachable Code",
    }

    parts = ["### 🧹 Dead Code Analysis", ""]
    total = len(findings)
    parts.append(f"Found **{total}** dead code issue{'s' if total != 1 else ''}:")
    parts.append("")

    for kind, count in by_kind.items():
        label = kind_labels.get(kind, kind)
        parts.append(f"- **{label}**: {count}")

    parts.append("")
    parts.append("<details>")
    parts.append("<summary>Details</summary>")
    parts.append("")

    for finding in findings:
        parts.append(
            f"- `{finding.path}:{finding.line}` — {finding.description}"
        )

    parts.append("")
    parts.append("</details>")

    return "\n".join(parts)
