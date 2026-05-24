"""Review policies engine — enforces team-level review requirements.

Declarative YAML-based policies that define review requirements:
- Minimum reviewers for certain paths
- Required checks before merge
- File change restrictions
- Branch protection rules
- Size limits
"""

from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass, field

from src.github.client import PRFile, PRInfo

logger = logging.getLogger(__name__)


@dataclass
class PolicyViolation:
    """A policy that was violated."""

    policy_id: str
    policy_name: str
    severity: str  # error, warning
    message: str
    details: str = ""


@dataclass
class Policy:
    """A single review policy rule."""

    id: str
    name: str
    description: str
    severity: str = "error"  # error = blocks merge, warning = advisory
    enabled: bool = True


@dataclass
class SizeLimitPolicy(Policy):
    max_files: int = 30
    max_lines: int = 1000
    max_additions: int = 800


@dataclass
class PathRestrictionPolicy(Policy):
    restricted_paths: list[str] = field(default_factory=list)
    allowed_authors: list[str] = field(default_factory=list)
    require_approval_from: list[str] = field(default_factory=list)


@dataclass
class RequiredFilePolicy(Policy):
    """Require certain files to be present when others change."""

    when_changed: list[str] = field(default_factory=list)  # Glob patterns
    must_include: list[str] = field(default_factory=list)   # Required files


@dataclass
class ConventionPolicy(Policy):
    """Enforce naming/message conventions."""

    title_pattern: str = ""
    branch_pattern: str = ""
    commit_pattern: str = ""


@dataclass
class ReviewPolicies:
    """Collection of policies to enforce."""

    size_limits: SizeLimitPolicy | None = None
    path_restrictions: list[PathRestrictionPolicy] = field(default_factory=list)
    required_files: list[RequiredFilePolicy] = field(default_factory=list)
    conventions: ConventionPolicy | None = None
    require_description: bool = True
    min_description_length: int = 20
    require_labels: bool = False
    blocked_patterns_in_diff: list[str] = field(default_factory=list)


def _default_policies() -> ReviewPolicies:
    """Default sensible policies."""
    return ReviewPolicies(
        size_limits=SizeLimitPolicy(
            id="SIZE001",
            name="PR Size Limit",
            description="Enforce maximum PR size for reviewability.",
            severity="warning",
        ),
        required_files=[
            RequiredFilePolicy(
                id="REQ001",
                name="Tests Required for Source Changes",
                description="Source code changes should include test updates.",
                severity="warning",
                when_changed=["src/**/*.py", "src/**/*.ts", "src/**/*.js", "src/**/*.go"],
                must_include=["tests/**", "test/**", "**/*.test.*", "**/*.spec.*", "**/test_*"],
            ),
        ],
        conventions=ConventionPolicy(
            id="CONV001",
            name="PR Title Convention",
            description="PR title should follow conventional format.",
            severity="warning",
            title_pattern=r"^(?:feat|fix|docs|style|refactor|perf|test|chore|ci|build|revert)[\(:]",
        ),
        require_description=True,
        min_description_length=20,
        blocked_patterns_in_diff=[
            r"(?:TODO|FIXME|HACK|XXX):\s*$",  # Empty TODOs
            r"console\.log\(",  # Debug logging
            r"debugger;?$",  # Debugger statements
            r"binding\.pry",  # Ruby debugger
            r"import\s+pdb",  # Python debugger
        ],
    )


