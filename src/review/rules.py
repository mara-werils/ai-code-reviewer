"""Declarative review rules engine.

Loads rules from `.pr-reviewer-rules.yml` and evaluates them against PR diffs
to produce deterministic, team-defined review comments alongside AI review.

Supported rule types:
1. **pattern** — regex match on added lines (e.g., detect raw SQL, hardcoded secrets)
2. **file_match** — trigger when files matching a glob are changed but no files
   matching another glob are present (e.g., API changed without tests)
"""

from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.github.client import PRFile
from src.review.analyzer import extract_diff_line_map

logger = logging.getLogger(__name__)


@dataclass
class Rule:
    """A single review rule."""

    name: str
    severity: str = "warning"  # critical, warning, suggestion, info
    message: str = ""

    # Pattern rule: regex matched against added lines
    pattern: str = ""

    # File-match rule: trigger when files_match but no_files_match is absent
    files_match: str = ""
    no_files_match: str = ""

    # Optional: only apply to files matching this glob
    include_files: str = ""
    # Optional: skip files matching this glob
    exclude_files: str = ""

    def __post_init__(self) -> None:
        if self.severity not in ("critical", "warning", "suggestion", "info"):
            self.severity = "warning"


@dataclass
class RuleViolation:
    """A single violation found by a rule."""

    rule_name: str
    severity: str
    message: str
    path: str
    line: int = 0
    matched_text: str = ""


@dataclass
class RulesConfig:
    """Parsed rules configuration."""

    rules: list[Rule] = field(default_factory=list)


def load_rules(path: Path | None = None) -> RulesConfig:
    """Load rules from .pr-reviewer-rules.yml.

    Args:
        path: Path to rules file. Defaults to .pr-reviewer-rules.yml in CWD.

    Returns:
        Parsed RulesConfig. Empty if file doesn't exist or is invalid.
    """
    if path is None:
        path = Path(".pr-reviewer-rules.yml")

    if not path.exists():
        return RulesConfig()

    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        logger.warning(f"Failed to parse rules file {path}: {e}")
        return RulesConfig()

    rules_data = data.get("rules", [])
    if not isinstance(rules_data, list):
        logger.warning(f"'rules' in {path} is not a list")
        return RulesConfig()

    rules: list[Rule] = []
    for item in rules_data:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "")
        if not name:
            continue

        # Handle nested 'when' block for file_match rules
        when = item.get("when", {})
        if isinstance(when, dict):
            files_match = when.get("files_match", "")
            no_files_match = when.get("no_files_match", "")
        else:
            files_match = ""
            no_files_match = ""

        rules.append(
            Rule(
                name=name,
                severity=item.get("severity", "warning"),
                message=item.get("message", f"Rule '{name}' violated"),
                pattern=item.get("pattern", ""),
                files_match=files_match or item.get("files_match", ""),
                no_files_match=no_files_match or item.get("no_files_match", ""),
                include_files=item.get("include_files", ""),
                exclude_files=item.get("exclude_files", ""),
            )
        )

    logger.info(f"Loaded {len(rules)} rules from {path}")
    return RulesConfig(rules=rules)


def _file_matches_glob(filename: str, glob_pattern: str) -> bool:
    """Check if a filename matches a glob pattern (supports ** for recursive).

    Converts ** to a regex that matches any number of path segments.
    """
    # Convert glob to regex
    # First escape regex special chars except * and ?
    regex = ""
    i = 0
    pattern = glob_pattern
    while i < len(pattern):
        c = pattern[i]
        if c == "*" and i + 1 < len(pattern) and pattern[i + 1] == "*":
            # ** matches any number of directories
            regex += ".*"
            i += 2
            # Skip trailing /
            if i < len(pattern) and pattern[i] == "/":
                i += 1
        elif c == "*":
            # * matches anything except /
            regex += "[^/]*"
            i += 1
        elif c == "?":
            regex += "[^/]"
            i += 1
        elif c in ".+^${}()|[]":
            regex += "\\" + c
            i += 1
        else:
            regex += c
            i += 1

    return bool(re.match(f"^{regex}$", filename))


def evaluate_rules(
    rules_config: RulesConfig,
    files: list[PRFile],
) -> list[RuleViolation]:
    """Evaluate all rules against PR files.

    Args:
        rules_config: Parsed rules configuration
        files: List of PR files with patches

    Returns:
        List of violations found
    """
    if not rules_config.rules:
        return []

    violations: list[RuleViolation] = []
    all_filenames = [f.filename for f in files]

    for rule in rules_config.rules:
        if rule.pattern:
            violations.extend(_evaluate_pattern_rule(rule, files))
        elif rule.files_match:
            violations.extend(_evaluate_file_match_rule(rule, all_filenames))

    return violations


def _evaluate_pattern_rule(rule: Rule, files: list[PRFile]) -> list[RuleViolation]:
    """Evaluate a regex pattern rule against added lines in the diff."""
    violations: list[RuleViolation] = []

    try:
        compiled = re.compile(rule.pattern)
    except re.error as e:
        logger.warning(f"Invalid regex in rule '{rule.name}': {e}")
        return []

    for f in files:
        # Apply include/exclude filters
        if rule.include_files and not _file_matches_glob(f.filename, rule.include_files):
            continue
        if rule.exclude_files and _file_matches_glob(f.filename, rule.exclude_files):
            continue

        if not f.patch:
            continue

        line_map = extract_diff_line_map(f.patch)

        for line_num, line_content in line_map.items():
            match = compiled.search(line_content)
            if match:
                violations.append(
                    RuleViolation(
                        rule_name=rule.name,
                        severity=rule.severity,
                        message=rule.message,
                        path=f.filename,
                        line=line_num,
                        matched_text=match.group(0),
                    )
                )

    return violations


def _evaluate_file_match_rule(
    rule: Rule,
    all_filenames: list[str],
) -> list[RuleViolation]:
    """Evaluate a file-match rule (files_match present but no_files_match absent)."""
    has_match = any(
        _file_matches_glob(fn, rule.files_match) for fn in all_filenames
    )

    if not has_match:
        return []

    # If no_files_match is set, check that at least one file matches it
    if rule.no_files_match:
        has_counter = any(
            _file_matches_glob(fn, rule.no_files_match) for fn in all_filenames
        )
        if has_counter:
            return []  # Counter-files exist, rule passes

    # Find the triggering files for context
    triggering = [fn for fn in all_filenames if _file_matches_glob(fn, rule.files_match)]

    return [
        RuleViolation(
            rule_name=rule.name,
            severity=rule.severity,
            message=rule.message,
            path=triggering[0] if triggering else "",
            line=0,
            matched_text="",
        )
    ]


def format_rule_violations(violations: list[RuleViolation]) -> list[dict]:
    """Format rule violations as review comment dicts (same shape as AI comments).

    Returns list of dicts with: path, line, body, severity.
    """
    comments: list[dict] = []
    for v in violations:
        severity_label = {
            "critical": "[CRITICAL]",
            "warning": "[WARNING]",
            "suggestion": "[SUGGESTION]",
            "info": "[INFO]",
        }.get(v.severity, "[WARNING]")

        body = f"**{severity_label} Rule: {v.rule_name}**\n\n{v.message}"
        if v.matched_text:
            body += f"\n\nMatched: `{v.matched_text}`"

        comments.append(
            {
                "path": v.path,
                "line": v.line,
                "body": body,
                "severity": v.severity,
            }
        )

    return comments
