"""Tests for the declarative review rules engine."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from src.github.client import PRFile
from src.review.rules import (
    Rule,
    RulesConfig,
    RuleViolation,
    _file_matches_glob,
    evaluate_rules,
    format_rule_violations,
    load_rules,
)


class TestRule:
    def test_default_severity(self) -> None:
        rule = Rule(name="test")
        assert rule.severity == "warning"

    def test_invalid_severity_defaults(self) -> None:
        rule = Rule(name="test", severity="banana")
        assert rule.severity == "warning"

    def test_valid_severities(self) -> None:
        for sev in ("critical", "warning", "suggestion", "info"):
            rule = Rule(name="test", severity=sev)
            assert rule.severity == sev


class TestFileMatchesGlob:
    def test_exact_match(self) -> None:
        assert _file_matches_glob("src/api.py", "src/api.py") is True

    def test_wildcard(self) -> None:
        assert _file_matches_glob("src/api.py", "src/*.py") is True

    def test_double_star(self) -> None:
        assert _file_matches_glob("src/deep/nested/file.py", "src/**/*.py") is True

    def test_no_match(self) -> None:
        assert _file_matches_glob("src/api.py", "tests/*.py") is False


class TestLoadRules:
    def test_no_file(self, tmp_path: Path) -> None:
        config = load_rules(tmp_path / "nonexistent.yml")
        assert config.rules == []

    def test_empty_file(self, tmp_path: Path) -> None:
        rules_file = tmp_path / ".pr-reviewer-rules.yml"
        rules_file.write_text("")
        config = load_rules(rules_file)
        assert config.rules == []

    def test_pattern_rule(self, tmp_path: Path) -> None:
        rules_file = tmp_path / ".pr-reviewer-rules.yml"
        rules_file.write_text(dedent("""\
            rules:
              - name: no-raw-sql
                pattern: "execute\\\\(.*SELECT|INSERT|UPDATE|DELETE"
                severity: critical
                message: "Use ORM instead of raw SQL"
        """))
        config = load_rules(rules_file)
        assert len(config.rules) == 1
        assert config.rules[0].name == "no-raw-sql"
        assert config.rules[0].severity == "critical"
        assert config.rules[0].pattern != ""

    def test_file_match_rule_with_when(self, tmp_path: Path) -> None:
        rules_file = tmp_path / ".pr-reviewer-rules.yml"
        rules_file.write_text(dedent("""\
            rules:
              - name: require-tests-for-api
                when:
                  files_match: "src/api/**/*.py"
                  no_files_match: "tests/api/**/*.py"
                severity: warning
                message: "API changes require test coverage"
        """))
        config = load_rules(rules_file)
        assert len(config.rules) == 1
        assert config.rules[0].files_match == "src/api/**/*.py"
        assert config.rules[0].no_files_match == "tests/api/**/*.py"

    def test_multiple_rules(self, tmp_path: Path) -> None:
        rules_file = tmp_path / ".pr-reviewer-rules.yml"
        rules_file.write_text(dedent("""\
            rules:
              - name: rule1
                pattern: "TODO"
                severity: info
                message: "Found TODO"
              - name: rule2
                pattern: "FIXME"
                severity: warning
                message: "Found FIXME"
        """))
        config = load_rules(rules_file)
        assert len(config.rules) == 2

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        rules_file = tmp_path / ".pr-reviewer-rules.yml"
        rules_file.write_text("{{invalid yaml: [")
        config = load_rules(rules_file)
        assert config.rules == []

    def test_rules_not_list(self, tmp_path: Path) -> None:
        rules_file = tmp_path / ".pr-reviewer-rules.yml"
        rules_file.write_text("rules: not-a-list\n")
        config = load_rules(rules_file)
        assert config.rules == []

    def test_skips_entries_without_name(self, tmp_path: Path) -> None:
        rules_file = tmp_path / ".pr-reviewer-rules.yml"
        rules_file.write_text(dedent("""\
            rules:
              - pattern: "TODO"
                severity: info
              - name: valid-rule
                pattern: "FIXME"
                message: "Fix me"
        """))
        config = load_rules(rules_file)
        assert len(config.rules) == 1
        assert config.rules[0].name == "valid-rule"

    def test_include_exclude_files(self, tmp_path: Path) -> None:
        rules_file = tmp_path / ".pr-reviewer-rules.yml"
        rules_file.write_text(dedent("""\
            rules:
              - name: no-console-log
                pattern: "console\\\\.log"
                severity: warning
                message: "Remove console.log"
                include_files: "src/**/*.ts"
                exclude_files: "src/**/*.test.ts"
        """))
        config = load_rules(rules_file)
        assert config.rules[0].include_files == "src/**/*.ts"
        assert config.rules[0].exclude_files == "src/**/*.test.ts"


class TestEvaluatePatternRules:
    def test_matches_added_line(self) -> None:
        rule = Rule(
            name="no-todo",
            pattern="TODO",
            severity="info",
            message="Found TODO comment",
        )
        files = [
            PRFile(
                filename="src/api.py",
                status="modified",
                additions=2,
                deletions=0,
                patch="@@ -10,6 +10,8 @@\n context\n+# TODO: fix this\n+some_code()",
            ),
        ]
        violations = evaluate_rules(RulesConfig(rules=[rule]), files)
        assert len(violations) == 1
        assert violations[0].rule_name == "no-todo"
        assert violations[0].path == "src/api.py"
        assert violations[0].line == 11
        assert "TODO" in violations[0].matched_text

    def test_no_match(self) -> None:
        rule = Rule(name="no-todo", pattern="TODO", message="Found TODO")
        files = [
            PRFile(
                filename="src/api.py",
                status="modified",
                additions=1,
                deletions=0,
                patch="@@ -10,6 +10,7 @@\n context\n+clean_code()",
            ),
        ]
        violations = evaluate_rules(RulesConfig(rules=[rule]), files)
        assert len(violations) == 0

    def test_include_files_filter(self) -> None:
        rule = Rule(
            name="no-print",
            pattern="print\\(",
            message="No print()",
            include_files="src/**/*.py",
        )
        files = [
            PRFile(
                filename="tests/test_api.py",
                status="modified",
                additions=1,
                deletions=0,
                patch="@@ -1,3 +1,4 @@\n context\n+print('debug')",
            ),
            PRFile(
                filename="src/api.py",
                status="modified",
                additions=1,
                deletions=0,
                patch="@@ -1,3 +1,4 @@\n context\n+print('debug')",
            ),
        ]
        violations = evaluate_rules(RulesConfig(rules=[rule]), files)
        assert len(violations) == 1
        assert violations[0].path == "src/api.py"

    def test_exclude_files_filter(self) -> None:
        rule = Rule(
            name="no-print",
            pattern="print\\(",
            message="No print()",
            exclude_files="tests/**",
        )
        files = [
            PRFile(
                filename="tests/test_api.py",
                status="modified",
                additions=1,
                deletions=0,
                patch="@@ -1,3 +1,4 @@\n context\n+print('debug')",
            ),
            PRFile(
                filename="src/api.py",
                status="modified",
                additions=1,
                deletions=0,
                patch="@@ -1,3 +1,4 @@\n context\n+print('debug')",
            ),
        ]
        violations = evaluate_rules(RulesConfig(rules=[rule]), files)
        assert len(violations) == 1
        assert violations[0].path == "src/api.py"

    def test_invalid_regex(self) -> None:
        rule = Rule(name="bad-regex", pattern="[invalid", message="oops")
        files = [
            PRFile(
                filename="f.py", status="added", additions=1, deletions=0,
                patch="@@ -0,0 +1 @@\n+code",
            ),
        ]
        violations = evaluate_rules(RulesConfig(rules=[rule]), files)
        assert len(violations) == 0

    def test_multiple_matches_in_file(self) -> None:
        rule = Rule(name="no-todo", pattern="TODO", severity="info", message="TODO found")
        files = [
            PRFile(
                filename="src/app.py",
                status="modified",
                additions=3,
                deletions=0,
                patch="@@ -1,3 +1,6 @@\n ctx\n+# TODO: first\n+code()\n+# TODO: second",
            ),
        ]
        violations = evaluate_rules(RulesConfig(rules=[rule]), files)
        assert len(violations) == 2


class TestEvaluateFileMatchRules:
    def test_trigger_when_no_counter_files(self) -> None:
        rule = Rule(
            name="require-tests",
            files_match="src/api/*.py",
            no_files_match="tests/api/*.py",
            severity="warning",
            message="API changes need tests",
        )
        files = [
            PRFile(filename="src/api/users.py", status="modified", additions=10, deletions=0, patch=""),
        ]
        violations = evaluate_rules(RulesConfig(rules=[rule]), files)
        assert len(violations) == 1
        assert violations[0].rule_name == "require-tests"

    def test_no_trigger_when_counter_files_present(self) -> None:
        rule = Rule(
            name="require-tests",
            files_match="src/api/*.py",
            no_files_match="tests/api/*.py",
            severity="warning",
            message="API changes need tests",
        )
        files = [
            PRFile(filename="src/api/users.py", status="modified", additions=10, deletions=0, patch=""),
            PRFile(filename="tests/api/test_users.py", status="added", additions=20, deletions=0, patch=""),
        ]
        violations = evaluate_rules(RulesConfig(rules=[rule]), files)
        assert len(violations) == 0

    def test_no_trigger_when_no_matching_files(self) -> None:
        rule = Rule(
            name="require-tests",
            files_match="src/api/*.py",
            no_files_match="tests/api/*.py",
            severity="warning",
            message="API changes need tests",
        )
        files = [
            PRFile(filename="docs/readme.md", status="modified", additions=5, deletions=0, patch=""),
        ]
        violations = evaluate_rules(RulesConfig(rules=[rule]), files)
        assert len(violations) == 0

    def test_files_match_without_no_files_match(self) -> None:
        rule = Rule(
            name="api-changed",
            files_match="src/api/*.py",
            severity="info",
            message="API files were changed",
        )
        files = [
            PRFile(filename="src/api/users.py", status="modified", additions=5, deletions=0, patch=""),
        ]
        violations = evaluate_rules(RulesConfig(rules=[rule]), files)
        assert len(violations) == 1


class TestFormatRuleViolations:
    def test_pattern_violation(self) -> None:
        violations = [
            RuleViolation(
                rule_name="no-raw-sql",
                severity="critical",
                message="Use ORM instead of raw SQL",
                path="src/db.py",
                line=42,
                matched_text='execute("SELECT * FROM users")',
            ),
        ]
        comments = format_rule_violations(violations)
        assert len(comments) == 1
        assert comments[0]["path"] == "src/db.py"
        assert comments[0]["line"] == 42
        assert "[CRITICAL]" in comments[0]["body"]
        assert "no-raw-sql" in comments[0]["body"]
        assert "Matched:" in comments[0]["body"]

    def test_file_match_violation(self) -> None:
        violations = [
            RuleViolation(
                rule_name="require-tests",
                severity="warning",
                message="API changes need tests",
                path="src/api/users.py",
                line=0,
                matched_text="",
            ),
        ]
        comments = format_rule_violations(violations)
        assert len(comments) == 1
        assert "[WARNING]" in comments[0]["body"]
        assert "Matched:" not in comments[0]["body"]

    def test_empty_violations(self) -> None:
        assert format_rule_violations([]) == []


class TestEvaluateEmpty:
    def test_no_rules(self) -> None:
        files = [
            PRFile(filename="src/api.py", status="modified", additions=5, deletions=0, patch="@@ +1 @@\n+code"),
        ]
        violations = evaluate_rules(RulesConfig(), files)
        assert violations == []

    def test_no_files(self) -> None:
        rule = Rule(name="no-todo", pattern="TODO", message="Found TODO")
        violations = evaluate_rules(RulesConfig(rules=[rule]), [])
        assert violations == []