def evaluate_policies(
    pr: PRInfo,
    files: list[PRFile],
    policies: ReviewPolicies | None = None,
) -> list[PolicyViolation]:
    """Evaluate all policies against a PR."""
    if policies is None:
        policies = _default_policies()

    violations: list[PolicyViolation] = []

    # Size limits
    if policies.size_limits and policies.size_limits.enabled:
        sl = policies.size_limits
        total_files = len(files)
        total_additions = sum(f.additions for f in files)
        total_deletions = sum(f.deletions for f in files)
        total_lines = total_additions + total_deletions

        if total_files > sl.max_files:
            violations.append(
                PolicyViolation(
                    policy_id=sl.id,
                    policy_name=sl.name,
                    severity=sl.severity,
                    message=f"PR has {total_files} files (limit: {sl.max_files}).",
                    details="Consider splitting into smaller PRs.",
                )
            )
        if total_lines > sl.max_lines:
            violations.append(
                PolicyViolation(
                    policy_id=sl.id,
                    policy_name=sl.name,
                    severity=sl.severity,
                    message=f"PR has {total_lines} lines changed (limit: {sl.max_lines}).",
                )
            )

    # Path restrictions
    for pr_policy in policies.path_restrictions:
        if not pr_policy.enabled:
            continue
        for f in files:
            for pattern in pr_policy.restricted_paths:
                if fnmatch.fnmatch(f.filename, pattern):
                    if pr.author not in pr_policy.allowed_authors:
                        violations.append(
                            PolicyViolation(
                                policy_id=pr_policy.id,
                                policy_name=pr_policy.name,
                                severity=pr_policy.severity,
                                message=f"File `{f.filename}` requires special approval.",
                                details=f"Allowed authors: {', '.join(pr_policy.allowed_authors) or 'none configured'}",
                            )
                        )

    # Required files
    for req in policies.required_files:
        if not req.enabled:
            continue

        changed_paths = [f.filename for f in files]
        trigger = any(
            any(fnmatch.fnmatch(p, pattern) for pattern in req.when_changed)
            for p in changed_paths
        )

        if trigger:
            has_required = any(
                any(fnmatch.fnmatch(p, pattern) for pattern in req.must_include)
                for p in changed_paths
            )
            if not has_required:
                violations.append(
                    PolicyViolation(
                        policy_id=req.id,
                        policy_name=req.name,
                        severity=req.severity,
                        message="Source code changed but no test files included.",
                        details=f"Expected test files matching: {', '.join(req.must_include[:3])}",
                    )
                )

    # Conventions
    if policies.conventions and policies.conventions.enabled:
        conv = policies.conventions
        if conv.title_pattern:
            if not re.match(conv.title_pattern, pr.title):
                violations.append(
                    PolicyViolation(
                        policy_id=conv.id,
                        policy_name=conv.name,
                        severity=conv.severity,
                        message=f"PR title doesn't match pattern: `{conv.title_pattern}`",
                        details=f"Current title: '{pr.title}'",
                    )
                )

        if conv.branch_pattern:
            if not re.match(conv.branch_pattern, pr.head_ref):
                violations.append(
                    PolicyViolation(
                        policy_id=conv.id,
                        policy_name=conv.name,
                        severity=conv.severity,
                        message=f"Branch name doesn't match pattern: `{conv.branch_pattern}`",
                        details=f"Current branch: '{pr.head_ref}'",
                    )
                )

    # Description requirements
    if policies.require_description:
        body = (pr.body or "").strip()
        if len(body) < policies.min_description_length:
            violations.append(
                PolicyViolation(
                    policy_id="DESC001",
                    policy_name="PR Description Required",
                    severity="warning",
                    message=f"PR description is too short ({len(body)} chars, minimum: {policies.min_description_length}).",
                    details="Add a meaningful description explaining the changes and motivation.",
                )
            )

    # Blocked patterns in diff
    if policies.blocked_patterns_in_diff:
        from src.review.analyzer import extract_diff_line_map

        for f in files:
            if not f.patch:
                continue
            line_map = extract_diff_line_map(f.patch)
            for line_num, line_text in line_map.items():
                for pattern in policies.blocked_patterns_in_diff:
                    if re.search(pattern, line_text):
                        violations.append(
                            PolicyViolation(
                                policy_id="BLOCK001",
                                policy_name="Blocked Pattern",
                                severity="warning",
                                message=f"Blocked pattern found in `{f.filename}:{line_num}`.",
                                details=f"Pattern: `{pattern}` matched: `{line_text.strip()[:100]}`",
                            )
                        )
                        break  # One violation per file per pattern

    return violations


def format_policy_report(violations: list[PolicyViolation]) -> str:
    """Format policy violations as markdown."""
    if not violations:
        return "### ✅ All review policies passed"

    errors = [v for v in violations if v.severity == "error"]
    warnings = [v for v in violations if v.severity == "warning"]

    parts = ["### 📜 Review Policy Report", ""]

    if errors:
        parts.append(f"**{len(errors)} error(s)** — must be resolved before merge:")
        parts.append("")
        for v in errors:
            parts.append(f"- 🔴 **{v.policy_name}** ({v.policy_id}): {v.message}")
            if v.details:
                parts.append(f"  _{v.details}_")
        parts.append("")

    if warnings:
        parts.append(f"**{len(warnings)} warning(s):**")
        parts.append("")
        for v in warnings:
            parts.append(f"- 🟡 **{v.policy_name}** ({v.policy_id}): {v.message}")
            if v.details:
                parts.append(f"  _{v.details}_")

    return "\n".join(parts)
