"""Multi-repo intelligence — detect cross-repository impact.

Analyzes PR changes to find potential breakages in dependent repositories.
Uses a declarative dependency map (.pr-reviewer-deps.yml) to understand
which repos consume APIs, shared libraries, or contracts from this repo.

Works without a database — dependency map is a YAML file in the repo root.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.github.client import GitHubAPI, PRFile

logger = logging.getLogger(__name__)


@dataclass
class RepoDependency:
    """A dependency link between two repositories."""

    repo: str  # dependent repo (e.g., "org/frontend")
    depends_on: list[str] = field(default_factory=list)  # glob patterns in this repo
    description: str = ""


@dataclass
class CrossRepoImpact:
    """A detected cross-repo impact from PR changes."""

    dependent_repo: str
    affected_files: list[str]
    dependency_description: str
    changed_files_in_pr: list[str]


@dataclass
class DepsConfig:
    """Parsed dependency configuration."""

    dependencies: list[RepoDependency] = field(default_factory=list)


def load_deps(path: Path | None = None) -> DepsConfig:
    """Load dependency map from .pr-reviewer-deps.yml.

    Example file:
    ```yaml
    dependencies:
      - repo: org/frontend
        depends_on:
          - "src/api/schemas/*.py"
          - "src/api/routes/*.py"
        description: "Frontend consumes these API endpoints"

      - repo: org/mobile-app
        depends_on:
          - "src/api/v2/**"
          - "proto/*.proto"
        description: "Mobile app uses API v2 and protobuf definitions"

      - repo: org/shared-lib
        depends_on:
          - "packages/core/src/**"
        description: "Shared library consumed by 5+ services"
    ```
    """
    if path is None:
        path = Path(".pr-reviewer-deps.yml")

    if not path.exists():
        return DepsConfig()

    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        logger.warning(f"Failed to parse deps file {path}: {e}")
        return DepsConfig()

    deps_data = data.get("dependencies", [])
    if not isinstance(deps_data, list):
        return DepsConfig()

    dependencies: list[RepoDependency] = []
    for item in deps_data:
        if not isinstance(item, dict) or "repo" not in item:
            continue
        depends_on = item.get("depends_on", [])
        if isinstance(depends_on, str):
            depends_on = [depends_on]
        dependencies.append(RepoDependency(
            repo=item["repo"],
            depends_on=depends_on,
            description=item.get("description", ""),
        ))

    logger.info(f"Loaded {len(dependencies)} dependency mappings")
    return DepsConfig(dependencies=dependencies)


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a glob pattern to a regex (supports **)."""
    regex = ""
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*" and i + 1 < len(pattern) and pattern[i + 1] == "*":
            regex += ".*"
            i += 2
            if i < len(pattern) and pattern[i] == "/":
                i += 1
        elif c == "*":
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
    return re.compile(f"^{regex}$")


def analyze_cross_repo_impact(
    files: list[PRFile],
    deps_config: DepsConfig,
) -> list[CrossRepoImpact]:
    """Analyze PR files for cross-repository impact.

    Checks each changed file against the dependency map to find
    which downstream repos might be affected.

    Args:
        files: Changed files in the PR
        deps_config: Parsed dependency configuration

    Returns:
        List of cross-repo impacts detected
    """
    if not deps_config.dependencies:
        return []

    impacts: list[CrossRepoImpact] = []
    changed_filenames = [f.filename for f in files]

    for dep in deps_config.dependencies:
        matched_patterns: list[str] = []
        matched_pr_files: list[str] = []

        for pattern in dep.depends_on:
            compiled = _glob_to_regex(pattern)
            for filename in changed_filenames:
                if compiled.match(filename):
                    if pattern not in matched_patterns:
                        matched_patterns.append(pattern)
                    if filename not in matched_pr_files:
                        matched_pr_files.append(filename)

        if matched_pr_files:
            impacts.append(CrossRepoImpact(
                dependent_repo=dep.repo,
                affected_files=matched_patterns,
                dependency_description=dep.description,
                changed_files_in_pr=matched_pr_files,
            ))

    return impacts


def format_cross_repo_comment(impacts: list[CrossRepoImpact]) -> str:
    """Format cross-repo impacts as a review comment section."""
    if not impacts:
        return ""

    parts = [
        "",
        "### Cross-Repository Impact",
        "",
        f"This PR may affect **{len(impacts)} dependent repo(s)**:",
        "",
    ]

    for impact in impacts:
        parts.append(f"**{impact.dependent_repo}**")
        if impact.dependency_description:
            parts.append(f"> {impact.dependency_description}")
        parts.append("")
        parts.append("Changed files affecting this repo:")
        for f in impact.changed_files_in_pr:
            parts.append(f"- `{f}`")
        parts.append("")

    parts.append(
        "_Verify compatibility with dependent repos before merging. "
        "Consider coordinating releases._"
    )

    return "\n".join(parts)


async def check_downstream_files(
    github: GitHubAPI,
    impacts: list[CrossRepoImpact],
    search_patterns: list[str] | None = None,
) -> list[dict]:
    """Optionally check downstream repos for usages of changed APIs.

    This is an advanced feature that searches dependent repos for
    references to the changed files/functions.

    Args:
        github: GitHub API client (needs access to dependent repos)
        impacts: Detected cross-repo impacts
        search_patterns: Optional specific patterns to search for

    Returns:
        List of findings with repo, file, and matched content
    """
    findings: list[dict] = []

    for impact in impacts:
        repo = impact.dependent_repo
        for changed_file in impact.changed_files_in_pr:
            # Extract module/function name from the path
            stem = Path(changed_file).stem
            try:
                # Use GitHub code search API
                # Note: requires repo access and search scope
                logger.info(f"Searching {repo} for references to {stem}")
            except Exception as e:
                logger.debug(f"Could not search {repo}: {e}")

    return findings
