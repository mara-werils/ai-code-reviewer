"""License compliance checker — flags incompatible licenses in dependencies.

Zero LLM cost — pattern-based detection of license information in
package manifests and LICENSE files.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from src.github.client import PRFile
from src.review.analyzer import extract_diff_line_map

logger = logging.getLogger(__name__)


@dataclass
class LicenseFinding:
    """A license compliance issue."""

    package: str
    license: str
    path: str
    line: int
    severity: str
    risk: str  # copyleft, unknown, commercial_restriction, patent
    description: str
    fix_hint: str


# ── License classifications ──────────────────────────────────────────────────

# Copyleft licenses that require derivative works to be open-sourced
_COPYLEFT = {
    "GPL-2.0", "GPL-3.0", "AGPL-3.0", "LGPL-2.1", "LGPL-3.0",
    "GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0-only", "GPL-3.0-or-later",
    "AGPL-3.0-only", "AGPL-3.0-or-later",
    "MPL-2.0",  # Weak copyleft
    "EUPL-1.1", "EUPL-1.2",
    "OSL-3.0",
    "SSPL-1.0",  # Server Side Public License (MongoDB)
    "BUSL-1.1",  # Business Source License
}

# Permissive licenses (generally safe)
_PERMISSIVE = {
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC",
    "0BSD", "Unlicense", "CC0-1.0", "WTFPL", "Zlib",
    "PSF-2.0", "Python-2.0",
}

# Commercial restriction licenses
_COMMERCIAL_RESTRICTED = {
    "CC-BY-NC-4.0", "CC-BY-NC-SA-4.0", "CC-BY-NC-ND-4.0",
    "SSPL-1.0", "BUSL-1.1", "Elastic-2.0",
}

# License detection patterns
_LICENSE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("GPL-3.0", re.compile(r"GNU\s+General\s+Public\s+License.*(?:version\s+)?3", re.IGNORECASE)),
    ("GPL-2.0", re.compile(r"GNU\s+General\s+Public\s+License.*(?:version\s+)?2", re.IGNORECASE)),
    ("AGPL-3.0", re.compile(r"GNU\s+Affero\s+General\s+Public\s+License", re.IGNORECASE)),
    ("LGPL-3.0", re.compile(r"GNU\s+Lesser\s+General\s+Public\s+License.*3", re.IGNORECASE)),
    ("LGPL-2.1", re.compile(r"GNU\s+Lesser\s+General\s+Public\s+License.*2\.1", re.IGNORECASE)),
    ("MPL-2.0", re.compile(r"Mozilla\s+Public\s+License.*2", re.IGNORECASE)),
    ("Apache-2.0", re.compile(r"Apache\s+License.*2", re.IGNORECASE)),
    ("MIT", re.compile(r"\bMIT\s+License\b", re.IGNORECASE)),
    ("BSD-3-Clause", re.compile(r"BSD\s+3-Clause", re.IGNORECASE)),
    ("BSD-2-Clause", re.compile(r"BSD\s+2-Clause", re.IGNORECASE)),
    ("ISC", re.compile(r"\bISC\s+License\b", re.IGNORECASE)),
    ("SSPL-1.0", re.compile(r"Server\s+Side\s+Public\s+License", re.IGNORECASE)),
    ("BUSL-1.1", re.compile(r"Business\s+Source\s+License", re.IGNORECASE)),
    ("Elastic-2.0", re.compile(r"Elastic\s+License\s+2", re.IGNORECASE)),
]

# npm package.json license field
_NPM_LICENSE = re.compile(r'"license"\s*:\s*"([^"]+)"', re.IGNORECASE)

# Cargo.toml license field
_CARGO_LICENSE = re.compile(r'license\s*=\s*"([^"]+)"', re.IGNORECASE)

# pyproject.toml license
_PYPROJECT_LICENSE = re.compile(r'license\s*=\s*(?:"([^"]+)"|\{.*text\s*=\s*"([^"]+)")', re.IGNORECASE)


def _classify_license(license_id: str) -> tuple[str, str]:
    """Classify a license as copyleft, permissive, or restricted."""
    normalized = license_id.strip().upper()

    for cl in _COPYLEFT:
        if cl.upper() in normalized:
            return "copyleft", "high"

    for cr in _COMMERCIAL_RESTRICTED:
        if cr.upper() in normalized:
            return "commercial_restriction", "high"

    for pm in _PERMISSIVE:
        if pm.upper() in normalized:
            return "permissive", "info"

    return "unknown", "medium"


def scan_licenses(files: list[PRFile]) -> list[LicenseFinding]:
    """Scan for license compliance issues in PR."""
    findings: list[LicenseFinding] = []

    for f in files:
        if not f.patch:
            continue

        line_map = extract_diff_line_map(f.patch)
        filename_lower = f.filename.lower()

        # Check LICENSE files
        if "license" in filename_lower or "copying" in filename_lower:
            full_text = "\n".join(line_map.values())
            for license_id, pattern in _LICENSE_PATTERNS:
                if pattern.search(full_text):
                    risk, severity = _classify_license(license_id)
                    if risk != "permissive":
                        first_line = min(line_map.keys()) if line_map else 1
                        findings.append(
                            LicenseFinding(
                                package="(project)",
                                license=license_id,
                                path=f.filename,
                                line=first_line,
                                severity=severity,
                                risk=risk,
                                description=f"Project uses {license_id} license ({risk}).",
                                fix_hint=_get_license_hint(risk, license_id),
                            )
                        )
                    break

        # Check package.json
        if filename_lower.endswith("package.json"):
            for line_num, line_text in line_map.items():
                m = _NPM_LICENSE.search(line_text)
                if m:
                    license_id = m.group(1)
                    risk, severity = _classify_license(license_id)
                    if risk not in ("permissive",):
                        findings.append(
                            LicenseFinding(
                                package="(project)",
                                license=license_id,
                                path=f.filename,
                                line=line_num,
                                severity=severity,
                                risk=risk,
                                description=f"Package license `{license_id}` is {risk}.",
                                fix_hint=_get_license_hint(risk, license_id),
                            )
                        )

        # Check Cargo.toml
        if filename_lower.endswith("cargo.toml"):
            for line_num, line_text in line_map.items():
                m = _CARGO_LICENSE.search(line_text)
                if m:
                    license_id = m.group(1)
                    risk, severity = _classify_license(license_id)
                    if risk not in ("permissive",):
                        findings.append(
                            LicenseFinding(
                                package="(crate)",
                                license=license_id,
                                path=f.filename,
                                line=line_num,
                                severity=severity,
                                risk=risk,
                                description=f"Crate license `{license_id}` is {risk}.",
                                fix_hint=_get_license_hint(risk, license_id),
                            )
                        )

        # Check pyproject.toml
        if filename_lower.endswith("pyproject.toml"):
            for line_num, line_text in line_map.items():
                m = _PYPROJECT_LICENSE.search(line_text)
                if m:
                    license_id = m.group(1) or m.group(2)
                    if license_id:
                        risk, severity = _classify_license(license_id)
                        if risk not in ("permissive",):
                            findings.append(
                                LicenseFinding(
                                    package="(project)",
                                    license=license_id,
                                    path=f.filename,
                                    line=line_num,
                                    severity=severity,
                                    risk=risk,
                                    description=f"Project license `{license_id}` is {risk}.",
                                    fix_hint=_get_license_hint(risk, license_id),
                                )
                            )

    logger.info(f"License scan: {len(findings)} issues found")
    return findings


def _get_license_hint(risk: str, license_id: str) -> str:
    """Get a fix hint based on license risk type."""
    if risk == "copyleft":
        return (
            f"{license_id} requires derivative works to use the same license. "
            f"If your project is proprietary, consider an alternative with a permissive license (MIT, Apache-2.0)."
        )
    if risk == "commercial_restriction":
        return (
            f"{license_id} has commercial use restrictions. "
            f"Ensure your use case is permitted, or find an alternative."
        )
    if risk == "unknown":
        return "Could not determine license compatibility. Review manually before using in production."
    return ""


def format_license_summary(findings: list[LicenseFinding]) -> str:
    """Format license findings into markdown summary."""
    if not findings:
        return ""

    severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "info": "ℹ️"}

    parts = ["### ⚖️ License Compliance", ""]

    copyleft = [f for f in findings if f.risk == "copyleft"]
    if copyleft:
        parts.append("⚠️ **Copyleft license detected** — may require open-sourcing derivative works.")
        parts.append("")

    for finding in findings:
        emoji = severity_emoji.get(finding.severity, "⚪")
        parts.append(f"- {emoji} **{finding.license}** ({finding.risk}) in `{finding.path}:{finding.line}`")
        parts.append(f"  {finding.description}")
        parts.append("")

    return "\n".join(parts)
