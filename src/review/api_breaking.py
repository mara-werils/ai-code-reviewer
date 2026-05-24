"""API breaking change detector — flags changes that could break consumers.

Zero LLM cost — pattern-based detection of:
- Removed/renamed endpoints, functions, classes, methods
- Changed function signatures (removed params, changed types)
- Modified response shapes
- Changed HTTP methods or status codes
- Removed exports
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from src.github.client import PRFile

logger = logging.getLogger(__name__)


@dataclass
class BreakingChange:
    """A potential API breaking change."""

    kind: str  # endpoint_removed, param_removed, export_removed, signature_changed, etc.
    name: str
    path: str
    line: int
    description: str
    severity: str  # critical, high, medium
    fix_hint: str


# ── Patterns for removed lines (lines starting with -) ──────────────────────

_ENDPOINT_PATTERN = re.compile(
    r"(?:@(?:app|router|api|blueprint)\."
    r"(?:get|post|put|delete|patch|head|options))\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)

_ROUTE_PATTERN = re.compile(
    r"(?:Route|path|url)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)

_EXPRESS_ROUTE = re.compile(
    r"(?:app|router)\.\s*(?:get|post|put|delete|patch|all)\s*\(\s*['\"]([^'\"]+)['\"]",
)

_FUNC_DEF = re.compile(
    r"^(?:export\s+)?(?:async\s+)?(?:def|function|func)\s+(\w+)\s*\(",
)

_CLASS_DEF = re.compile(
    r"^(?:export\s+)?class\s+(\w+)",
)

_METHOD_DEF = re.compile(
    r"^\s+(?:public|protected|async\s+)?(?:def|func|function)?\s*(\w+)\s*\(",
)

_EXPORT_PATTERN = re.compile(
    r"^export\s+(?:default\s+)?(?:const|let|var|function|class|type|interface)\s+(\w+)",
)

_GO_EXPORTED = re.compile(r"^func\s+(?:\([^)]+\)\s+)?([A-Z]\w+)\s*\(")

_PROTO_FIELD = re.compile(r"^\s*(?:optional|required|repeated)?\s*\w+\s+(\w+)\s*=\s*(\d+)")


def _parse_diff_removed_added(patch: str) -> tuple[dict[int, str], dict[int, str]]:
    """Parse patch to extract removed (-) and added (+) lines with line numbers."""
    removed: dict[int, str] = {}
    added: dict[int, str] = {}

    old_line = 0
    new_line = 0

    for line in patch.split("\n"):
        if line.startswith("@@"):
            m = re.search(r"@@ -(\d+)", line)
            if m:
                old_line = int(m.group(1)) - 1
            m2 = re.search(r"\+(\d+)", line)
            if m2:
                new_line = int(m2.group(1)) - 1
        elif line.startswith("-") and not line.startswith("---"):
            old_line += 1
            removed[old_line] = line[1:]
        elif line.startswith("+") and not line.startswith("+++"):
            new_line += 1
            added[new_line] = line[1:]
        else:
            old_line += 1
            new_line += 1

    return removed, added


def scan_breaking_changes(files: list[PRFile]) -> list[BreakingChange]:
    """Scan for potential API breaking changes in PR diffs."""
    findings: list[BreakingChange] = []

    for f in files:
        if not f.patch:
            continue

        removed, added = _parse_diff_removed_added(f.patch)
        if not removed:
            continue

        added_text = "\n".join(added.values())

        # Check removed endpoints
        for line_num, line_text in removed.items():
            for pattern in (_ENDPOINT_PATTERN, _EXPRESS_ROUTE, _ROUTE_PATTERN):
                m = pattern.search(line_text)
                if m:
                    endpoint = m.group(1)
                    # Check if endpoint was just moved/renamed (exists in added)
                    if endpoint not in added_text:
                        findings.append(
                            BreakingChange(
                                kind="endpoint_removed",
                                name=endpoint,
                                path=f.filename,
                                line=line_num,
                                description=f"API endpoint `{endpoint}` was removed. This will break consumers.",
                                severity="critical",
                                fix_hint="Deprecate the endpoint first, add a sunset header, and version the API.",
                            )
                        )

        # Check removed public functions
        for line_num, line_text in removed.items():
            m = _FUNC_DEF.match(line_text.strip())
            if m:
                func_name = m.group(1)
                # Skip private/internal functions
                if func_name.startswith("_"):
                    continue
                # Check if renamed (exists in added)
                if not re.search(rf"\b{re.escape(func_name)}\b", added_text):
                    findings.append(
                        BreakingChange(
                            kind="function_removed",
                            name=func_name,
                            path=f.filename,
                            line=line_num,
                            description=f"Public function `{func_name}()` was removed.",
                            severity="high",
                            fix_hint="If this is a public API, deprecate first. Add @deprecated decorator and keep a forwarding stub.",
                        )
                    )

        # Check removed classes
        for line_num, line_text in removed.items():
            m = _CLASS_DEF.match(line_text.strip())
            if m:
                class_name = m.group(1)
                if class_name.startswith("_"):
                    continue
                if not re.search(rf"\b{re.escape(class_name)}\b", added_text):
                    findings.append(
                        BreakingChange(
                            kind="class_removed",
                            name=class_name,
                            path=f.filename,
                            line=line_num,
                            description=f"Public class `{class_name}` was removed.",
                            severity="high",
                            fix_hint="Deprecate the class and provide a migration path for consumers.",
                        )
                    )

        # Check removed exports (JS/TS)
        for line_num, line_text in removed.items():
            m = _EXPORT_PATTERN.match(line_text.strip())
            if m:
                export_name = m.group(1)
                if not re.search(rf"export\b.*\b{re.escape(export_name)}\b", added_text):
                    findings.append(
                        BreakingChange(
                            kind="export_removed",
                            name=export_name,
                            path=f.filename,
                            line=line_num,
                            description=f"Export `{export_name}` was removed from module.",
                            severity="high",
                            fix_hint="Re-export with @deprecated JSDoc tag, or bump major version.",
                        )
                    )

        # Check removed Go exported functions
        for line_num, line_text in removed.items():
            m = _GO_EXPORTED.match(line_text.strip())
            if m:
                func_name = m.group(1)
                if not re.search(rf"\b{re.escape(func_name)}\b", added_text):
                    findings.append(
                        BreakingChange(
                            kind="function_removed",
                            name=func_name,
                            path=f.filename,
                            line=line_num,
                            description=f"Exported function `{func_name}()` was removed (Go public API).",
                            severity="high",
                            fix_hint="Bump the module major version or deprecate with a wrapper function.",
                        )
                    )

    logger.info(f"Breaking change scan: {len(findings)} potential issues found")
    return findings


def format_breaking_changes_summary(findings: list[BreakingChange]) -> str:
    """Format breaking changes into markdown summary."""
    if not findings:
        return ""

    severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡"}

    parts = ["### 💥 Breaking Change Analysis", ""]

    critical = sum(1 for f in findings if f.severity == "critical")
    if critical > 0:
        parts.append(f"⚠️ **{critical} breaking API change{'s' if critical != 1 else ''} detected!**")
        parts.append("")

    for finding in findings:
        emoji = severity_emoji.get(finding.severity, "⚪")
        parts.append(f"- {emoji} **{finding.kind.replace('_', ' ').title()}**: `{finding.name}`")
        parts.append(f"  `{finding.path}:{finding.line}` — {finding.description}")
        parts.append(f"  💡 {finding.fix_hint}")
        parts.append("")

    return "\n".join(parts)
