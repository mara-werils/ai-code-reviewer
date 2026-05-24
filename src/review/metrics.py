"""Code metrics calculator — cyclomatic & cognitive complexity per function.

Zero LLM cost — regex-based analysis on PR diffs.
Tracks complexity trends to flag functions growing too complex.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.github.client import PRFile
from src.review.analyzer import extract_diff_line_map

logger = logging.getLogger(__name__)

# Complexity thresholds
CYCLOMATIC_WARN = 10
CYCLOMATIC_CRITICAL = 20
COGNITIVE_WARN = 15
COGNITIVE_CRITICAL = 30


@dataclass
class FunctionMetrics:
    """Metrics for a single function/method."""

    name: str
    path: str
    start_line: int
    end_line: int
    lines_of_code: int
    cyclomatic_complexity: int
    cognitive_complexity: int
    max_nesting_depth: int
    parameter_count: int


@dataclass
class MetricsResult:
    """Aggregated metrics for the PR."""

    functions: list[FunctionMetrics] = field(default_factory=list)
    total_added_loc: int = 0
    avg_cyclomatic: float = 0.0
    avg_cognitive: float = 0.0
    max_cyclomatic: int = 0
    max_cognitive: int = 0
    warnings: list[str] = field(default_factory=list)


# ── Complexity counting patterns ─────────────────────────────────────────────

# Branching keywords that increase cyclomatic complexity
_BRANCH_PATTERNS = {
    "python": re.compile(r"\b(?:if|elif|for|while|except|and|or|assert)\b"),
    "javascript": re.compile(r"\b(?:if|else\s+if|for|while|do|case|catch|&&|\|\||\?\?)\b"),
    "typescript": re.compile(r"\b(?:if|else\s+if|for|while|do|case|catch|&&|\|\||\?\?)\b"),
    "go": re.compile(r"\b(?:if|for|case|select|&&|\|\|)\b"),
    "java": re.compile(r"\b(?:if|else\s+if|for|while|do|case|catch|&&|\|\|)\b"),
    "rust": re.compile(r"\b(?:if|else\s+if|for|while|loop|match|&&|\|\|)\b"),
}

# Function definition patterns
_FUNC_PATTERNS = {
    "python": re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)"),
    "javascript": re.compile(
        r"(?:(?:async\s+)?function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>))\s*\(([^)]*)\)"
    ),
    "typescript": re.compile(
        r"(?:(?:async\s+)?function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*(?::\s*\w+)?\s*=\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>))\s*\(([^)]*)\)"
    ),
    "go": re.compile(r"^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(([^)]*)\)"),
    "java": re.compile(r"(?:public|private|protected|static|\s)+\w+\s+(\w+)\s*\(([^)]*)\)"),
    "rust": re.compile(r"(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*(?:<[^>]+>)?\s*\(([^)]*)\)"),
}

# Nesting increase patterns
_NESTING_INCREASE = re.compile(r"[{(]\s*$|:\s*$")
_NESTING_DECREASE = re.compile(r"^\s*[})]")

_EXT_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
    ".kt": "kotlin",
}


def _get_language(path: str) -> str:
    for ext, lang in _EXT_LANG.items():
        if path.endswith(ext):
            return lang
    return ""


def _count_params(params_str: str) -> int:
    """Count function parameters from parameter string."""
    if not params_str or not params_str.strip():
        return 0
    params = [p.strip() for p in params_str.split(",") if p.strip()]
    # Filter out self, cls, ctx for Python/Go
    params = [p for p in params if p not in ("self", "cls")]
    return len(params)


def _compute_cyclomatic(lines: list[str], lang: str) -> int:
    """Compute cyclomatic complexity for a block of code."""
    complexity = 1  # Base complexity
    pattern = _BRANCH_PATTERNS.get(lang)
    if not pattern:
        return complexity

    for line in lines:
        matches = pattern.findall(line)
        complexity += len(matches)

    return complexity


def _compute_cognitive(lines: list[str], lang: str) -> int:
    """Compute cognitive complexity — penalizes nesting."""
    complexity = 0
    nesting = 0
    pattern = _BRANCH_PATTERNS.get(lang)
    if not pattern:
        return complexity

    for line in lines:
        stripped = line.strip()

        # Track nesting depth
        if _NESTING_INCREASE.search(stripped):
            nesting += 1
        if _NESTING_DECREASE.match(stripped):
            nesting = max(0, nesting - 1)

        # Each branch adds 1 + nesting level
        matches = pattern.findall(stripped)
        if matches:
            complexity += len(matches) * (1 + nesting)

    return complexity


def _max_nesting(lines: list[str]) -> int:
    """Calculate max nesting depth."""
    max_depth = 0
    depth = 0

    for line in lines:
        stripped = line.strip()
        if _NESTING_INCREASE.search(stripped):
            depth += 1
            max_depth = max(max_depth, depth)
        if _NESTING_DECREASE.match(stripped):
            depth = max(0, depth - 1)

    return max_depth


def compute_metrics(files: list[PRFile]) -> MetricsResult:
    """Compute code metrics for added/modified functions in PR."""
    result = MetricsResult()

    for f in files:
        if not f.patch:
            continue

        lang = _get_language(f.filename)
        if not lang:
            continue

        line_map = extract_diff_line_map(f.patch)
        if not line_map:
            continue

        sorted_lines = sorted(line_map.items())
        result.total_added_loc += len(sorted_lines)

        # Find functions in added code
        func_pattern = _FUNC_PATTERNS.get(lang)
        if not func_pattern:
            continue

        func_blocks: list[tuple[str, int, list[str], int]] = []  # name, start, lines, params
        current_func: str | None = None
        current_start = 0
        current_lines: list[str] = []
        current_params = 0

        for line_num, line_text in sorted_lines:
            match = func_pattern.match(line_text.strip())
            if match:
                # Save previous function
                if current_func and current_lines:
                    func_blocks.append(
                        (current_func, current_start, current_lines, current_params)
                    )

                # Extract name from match groups (varies by language)
                groups = [g for g in match.groups() if g]
                current_func = groups[0] if groups else "anonymous"
                params_str = groups[1] if len(groups) > 1 else ""
                current_params = _count_params(params_str)
                current_start = line_num
                current_lines = [line_text]
            elif current_func:
                current_lines.append(line_text)

        # Save last function
        if current_func and current_lines:
            func_blocks.append(
                (current_func, current_start, current_lines, current_params)
            )

        # Compute metrics for each function
        for name, start_line, lines, params in func_blocks:
            cc = _compute_cyclomatic(lines, lang)
            cog = _compute_cognitive(lines, lang)
            depth = _max_nesting(lines)

            fm = FunctionMetrics(
                name=name,
                path=f.filename,
                start_line=start_line,
                end_line=start_line + len(lines) - 1,
                lines_of_code=len(lines),
                cyclomatic_complexity=cc,
                cognitive_complexity=cog,
                max_nesting_depth=depth,
                parameter_count=params,
            )
            result.functions.append(fm)

            # Generate warnings
            if cc >= CYCLOMATIC_CRITICAL:
                result.warnings.append(
                    f"🔴 `{f.filename}:{start_line}` — `{name}()` has cyclomatic "
                    f"complexity {cc} (critical threshold: {CYCLOMATIC_CRITICAL})"
                )
            elif cc >= CYCLOMATIC_WARN:
                result.warnings.append(
                    f"🟡 `{f.filename}:{start_line}` — `{name}()` has cyclomatic "
                    f"complexity {cc} (warning threshold: {CYCLOMATIC_WARN})"
                )

            if cog >= COGNITIVE_CRITICAL:
                result.warnings.append(
                    f"🔴 `{f.filename}:{start_line}` — `{name}()` has cognitive "
                    f"complexity {cog} (critical threshold: {COGNITIVE_CRITICAL})"
                )
            elif cog >= COGNITIVE_WARN:
                result.warnings.append(
                    f"🟡 `{f.filename}:{start_line}` — `{name}()` has cognitive "
                    f"complexity {cog} (warning threshold: {COGNITIVE_WARN})"
                )

            if depth > 4:
                result.warnings.append(
                    f"🟡 `{f.filename}:{start_line}` — `{name}()` has nesting "
                    f"depth {depth} (consider refactoring)"
                )

            if params > 5:
                result.warnings.append(
                    f"🟡 `{f.filename}:{start_line}` — `{name}()` has {params} "
                    f"parameters (consider using a config object)"
                )

    # Compute aggregates
    if result.functions:
        ccs = [f.cyclomatic_complexity for f in result.functions]
        cogs = [f.cognitive_complexity for f in result.functions]
        result.avg_cyclomatic = sum(ccs) / len(ccs)
        result.avg_cognitive = sum(cogs) / len(cogs)
        result.max_cyclomatic = max(ccs)
        result.max_cognitive = max(cogs)

    return result


def format_metrics_summary(result: MetricsResult) -> str:
    """Format metrics into a markdown summary."""
    if not result.functions:
        return ""

    parts = ["### 📊 Code Metrics", ""]

    parts.append(f"| Metric | Value |")
    parts.append(f"|--------|-------|")
    parts.append(f"| Functions analyzed | {len(result.functions)} |")
    parts.append(f"| Added LOC | {result.total_added_loc} |")
    parts.append(f"| Avg cyclomatic complexity | {result.avg_cyclomatic:.1f} |")
    parts.append(f"| Max cyclomatic complexity | {result.max_cyclomatic} |")
    parts.append(f"| Avg cognitive complexity | {result.avg_cognitive:.1f} |")
    parts.append(f"| Max cognitive complexity | {result.max_cognitive} |")
    parts.append("")

    if result.warnings:
        parts.append("**Warnings:**")
        parts.append("")
        for w in result.warnings:
            parts.append(f"- {w}")
        parts.append("")

    return "\n".join(parts)
