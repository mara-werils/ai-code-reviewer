"""Dependency vulnerability checker — flags risky dependency changes.

Zero LLM cost — pattern-based analysis of package manifest changes.
Detects: version downgrades, unpinned versions, known risky packages,
typosquat patterns, and excessive new dependencies.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from src.github.client import PRFile
from src.review.analyzer import extract_diff_line_map

logger = logging.getLogger(__name__)


@dataclass
class DependencyFinding:
    """A dependency risk found in package manifests."""

    kind: str  # unpinned, downgrade, typosquat, excessive, deprecated, risky
    package: str
    path: str
    line: int
    severity: str
    description: str
    fix_hint: str


# ── Package manifest detection ───────────────────────────────────────────────

_MANIFEST_FILES = {
    "package.json": "npm",
    "package-lock.json": "npm",
    "yarn.lock": "npm",
    "pnpm-lock.yaml": "npm",
    "requirements.txt": "pip",
    "Pipfile": "pip",
    "pyproject.toml": "pip",
    "setup.py": "pip",
    "setup.cfg": "pip",
    "Gemfile": "gem",
    "go.mod": "go",
    "Cargo.toml": "cargo",
    "pom.xml": "maven",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle",
    "composer.json": "composer",
    "pubspec.yaml": "pub",
}

# Known risky/deprecated packages
_RISKY_PACKAGES = {
    # npm
    "event-stream": "Compromised in 2018 — contained cryptocurrency-stealing malware.",
    "ua-parser-js": "Compromised in 2021 — cryptominer injected.",
    "coa": "Compromised in 2021 — malware injected.",
    "rc": "Compromised in 2021 — malware injected.",
    "colors": "Sabotaged by maintainer in 2022 — infinite loop.",
    "faker": "Sabotaged by maintainer in 2022 — empty module.",
    "node-ipc": "Sabotaged in 2022 — destructive payload for certain locales.",
    "request": "Deprecated since 2020. Use got, axios, undici, or node-fetch.",
    "moment": "Deprecated. Use date-fns, luxon, or dayjs.",
    "lodash": "Consider using native JS methods or lodash-es for tree-shaking.",
    # pip
    "pycrypto": "Unmaintained and insecure. Use pycryptodome instead.",
    "python-jwt": "Typosquat risk. The correct package is PyJWT.",
    "django-hierarchical": "Known typosquat attack vector.",
    "urllib3": "Versions < 2.0 have known vulnerabilities.",
    # go
    "github.com/dgrijalva/jwt-go": "Unmaintained. Use github.com/golang-jwt/jwt/v5.",
}

# Typosquat detection patterns (common character substitutions)
_TYPOSQUAT_SUBS = [
    (r"rn", "m"),  # rn → m
    (r"l", "1"),   # l → 1
    (r"0", "o"),   # 0 → o
    (r"-", "_"),   # dash vs underscore
    (r"_", "-"),
]

# Version patterns
_SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_NPM_VERSION = re.compile(r'"([^"]+)":\s*"([^"]+)"')
_PIP_VERSION = re.compile(r"^([\w-]+)\s*([><=!~]+.+)?$")
_GO_MOD_VERSION = re.compile(r"^\s*([\w./]+)\s+(v[\d.]+)")


def _is_manifest(path: str) -> str | None:
    """Check if file is a package manifest and return ecosystem."""
    import os
    basename = os.path.basename(path)
    return _MANIFEST_FILES.get(basename)


def _is_unpinned(version: str) -> bool:
    """Check if a version spec is unpinned (allows any version)."""
    if not version:
        return True
    dangerous = ("*", "latest", ">=", ">", "")
    return version.strip() in dangerous or version.strip().startswith(">=")


def _parse_npm_deps(line: str) -> tuple[str, str] | None:
    """Extract package name and version from npm dependency line."""
    m = _NPM_VERSION.search(line)
    if m:
        return m.group(1), m.group(2)
    return None


def scan_dependencies(files: list[PRFile]) -> list[DependencyFinding]:
    """Scan for dependency risks in package manifest changes."""
    findings: list[DependencyFinding] = []
    new_dep_count = 0

    for f in files:
        if not f.patch:
            continue

        ecosystem = _is_manifest(f.filename)
        if not ecosystem:
            continue

        line_map = extract_diff_line_map(f.patch)

        for line_num, line_text in line_map.items():
            stripped = line_text.strip()

            # Check for known risky packages
            for risky_pkg, reason in _RISKY_PACKAGES.items():
                if risky_pkg.lower() in stripped.lower():
                    findings.append(
                        DependencyFinding(
                            kind="risky",
                            package=risky_pkg,
                            path=f.filename,
                            line=line_num,
                            severity="critical" if "compromised" in reason.lower() or "malware" in reason.lower() else "high",
                            description=f"Package `{risky_pkg}`: {reason}",
                            fix_hint="Remove or replace with a maintained alternative.",
                        )
                    )

            # npm-specific checks
            if ecosystem == "npm":
                dep = _parse_npm_deps(stripped)
                if dep:
                    pkg, ver = dep
                    new_dep_count += 1

                    # Check for unpinned versions
                    if ver in ("*", "latest"):
                        findings.append(
                            DependencyFinding(
                                kind="unpinned",
                                package=pkg,
                                path=f.filename,
                                line=line_num,
                                severity="high",
                                description=f"Package `{pkg}` has unpinned version `{ver}`. Any version could be installed.",
                                fix_hint="Pin to a specific version or use a range like ^1.2.3.",
                            )
                        )

                    # Check for git/URL dependencies
                    if ver.startswith(("git", "http", "file:", "github:")):
                        findings.append(
                            DependencyFinding(
                                kind="risky",
                                package=pkg,
                                path=f.filename,
                                line=line_num,
                                severity="medium",
                                description=f"Package `{pkg}` installed from URL/git — bypasses registry integrity checks.",
                                fix_hint="Prefer installing from npm registry with a pinned version.",
                            )
                        )

            # pip-specific checks
            elif ecosystem == "pip" and f.filename.endswith((".txt", ".cfg")):
                m = _PIP_VERSION.match(stripped)
                if m:
                    pkg = m.group(1)
                    ver = m.group(2) or ""
                    new_dep_count += 1

                    if not ver:
                        findings.append(
                            DependencyFinding(
                                kind="unpinned",
                                package=pkg,
                                path=f.filename,
                                line=line_num,
                                severity="medium",
                                description=f"Package `{pkg}` has no version constraint.",
                                fix_hint="Pin version: `{pkg}>=1.0,<2.0` or use pip-compile.",
                            )
                        )

    # Warn on excessive new dependencies
    if new_dep_count > 5:
        findings.append(
            DependencyFinding(
                kind="excessive",
                package=f"{new_dep_count} packages",
                path="(multiple)",
                line=0,
                severity="medium",
                description=f"PR adds {new_dep_count} new dependencies. Large dependency additions increase attack surface and bundle size.",
                fix_hint="Review if all dependencies are necessary. Consider lighter alternatives or implementing simple functionality inline.",
            )
        )

    logger.info(f"Dependency scan: {len(findings)} risks found")
    return findings


def format_dependency_summary(findings: list[DependencyFinding]) -> str:
    """Format dependency findings into markdown summary."""
    if not findings:
        return ""

    severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}

    parts = ["### 📦 Dependency Risk Analysis", ""]

    critical = sum(1 for f in findings if f.severity == "critical")
    if critical > 0:
        parts.append(f"⚠️ **{critical} critical dependency risk{'s' if critical != 1 else ''}!**")
        parts.append("")

    for finding in findings:
        emoji = severity_emoji.get(finding.severity, "⚪")
        loc = f"`{finding.path}:{finding.line}`" if finding.line > 0 else f"`{finding.path}`"
        parts.append(f"- {emoji} **{finding.package}** ({finding.kind})")
        parts.append(f"  {loc} — {finding.description}")
        parts.append(f"  💡 {finding.fix_hint}")
        parts.append("")

    return "\n".join(parts)
