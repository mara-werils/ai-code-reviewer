"""Database migration risk analyzer — detects dangerous migration patterns.

Zero LLM cost — pattern-based analysis on migration files.
Detects: destructive operations, lock-heavy changes, missing rollbacks,
data loss risks, and production safety issues.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.github.client import PRFile
from src.review.analyzer import extract_diff_line_map

logger = logging.getLogger(__name__)


@dataclass
class MigrationRisk:
    """A risk found in a database migration."""

    id: str
    name: str
    severity: str  # critical, high, medium, low
    description: str
    fix_hint: str
    path: str
    line: int
    matched_text: str


@dataclass
class MigrationRule:
    id: str
    name: str
    pattern: str
    severity: str
    description: str
    fix_hint: str
    flags: int = re.IGNORECASE


# ── Migration file detection ─────────────────────────────────────────────────

_MIGRATION_PATTERNS = (
    "migration",
    "migrate",
    "alembic",
    "flyway",
    "liquibase",
    "db/migrate",
    "migrations/",
    "schema.sql",
    "changeset",
    ".up.sql",
    ".down.sql",
)


def _is_migration_file(path: str) -> bool:
    lower = path.lower()
    return any(p in lower for p in _MIGRATION_PATTERNS) or lower.endswith(".sql")


# ── Risk rules ───────────────────────────────────────────────────────────────

MIGRATION_RULES: list[MigrationRule] = [
    MigrationRule(
        id="MIG001",
        name="DROP TABLE",
        pattern=r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(\w+)",
        severity="critical",
        description="Dropping a table permanently deletes all data. This is irreversible in production.",
        fix_hint="Consider renaming the table first (with a deprecation period), or use soft-delete. Always backup before dropping.",
    ),
    MigrationRule(
        id="MIG002",
        name="DROP COLUMN",
        pattern=r"ALTER\s+TABLE\s+\w+\s+DROP\s+COLUMN",
        severity="critical",
        description="Dropping a column deletes data permanently. Running applications may still reference it.",
        fix_hint="Deploy code changes first (stop reading the column), then drop it in a follow-up migration.",
    ),
    MigrationRule(
        id="MIG003",
        name="TRUNCATE TABLE",
        pattern=r"TRUNCATE\s+(?:TABLE\s+)?(\w+)",
        severity="critical",
        description="TRUNCATE deletes all rows from a table instantly and cannot be rolled back in some databases.",
        fix_hint="Use DELETE with WHERE clause for selective removal, or ensure backup exists.",
    ),
    MigrationRule(
        id="MIG004",
        name="Column Type Change",
        pattern=r"ALTER\s+TABLE\s+\w+\s+(?:ALTER|MODIFY)\s+COLUMN\s+\w+\s+(?:TYPE\s+)?(\w+)",
        severity="high",
        description="Changing column type can cause data loss or lock the table for extended periods on large tables.",
        fix_hint="Add a new column, migrate data in batches, then drop the old column. Use pg_repack or pt-online-schema-change for zero-downtime.",
    ),
    MigrationRule(
        id="MIG005",
        name="NOT NULL Without Default",
        pattern=r"(?:ADD|ALTER)\s+(?:COLUMN\s+)?\w+\s+\w+\s+NOT\s+NULL(?!\s+DEFAULT)",
        severity="high",
        description="Adding NOT NULL constraint without DEFAULT will fail if existing rows have NULL values.",
        fix_hint="Add DEFAULT value, or first backfill NULLs, then add the constraint.",
    ),
    MigrationRule(
        id="MIG006",
        name="Large Table Lock (ADD INDEX without CONCURRENTLY)",
        pattern=r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?!CONCURRENTLY)",
        severity="high",
        description="CREATE INDEX without CONCURRENTLY locks the table for writes during index creation.",
        fix_hint="Use CREATE INDEX CONCURRENTLY (PostgreSQL) to avoid blocking writes.",
    ),
    MigrationRule(
        id="MIG007",
        name="Rename Table",
        pattern=r"(?:ALTER\s+TABLE|RENAME\s+TABLE)\s+\w+\s+(?:RENAME\s+TO|TO)\s+\w+",
        severity="high",
        description="Renaming a table breaks all queries referencing the old name. Requires coordinated deploy.",
        fix_hint="Create a view with the old name pointing to the new table during transition period.",
    ),
    MigrationRule(
        id="MIG008",
        name="ENUM Modification",
        pattern=r"ALTER\s+TYPE\s+\w+\s+(?:ADD|RENAME)\s+VALUE",
        severity="medium",
        description="Modifying ENUM types can be tricky and varies by database. Cannot be done in a transaction (PostgreSQL).",
        fix_hint="Ensure this runs outside a transaction block. Consider using a lookup table instead of ENUM.",
    ),
    MigrationRule(
        id="MIG009",
        name="Raw Data Manipulation",
        pattern=r"(?:UPDATE|DELETE\s+FROM)\s+\w+\s+(?:SET|WHERE)",
        severity="medium",
        description="Data manipulation in migrations can be slow on large tables and hard to reverse.",
        fix_hint="Run data migrations as separate scripts with batching, progress logging, and dry-run mode.",
    ),
    MigrationRule(
        id="MIG010",
        name="Foreign Key Without Index",
        pattern=r"(?:ADD\s+)?(?:CONSTRAINT\s+\w+\s+)?FOREIGN\s+KEY\s*\((\w+)\)\s+REFERENCES",
        severity="medium",
        description="Foreign key without matching index causes full table scans on JOINs and cascading deletes.",
        fix_hint="Create an index on the foreign key column before adding the constraint.",
    ),
    MigrationRule(
        id="MIG011",
        name="Multiple Schema Changes",
        pattern=r"(?:ALTER\s+TABLE\s+\w+\s+(?:ADD|DROP|ALTER|MODIFY)){2,}",
        severity="medium",
        description="Multiple schema changes in one statement. Each ALTER can lock the table.",
        fix_hint="Split into separate ALTER statements. Consider using batched DDL tools.",
    ),
    MigrationRule(
        id="MIG012",
        name="No Transaction Wrapper",
        pattern=r"^(?!.*(?:BEGIN|START\s+TRANSACTION)).*(?:ALTER\s+TABLE|DROP|CREATE)",
        severity="low",
        description="Schema change without explicit transaction wrapper. Partial failures leave schema inconsistent.",
        fix_hint="Wrap related DDL in BEGIN/COMMIT (where supported by the database).",
    ),
]


def scan_migration_risks(files: list[PRFile]) -> list[MigrationRisk]:
    """Scan migration files for risks."""
    findings: list[MigrationRisk] = []

    for f in files:
        if not f.patch:
            continue
        if not _is_migration_file(f.filename):
            continue

        line_map = extract_diff_line_map(f.patch)

        for line_num, line_text in line_map.items():
            for rule in MIGRATION_RULES:
                try:
                    if re.search(rule.pattern, line_text, rule.flags):
                        findings.append(
                            MigrationRisk(
                                id=rule.id,
                                name=rule.name,
                                severity=rule.severity,
                                description=rule.description,
                                fix_hint=rule.fix_hint,
                                path=f.filename,
                                line=line_num,
                                matched_text=line_text.strip()[:200],
                            )
                        )
                except re.error:
                    continue

    logger.info(f"Migration risk scan: {len(findings)} risks found")
    return findings


def format_migration_summary(findings: list[MigrationRisk]) -> str:
    """Format migration risks into markdown summary."""
    if not findings:
        return ""

    severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}

    parts = ["### 🗄️ Migration Risk Analysis", ""]
    total = len(findings)
    critical = sum(1 for f in findings if f.severity == "critical")
    high = sum(1 for f in findings if f.severity == "high")

    if critical > 0:
        parts.append(f"⚠️ **{critical} CRITICAL risk{'s' if critical != 1 else ''} detected!** Manual review required.")
        parts.append("")

    parts.append(f"Found **{total}** migration risk{'s' if total != 1 else ''}:")
    parts.append("")

    for finding in sorted(findings, key=lambda f: ["critical", "high", "medium", "low"].index(f.severity)):
        emoji = severity_emoji.get(finding.severity, "⚪")
        parts.append(
            f"- {emoji} **{finding.name}** ({finding.id}) in `{finding.path}:{finding.line}`"
        )
        parts.append(f"  {finding.description}")
        parts.append(f"  💡 {finding.fix_hint}")
        parts.append("")

    return "\n".join(parts)
