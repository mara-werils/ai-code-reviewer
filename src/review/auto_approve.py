"""Auto-approve engine — automatically approves low-risk PRs.

Evaluates PRs against safety criteria and auto-approves when all
conditions are met. Configurable rules for what qualifies as "safe".
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.github.client import PRFile, PRInfo

logger = logging.getLogger(__name__)


@dataclass
class AutoApproveConfig:
    """Configuration for auto-approve behavior."""

    enabled: bool = False
    max_files: int = 5
    max_lines_changed: int = 100
    allowed_categories: list[str] = field(
        default_factory=lambda: ["docs", "test", "chore", "style", "ci"]
    )
    allowed_extensions: list[str] = field(
        default_factory=lambda: [
            ".md", ".txt", ".rst", ".yml", ".yaml", ".json",
            ".toml", ".cfg", ".ini", ".env.example",
            ".gitignore", ".editorconfig", ".prettierrc",
        ]
    )
    blocked_paths: list[str] = field(
        default_factory=lambda: [
            "*.lock", "*.sql", "migration*", "*secret*",
            "*password*", "*credential*", "*auth*",
            "Dockerfile", "docker-compose*",
            ".github/workflows/*", ".gitlab-ci*",
        ]
    )
    require_tests_for_code: bool = True
    max_complexity_score: int = 20


@dataclass
class ApprovalDecision:
    """Result of auto-approve evaluation."""

    approved: bool
    reason: str
    checks_passed: list[str]
    checks_failed: list[str]
    risk_score: int  # 0-100


def _matches_glob(path: str, pattern: str) -> bool:
    """Simple glob matching."""
    import fnmatch
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path.split("/")[-1], pattern)


def _is_docs_only(files: list[PRFile]) -> bool:
    """Check if PR only touches documentation files."""
    doc_extensions = {".md", ".txt", ".rst", ".adoc", ".html"}
    return all(
        any(f.filename.lower().endswith(ext) for ext in doc_extensions)
        for f in files
    )


def _is_test_only(files: list[PRFile]) -> bool:
    """Check if PR only touches test files."""
    test_patterns = ("test_", "_test.", ".test.", ".spec.", "tests/", "__tests__/")
    return all(
        any(p in f.filename.lower() for p in test_patterns)
        for f in files
    )


def _is_config_only(files: list[PRFile]) -> bool:
    """Check if PR only touches config files."""
    config_extensions = {
        ".yml", ".yaml", ".json", ".toml", ".cfg", ".ini",
        ".gitignore", ".editorconfig", ".prettierrc", ".eslintrc",
    }
    return all(
        any(f.filename.lower().endswith(ext) for ext in config_extensions)
        for f in files
    )


def _has_blocked_files(files: list[PRFile], blocked_paths: list[str]) -> list[str]:
    """Check for files that block auto-approval."""
    blocked = []
    for f in files:
        for pattern in blocked_paths:
            if _matches_glob(f.filename, pattern):
                blocked.append(f.filename)
                break
    return blocked


def evaluate_auto_approve(
    pr: PRInfo,
    files: list[PRFile],
    config: AutoApproveConfig | None = None,
    review_risk_level: str = "",
    complexity_score: int = 0,
) -> ApprovalDecision:
    """Evaluate whether a PR qualifies for auto-approval."""
    if config is None:
        config = AutoApproveConfig()

    if not config.enabled:
        return ApprovalDecision(
            approved=False,
            reason="Auto-approve is disabled.",
            checks_passed=[],
            checks_failed=["auto_approve_disabled"],
            risk_score=0,
        )

    checks_passed: list[str] = []
    checks_failed: list[str] = []
    risk_score = 0

    # Check file count
    if len(files) <= config.max_files:
        checks_passed.append(f"file_count: {len(files)} <= {config.max_files}")
    else:
        checks_failed.append(f"file_count: {len(files)} > {config.max_files}")
        risk_score += 20

    # Check total lines changed
    total_lines = sum(f.additions + f.deletions for f in files)
    if total_lines <= config.max_lines_changed:
        checks_passed.append(f"lines_changed: {total_lines} <= {config.max_lines_changed}")
    else:
        checks_failed.append(f"lines_changed: {total_lines} > {config.max_lines_changed}")
        risk_score += 20

    # Check for blocked files
    blocked = _has_blocked_files(files, config.blocked_paths)
    if not blocked:
        checks_passed.append("no_blocked_files")
    else:
        checks_failed.append(f"blocked_files: {', '.join(blocked[:3])}")
        risk_score += 30

    # Check if docs/test/config only
    is_safe_category = _is_docs_only(files) or _is_test_only(files) or _is_config_only(files)
    if is_safe_category:
        checks_passed.append("safe_category_only")
        risk_score = max(0, risk_score - 20)
    else:
        # Check file extensions against allowed list
        all_allowed = all(
            any(f.filename.endswith(ext) for ext in config.allowed_extensions)
            for f in files
        )
        if all_allowed:
            checks_passed.append("all_extensions_allowed")
        else:
            checks_failed.append("contains_code_files")
            risk_score += 15

    # Check review risk level
    if review_risk_level in ("low", ""):
        checks_passed.append(f"risk_level: {review_risk_level or 'not_evaluated'}")
    else:
        checks_failed.append(f"risk_level: {review_risk_level}")
        risk_score += 25

    # Check complexity score
    if complexity_score <= config.max_complexity_score:
        checks_passed.append(f"complexity: {complexity_score} <= {config.max_complexity_score}")
    else:
        checks_failed.append(f"complexity: {complexity_score} > {config.max_complexity_score}")
        risk_score += 15

    # Check PR title for WIP/DRAFT indicators
    title_lower = pr.title.lower()
    if any(w in title_lower for w in ("wip", "draft", "do not merge", "dnm", "wip:")):
        checks_failed.append("pr_title_indicates_draft")
        risk_score += 50

    # Decision
    approved = len(checks_failed) == 0 and risk_score < 30

    if approved:
        reason = f"All {len(checks_passed)} safety checks passed. Risk score: {risk_score}/100."
    else:
        reason = f"Failed {len(checks_failed)} check(s): {'; '.join(checks_failed[:3])}."

    return ApprovalDecision(
        approved=approved,
        reason=reason,
        checks_passed=checks_passed,
        checks_failed=checks_failed,
        risk_score=risk_score,
    )


def format_approval_comment(decision: ApprovalDecision) -> str:
    """Format approval decision as a PR comment."""
    if decision.approved:
        parts = [
            "## ✅ Auto-Approved",
            "",
            decision.reason,
            "",
            "<details>",
            "<summary>Safety checks</summary>",
            "",
        ]
        for check in decision.checks_passed:
            parts.append(f"- ✅ {check}")
        parts.append("")
        parts.append("</details>")
    else:
        parts = [
            "## ❌ Auto-Approve Blocked",
            "",
            decision.reason,
            "",
        ]
        if decision.checks_failed:
            parts.append("**Failed checks:**")
            for check in decision.checks_failed:
                parts.append(f"- ❌ {check}")
        parts.append("")
        if decision.checks_passed:
            parts.append("**Passed checks:**")
            for check in decision.checks_passed:
                parts.append(f"- ✅ {check}")

    return "\n".join(parts)
