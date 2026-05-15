"""Monorepo-native analysis — impact radius and package dependency awareness.

For monorepos with multiple packages/services, analyzes:
1. Which packages are affected by the PR
2. Import/dependency graph between packages
3. Downstream consumers of changed packages
4. Impact radius summary for the review

Configuration via .pr-reviewer-monorepo.yml in repo root.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.github.client import PRFile

logger = logging.getLogger(__name__)


@dataclass
class Package:
    """A package/service in the monorepo."""

    name: str
    path: str  # root path (e.g., "packages/core", "services/api")
    depends_on: list[str] = field(default_factory=list)  # package names
    owners: list[str] = field(default_factory=list)  # GitHub usernames/teams


@dataclass
class MonorepoConfig:
    """Monorepo configuration."""

    packages: list[Package] = field(default_factory=list)

    def get_package(self, name: str) -> Package | None:
        for p in self.packages:
            if p.name == name:
                return p
        return None


@dataclass
class PackageImpact:
    """Impact analysis for a single package."""

    package_name: str
    package_path: str
    changed_files: list[str]
    downstream_consumers: list[str]  # packages that depend on this one
    owners: list[str]
    is_direct: bool = True  # directly changed vs transitive impact


@dataclass
class ImpactAnalysis:
    """Full impact analysis for a PR in a monorepo."""

    directly_changed: list[PackageImpact]
    transitively_affected: list[PackageImpact]
    unowned_files: list[str]  # files not belonging to any package

    @property
    def total_packages_affected(self) -> int:
        return len(self.directly_changed) + len(self.transitively_affected)

    @property
    def all_owners(self) -> list[str]:
        owners: set[str] = set()
        for p in self.directly_changed + self.transitively_affected:
            owners.update(p.owners)
        return sorted(owners)


def load_monorepo_config(path: Path | None = None) -> MonorepoConfig:
    """Load monorepo configuration from .pr-reviewer-monorepo.yml.

    Example file:
    ```yaml
    packages:
      - name: core
        path: packages/core
        owners: ["@backend-team"]

      - name: api
        path: services/api
        depends_on: [core, db]
        owners: ["@api-team"]

      - name: web
        path: apps/web
        depends_on: [core, api]
        owners: ["@frontend-team"]

      - name: db
        path: packages/db
        owners: ["@backend-team"]
    ```
    """
    if path is None:
        path = Path(".pr-reviewer-monorepo.yml")

    if not path.exists():
        return MonorepoConfig()

    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        logger.warning(f"Failed to parse monorepo config {path}: {e}")
        return MonorepoConfig()

    packages_data = data.get("packages", [])
    if not isinstance(packages_data, list):
        return MonorepoConfig()

    packages: list[Package] = []
    for item in packages_data:
        if not isinstance(item, dict) or "name" not in item or "path" not in item:
            continue

        depends_on = item.get("depends_on", [])
        if isinstance(depends_on, str):
            depends_on = [depends_on]

        owners = item.get("owners", [])
        if isinstance(owners, str):
            owners = [owners]

        packages.append(
            Package(
                name=item["name"],
                path=item["path"].rstrip("/"),
                depends_on=depends_on,
                owners=owners,
            )
        )

    return MonorepoConfig(packages=packages)


def _file_belongs_to_package(filename: str, package_path: str) -> bool:
    """Check if a file belongs to a package based on its path prefix."""
    return filename.startswith(package_path + "/") or filename == package_path


def _find_downstream(
    package_name: str,
    all_packages: list[Package],
    visited: set[str] | None = None,
) -> list[str]:
    """Find all packages that depend on the given package (transitively)."""
    if visited is None:
        visited = set()

    if package_name in visited:
        return []
    visited.add(package_name)

    downstream: list[str] = []
    for pkg in all_packages:
        if package_name in pkg.depends_on and pkg.name not in visited:
            downstream.append(pkg.name)
            # Recurse for transitive dependencies
            downstream.extend(_find_downstream(pkg.name, all_packages, visited))

    return downstream


def analyze_monorepo_impact(
    files: list[PRFile],
    config: MonorepoConfig,
) -> ImpactAnalysis:
    """Analyze the impact of changed files across monorepo packages.

    1. Map each changed file to its package
    2. Find downstream consumers of each changed package
    3. Build direct + transitive impact lists
    """
    if not config.packages:
        return ImpactAnalysis(
            directly_changed=[],
            transitively_affected=[],
            unowned_files=[f.filename for f in files],
        )

    # Map files to packages
    package_files: dict[str, list[str]] = {}
    unowned: list[str] = []

    for f in files:
        matched = False
        for pkg in config.packages:
            if _file_belongs_to_package(f.filename, pkg.path):
                package_files.setdefault(pkg.name, []).append(f.filename)
                matched = True
                break
        if not matched:
            unowned.append(f.filename)

    # Build direct impacts
    directly_changed: list[PackageImpact] = []
    all_downstream: set[str] = set()

    for pkg_name, changed_files in package_files.items():
        pkg = config.get_package(pkg_name)
        if not pkg:
            continue

        downstream = _find_downstream(pkg_name, config.packages)
        all_downstream.update(downstream)

        directly_changed.append(
            PackageImpact(
                package_name=pkg_name,
                package_path=pkg.path,
                changed_files=changed_files,
                downstream_consumers=downstream,
                owners=pkg.owners,
                is_direct=True,
            )
        )

    # Build transitive impacts (packages affected but not directly changed)
    transitively_affected: list[PackageImpact] = []
    for downstream_name in all_downstream:
        if downstream_name in package_files:
            continue  # Already directly changed
        pkg = config.get_package(downstream_name)
        if pkg:
            transitively_affected.append(
                PackageImpact(
                    package_name=downstream_name,
                    package_path=pkg.path,
                    changed_files=[],
                    downstream_consumers=[],
                    owners=pkg.owners,
                    is_direct=False,
                )
            )

    return ImpactAnalysis(
        directly_changed=directly_changed,
        transitively_affected=transitively_affected,
        unowned_files=unowned,
    )


def format_impact_comment(analysis: ImpactAnalysis) -> str:
    """Format impact analysis as a review comment section."""
    if not analysis.directly_changed and not analysis.transitively_affected:
        return ""

    parts = [
        "",
        "### Monorepo Impact Radius",
        "",
    ]

    total = analysis.total_packages_affected
    parts.append(
        f"This PR affects **{len(analysis.directly_changed)} package(s) directly** "
        f"and **{len(analysis.transitively_affected)} transitively** "
        f"({total} total)."
    )
    parts.append("")

    # Direct changes
    if analysis.directly_changed:
        parts.append("**Directly changed:**")
        for impact in analysis.directly_changed:
            owners_str = f" (owners: {', '.join(impact.owners)})" if impact.owners else ""
            parts.append(
                f"- `{impact.package_name}` — {len(impact.changed_files)} files{owners_str}"
            )
            if impact.downstream_consumers:
                consumers = ", ".join(f"`{c}`" for c in impact.downstream_consumers)
                parts.append(f"  - Downstream: {consumers}")
        parts.append("")

    # Transitive impacts
    if analysis.transitively_affected:
        parts.append("**Transitively affected** (may need testing):")
        for impact in analysis.transitively_affected:
            owners_str = f" (owners: {', '.join(impact.owners)})" if impact.owners else ""
            parts.append(f"- `{impact.package_name}`{owners_str}")
        parts.append("")

    # Suggested reviewers
    if analysis.all_owners:
        parts.append(f"**Suggested reviewers:** {', '.join(analysis.all_owners)}")
        parts.append("")

    return "\n".join(parts)
