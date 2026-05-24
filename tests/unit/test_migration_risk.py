"""Tests for migration risk analyzer."""

from src.github.client import PRFile
from src.review.migration_risk import (
    format_migration_summary,
    scan_migration_risks,
)


def _make_file(filename: str, patch: str) -> PRFile:
    return PRFile(
        filename=filename,
        status="modified",
        additions=3,
        deletions=0,
        patch=patch,
    )


class TestMigrationRisk:
    def test_detects_drop_table(self):
        patch = """@@ -1,3 +1,5 @@
+DROP TABLE IF EXISTS users;
"""
        files = [_make_file("migrations/001.sql", patch)]
        risks = scan_migration_risks(files)
        assert any(r.id == "MIG001" for r in risks)

    def test_detects_drop_column(self):
        patch = """@@ -1,3 +1,5 @@
+ALTER TABLE users DROP COLUMN email;
"""
        files = [_make_file("db/migrations/002.sql", patch)]
        risks = scan_migration_risks(files)
        assert any(r.id == "MIG002" for r in risks)

    def test_detects_not_null_without_default(self):
        patch = """@@ -1,3 +1,5 @@
+ALTER TABLE users ADD COLUMN age INTEGER NOT NULL;
"""
        files = [_make_file("alembic/versions/003.sql", patch)]
        risks = scan_migration_risks(files)
        assert any(r.id == "MIG005" for r in risks)

    def test_skips_non_migration_files(self):
        patch = """@@ -1,3 +1,5 @@
+DROP TABLE users;
"""
        files = [_make_file("src/app.py", patch)]
        risks = scan_migration_risks(files)
        assert len(risks) == 0

    def test_detects_create_index_without_concurrently(self):
        patch = """@@ -1,3 +1,5 @@
+CREATE INDEX idx_users_email ON users(email);
"""
        files = [_make_file("migrations/004.sql", patch)]
        risks = scan_migration_risks(files)
        assert any(r.id == "MIG006" for r in risks)

    def test_format_empty(self):
        assert format_migration_summary([]) == ""

    def test_format_with_risks(self):
        patch = """@@ -1,3 +1,5 @@
+DROP TABLE users;
"""
        files = [_make_file("migrations/005.sql", patch)]
        risks = scan_migration_risks(files)
        summary = format_migration_summary(risks)
        assert "Migration Risk" in summary
