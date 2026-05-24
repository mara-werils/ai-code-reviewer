"""Performance anti-pattern detector — zero LLM cost.

Detects common performance issues in PR diffs:
- N+1 query patterns
- O(n²) nested loops
- Unbounded queries (SELECT * without LIMIT)
- Memory leaks (event listeners without cleanup)
- Synchronous I/O in async context
- Inefficient string concatenation in loops
- Missing database indexes hints
- Large payload serialization
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.github.client import PRFile
from src.review.analyzer import extract_diff_line_map

logger = logging.getLogger(__name__)


@dataclass
class PerformanceRule:
    """A single performance scanning rule."""

    id: str
    name: str
    pattern: str
    severity: str  # critical, high, medium, low
    category: str  # query, loop, memory, io, serialization
    description: str
    fix_hint: str = ""
    languages: list[str] = field(default_factory=list)
    exclude_test_files: bool = True


@dataclass
class PerformanceFinding:
    """A performance issue found by the scanner."""

    rule_id: str
    rule_name: str
    severity: str
    category: str
    description: str
    fix_hint: str
    path: str
    line: int
    matched_text: str


# ── Performance rules ─────────────────────────────────────────────────────────

PERFORMANCE_RULES: list[PerformanceRule] = [
    # N+1 query patterns
    PerformanceRule(
        id="PERF001",
        name="N+1 Query Pattern",
        pattern=r"for\s+\w+\s+in\s+.*:\s*\n\s+.*\.(?:query|execute|filter|get|find|fetch|select)",
        severity="high",
        category="query",
        description="Possible N+1 query: database call inside a loop. Each iteration triggers a separate query.",
        fix_hint="Use bulk queries, prefetch_related(), select_related(), or JOIN to fetch all data in one query.",
        languages=["python"],
    ),
    PerformanceRule(
        id="PERF002",
        name="N+1 Query Pattern (JS/TS)",
        pattern=r"(?:for|forEach|map)\s*\(.*\)\s*(?:=>|{)\s*\n?\s*.*(?:await\s+)?(?:prisma|db|knex|sequelize|mongoose)\.",
        severity="high",
        category="query",
        description="Possible N+1 query: database call inside a loop/iterator.",
        fix_hint="Use bulk operations like findMany(), $in operator, or Promise.all() with batched queries.",
        languages=["javascript", "typescript"],
    ),
    # Unbounded queries
    PerformanceRule(
        id="PERF003",
        name="Unbounded SELECT Query",
        pattern=r"SELECT\s+(?:\*|[\w,\s]+)\s+FROM\s+\w+(?:\s+WHERE[^;]*)?(?<!\bLIMIT\b[^;]*);",
        severity="medium",
        category="query",
        description="SELECT query without LIMIT clause may return unbounded results.",
        fix_hint="Add LIMIT clause or use pagination to prevent loading entire tables into memory.",
    ),
    PerformanceRule(
        id="PERF004",
        name="SELECT * Usage",
        pattern=r"SELECT\s+\*\s+FROM",
        severity="low",
        category="query",
        description="SELECT * fetches all columns, which is wasteful when only specific columns are needed.",
        fix_hint="Specify only the columns you need: SELECT col1, col2 FROM table.",
    ),
    # O(n²) patterns
    PerformanceRule(
        id="PERF005",
        name="Nested Loop O(n²)",
        pattern=r"for\s+\w+\s+in\s+(\w+):\s*\n\s+for\s+\w+\s+in\s+\1:",
        severity="high",
        category="loop",
        description="Nested loop iterating over the same collection — O(n²) complexity.",
        fix_hint="Use a set/dict for O(1) lookups, or restructure with itertools or list comprehensions.",
        languages=["python"],
    ),
    PerformanceRule(
        id="PERF006",
        name="Array.includes() in Loop",
        pattern=r"(?:for|forEach|map|filter|reduce).*\n\s+.*\.includes\(",
        severity="medium",
        category="loop",
        description="Array.includes() in a loop is O(n²). Each includes() scans the entire array.",
        fix_hint="Convert to a Set before the loop: const set = new Set(arr); then use set.has().",
        languages=["javascript", "typescript"],
    ),
    # Memory leak patterns
    PerformanceRule(
        id="PERF007",
        name="Event Listener Without Cleanup",
        pattern=r"addEventListener\(['\"](\w+)['\"]",
        severity="medium",
        category="memory",
        description="Event listener added without corresponding removeEventListener. Potential memory leak.",
        fix_hint="Add cleanup: return () => element.removeEventListener(...) in useEffect, or use AbortController.",
        languages=["javascript", "typescript"],
    ),
    PerformanceRule(
        id="PERF008",
        name="setInterval Without Cleanup",
        pattern=r"setInterval\s*\(",
        severity="medium",
        category="memory",
        description="setInterval without clearInterval can cause memory leaks and zombie timers.",
        fix_hint="Store the interval ID and call clearInterval() in cleanup/destructor/useEffect return.",
        languages=["javascript", "typescript"],
    ),
    # Sync I/O in async
    PerformanceRule(
        id="PERF009",
        name="Synchronous File I/O in Async",
        pattern=r"(?:async\s+def|async\s+function).*\n(?:.*\n)*?\s+(?:open\(|readFileSync|writeFileSync|fs\.read(?!Stream)|fs\.write(?!Stream))",
        severity="high",
        category="io",
        description="Synchronous file I/O inside async function blocks the event loop.",
        fix_hint="Use async alternatives: aiofiles (Python), fs.promises (Node.js).",
    ),
    PerformanceRule(
        id="PERF010",
        name="Synchronous HTTP in Async",
        pattern=r"async\s+def\s+.*\n(?:.*\n)*?\s+requests\.",
        severity="high",
        category="io",
        description="Synchronous requests library used inside async function blocks the event loop.",
        fix_hint="Use httpx.AsyncClient or aiohttp instead of requests in async code.",
        languages=["python"],
    ),
    # String concatenation in loops
    PerformanceRule(
        id="PERF011",
        name="String Concatenation in Loop",
        pattern=r"for\s+.*:\s*\n(?:\s+.*\n)*?\s+\w+\s*\+=\s*['\"]",
        severity="medium",
        category="loop",
        description="String concatenation with += in a loop creates many intermediate strings.",
        fix_hint="Use ''.join() with a list (Python), StringBuilder (Java), or template literals (JS).",
        languages=["python", "java"],
    ),
    # Goroutine leaks
    PerformanceRule(
        id="PERF012",
        name="Goroutine Without Context",
        pattern=r"go\s+func\s*\(",
        severity="medium",
        category="memory",
        description="Goroutine launched without context.Context may leak if the parent returns early.",
        fix_hint="Pass context.Context and select on ctx.Done() to allow cancellation.",
        languages=["go"],
    ),
    # Unbounded goroutines
    PerformanceRule(
        id="PERF013",
        name="Unbounded Goroutine Spawning",
        pattern=r"for\s+.*range\s+.*\{\s*\n\s+go\s+",
        severity="high",
        category="memory",
        description="Spawning goroutines in a loop without limits can exhaust memory.",
        fix_hint="Use a worker pool pattern with semaphore channel or errgroup.Group with SetLimit().",
        languages=["go"],
    ),
    # Missing pagination
    PerformanceRule(
        id="PERF014",
        name="ORM Query Without Pagination",
        pattern=r"\.(?:objects|query|find|where)\(.*\)\.(?:all|to_list|fetchall|exec)\(\)",
        severity="medium",
        category="query",
        description="ORM query fetching all results without pagination may cause memory issues.",
        fix_hint="Add .limit()/.offset() or use cursor-based pagination for large datasets.",
    ),
    # Large JSON serialization
    PerformanceRule(
        id="PERF015",
        name="JSON Serialization of Large Objects",
        pattern=r"json\.dumps?\(.*(?:queryset|objects\.all|find\(\)|fetchall)",
        severity="medium",
        category="serialization",
        description="Serializing entire query results to JSON can be slow and memory-intensive.",
        fix_hint="Use streaming serialization (json.JSONEncoder with iterencode) or paginate results.",
        languages=["python"],
    ),
    # React re-render patterns
    PerformanceRule(
        id="PERF016",
        name="Object/Array Literal in JSX Props",
        pattern=r"<\w+[^>]*\s(?:style|options|data|config)=\{\{",
        severity="low",
        category="memory",
        description="Inline object/array literal in JSX props creates new reference on every render.",
        fix_hint="Extract to useMemo(), a constant outside component, or use React.memo().",
        languages=["javascript", "typescript"],
    ),
    PerformanceRule(
        id="PERF017",
        name="Missing useCallback for Event Handler",
        pattern=r"(?:onClick|onChange|onSubmit|onInput)=\{\s*\(\s*\w*\s*\)\s*=>",
        severity="low",
        category="memory",
        description="Inline arrow function in event handler creates new function on every render.",
        fix_hint="Wrap with useCallback() if this component is memoized or passed to child components.",
        languages=["javascript", "typescript"],
    ),
    # Rust-specific
    PerformanceRule(
        id="PERF018",
        name="Clone in Hot Path",
        pattern=r"\.clone\(\)\s*[;,\)]",
        severity="low",
        category="memory",
        description="Excessive .clone() can impact performance. Consider borrowing instead.",
        fix_hint="Use references (&T) or Cow<T> to avoid unnecessary cloning.",
        languages=["rust"],
    ),
    # Python-specific
    PerformanceRule(
        id="PERF019",
        name="List Comprehension as Filter",
        pattern=r"\[.*for\s+\w+\s+in\s+.*if\s+.*\]\s*\[\s*0\s*\]",
        severity="low",
        category="loop",
        description="Filtering entire list to get first match is O(n). Use next() with generator.",
        fix_hint="Use next(x for x in items if condition, default) for O(1) best case.",
        languages=["python"],
    ),
    PerformanceRule(
        id="PERF020",
        name="Global Import of Heavy Module",
        pattern=r"^import\s+(?:pandas|numpy|tensorflow|torch|scipy|sklearn)",
        severity="low",
        category="io",
        description="Heavy module imported at module level increases cold start time.",
        fix_hint="Consider lazy imports inside functions if the module isn't always needed.",
        languages=["python"],
    ),
]

# ── Test file patterns ────────────────────────────────────────────────────────

_TEST_PATTERNS = (
    "test_",
    "_test.",
    ".test.",
    ".spec.",
    "tests/",
    "__tests__/",
    "test/",
    "testing/",
    "e2e/",
    "cypress/",
    "playwright/",
    "fixtures/",
)

_EXT_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".rs": "rust",
    ".kt": "kotlin",
    ".swift": "swift",
    ".cs": "csharp",
}


def _is_test_file(path: str) -> bool:
    return any(p in path.lower() for p in _TEST_PATTERNS)


def _get_language(path: str) -> str:
    for ext, lang in _EXT_LANG.items():
        if path.endswith(ext):
            return lang
    return ""


def scan_performance(
    files: list[PRFile],
    *,
    enabled: bool = True,
) -> list[PerformanceFinding]:
    """Scan PR diff for performance anti-patterns."""
    if not enabled:
        return []

    findings: list[PerformanceFinding] = []

    for f in files:
        if not f.patch:
            continue

        lang = _get_language(f.filename)
        is_test = _is_test_file(f.filename)
        line_map = extract_diff_line_map(f.patch)

        # Get full added content for multi-line pattern matching
        added_lines: dict[int, str] = {}
        for line_num, line_text in line_map.items():
            added_lines[line_num] = line_text

        # Build content block for multi-line matching
        sorted_lines = sorted(added_lines.items())
        content_block = "\n".join(text for _, text in sorted_lines)

        for rule in PERFORMANCE_RULES:
            if is_test and rule.exclude_test_files:
                continue
            if rule.languages and lang not in rule.languages:
                continue

            try:
                compiled = re.compile(rule.pattern, re.MULTILINE | re.IGNORECASE)
            except re.error:
                continue

            # Try single-line matching first
            for line_num, line_text in added_lines.items():
                if re.search(compiled, line_text):
                    findings.append(
                        PerformanceFinding(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            severity=rule.severity,
                            category=rule.category,
                            description=rule.description,
                            fix_hint=rule.fix_hint,
                            path=f.filename,
                            line=line_num,
                            matched_text=line_text.strip()[:200],
                        )
                    )
                    break  # One finding per rule per file

            # Multi-line matching on content block
            else:
                match = compiled.search(content_block)
                if match:
                    # Find the approximate line number
                    match_start = match.start()
                    lines_before = content_block[:match_start].count("\n")
                    if lines_before < len(sorted_lines):
                        approx_line = sorted_lines[lines_before][0]
                    else:
                        approx_line = sorted_lines[0][0] if sorted_lines else 1

                    findings.append(
                        PerformanceFinding(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            severity=rule.severity,
                            category=rule.category,
                            description=rule.description,
                            fix_hint=rule.fix_hint,
                            path=f.filename,
                            line=approx_line,
                            matched_text=match.group()[:200],
                        )
                    )

    logger.info(f"Performance scan: {len(findings)} issues found")
    return findings


def format_performance_summary(findings: list[PerformanceFinding]) -> str:
    """Format performance findings into a markdown summary."""
    if not findings:
        return ""

    by_severity: dict[str, list[PerformanceFinding]] = {}
    for f in findings:
        by_severity.setdefault(f.severity, []).append(f)

    parts = ["### ⚡ Performance Analysis", ""]

    severity_order = ["critical", "high", "medium", "low"]
    severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}

    total = len(findings)
    parts.append(f"Found **{total}** performance issue{'s' if total != 1 else ''}:")
    parts.append("")

    for sev in severity_order:
        items = by_severity.get(sev, [])
        if items:
            emoji = severity_emoji.get(sev, "⚪")
            parts.append(f"- {emoji} **{sev.upper()}**: {len(items)}")

    parts.append("")
    parts.append("<details>")
    parts.append("<summary>Details</summary>")
    parts.append("")

    for finding in findings:
        emoji = severity_emoji.get(finding.severity, "⚪")
        parts.append(
            f"- {emoji} `{finding.path}:{finding.line}` — "
            f"**{finding.rule_name}** ({finding.rule_id}): {finding.description}"
        )

    parts.append("")
    parts.append("</details>")

    return "\n".join(parts)
