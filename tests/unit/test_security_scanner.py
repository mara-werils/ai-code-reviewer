"""Tests for the built-in security scanner."""

from __future__ import annotations

from src.github.client import PRFile
from src.review.security import (
    SecurityFinding,
    SecurityRule,
    format_security_findings,
    format_security_summary,
    scan_diff,
)


def _make_file(filename: str, patch: str) -> PRFile:
    return PRFile(filename=filename, status="modified", additions=1, deletions=0, patch=patch)


# ── SQL Injection ────────────────────────────────────────────────────────────

class TestSQLInjection:
    def test_fstring_in_execute(self) -> None:
        f = _make_file("src/db.py", '@@ -1,3 +1,4 @@\n ctx\n+cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC001" for r in findings)

    def test_parameterized_query_safe(self) -> None:
        f = _make_file("src/db.py", '@@ -1,3 +1,4 @@\n ctx\n+cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))')
        findings = scan_diff([f])
        assert not any(r.rule_id == "SEC001" for r in findings)

    def test_go_sql_injection(self) -> None:
        f = _make_file("handler.go", '@@ -1,3 +1,4 @@\n ctx\n+db.Query(fmt.Sprintf("SELECT * FROM users WHERE id = %s", id))')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC100" for r in findings)


# ── XSS ──────────────────────────────────────────────────────────────────────

class TestXSS:
    def test_innerhtml(self) -> None:
        f = _make_file("app.js", '@@ -1,3 +1,4 @@\n ctx\n+element.innerHTML = userInput;')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC010" for r in findings)

    def test_dangerously_set_inner_html(self) -> None:
        f = _make_file("App.tsx", '@@ -1,3 +1,4 @@\n ctx\n+<div dangerouslySetInnerHTML={{ __html: data }} />')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC011" for r in findings)

    def test_mark_safe(self) -> None:
        f = _make_file("views.py", '@@ -1,3 +1,4 @@\n ctx\n+return mark_safe(user_content)')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC012" for r in findings)


# ── Hardcoded Secrets ────────────────────────────────────────────────────────

class TestSecrets:
    def test_api_key(self) -> None:
        f = _make_file("config.py", '@@ -1,3 +1,4 @@\n ctx\n+api_key = "sk_live_1234567890abcdef1234"')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC020" for r in findings)

    def test_password(self) -> None:
        f = _make_file("settings.py", '@@ -1,3 +1,4 @@\n ctx\n+password = "super_secret_pass"')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC021" for r in findings)

    def test_password_in_test_file_skipped(self) -> None:
        f = _make_file("tests/test_auth.py", '@@ -1,3 +1,4 @@\n ctx\n+password = "test_password_123"')
        findings = scan_diff([f])
        assert not any(r.rule_id == "SEC021" for r in findings)

    def test_aws_key(self) -> None:
        f = _make_file("deploy.py", '@@ -1,3 +1,4 @@\n ctx\n+aws_access_key_id = "AKIAIOSFODNN7EXAMPLE"')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC023" for r in findings)

    def test_private_key(self) -> None:
        f = _make_file("config.py", '@@ -1,3 +1,4 @@\n ctx\n+-----BEGIN RSA PRIVATE KEY-----')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC024" for r in findings)

    def test_private_key_in_test_skipped(self) -> None:
        f = _make_file("tests/test_crypto.py", '@@ -1,3 +1,4 @@\n ctx\n+-----BEGIN RSA PRIVATE KEY-----')
        findings = scan_diff([f])
        assert not any(r.rule_id == "SEC024" for r in findings)


# ── Command Injection ────────────────────────────────────────────────────────

class TestCommandInjection:
    def test_os_system_fstring(self) -> None:
        f = _make_file("util.py", '@@ -1,3 +1,4 @@\n ctx\n+os.system(f"rm -rf {user_path}")')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC040" for r in findings)

    def test_shell_true(self) -> None:
        f = _make_file("deploy.py", '@@ -1,3 +1,4 @@\n ctx\n+subprocess.run(cmd, shell=True)')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC041" for r in findings)

    def test_eval(self) -> None:
        f = _make_file("handler.py", '@@ -1,3 +1,4 @@\n ctx\n+result = eval(user_input)')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC042" for r in findings)


# ── Insecure Crypto ──────────────────────────────────────────────────────────

class TestCrypto:
    def test_md5(self) -> None:
        f = _make_file("auth.py", '@@ -1,3 +1,4 @@\n ctx\n+hash = hashlib.md5(password.encode())')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC050" for r in findings)

    def test_math_random(self) -> None:
        f = _make_file("src/token.js", '@@ -1,3 +1,4 @@\n ctx\n+const token = Math.random().toString(36);')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC051" for r in findings)

    def test_math_random_in_test_skipped(self) -> None:
        f = _make_file("tests/test_util.js", '@@ -1,3 +1,4 @@\n ctx\n+const x = Math.random();')
        findings = scan_diff([f])
        assert not any(r.rule_id == "SEC051" for r in findings)


# ── Deserialization ──────────────────────────────────────────────────────────

class TestDeserialization:
    def test_pickle_load(self) -> None:
        f = _make_file("cache.py", '@@ -1,3 +1,4 @@\n ctx\n+data = pickle.loads(payload)')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC070" for r in findings)

    def test_yaml_unsafe_load(self) -> None:
        f = _make_file("config.py", '@@ -1,3 +1,4 @@\n ctx\n+data = yaml.load(content)')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC071" for r in findings)

    def test_yaml_safe_load_ok(self) -> None:
        f = _make_file("config.py", '@@ -1,3 +1,4 @@\n ctx\n+data = yaml.safe_load(content)')
        findings = scan_diff([f])
        assert not any(r.rule_id == "SEC071" for r in findings)


# ── Auth Issues ──────────────────────────────────────────────────────────────

class TestAuth:
    def test_cors_wildcard(self) -> None:
        f = _make_file("app.py", '@@ -1,3 +1,4 @@\n ctx\n+allow_origins = "*"')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC081" for r in findings)

    def test_debug_true(self) -> None:
        f = _make_file("app.py", '@@ -1,3 +1,4 @@\n ctx\n+DEBUG = True')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC082" for r in findings)

    def test_debug_in_test_skipped(self) -> None:
        f = _make_file("tests/conftest.py", '@@ -1,3 +1,4 @@\n ctx\n+DEBUG = True')
        findings = scan_diff([f])
        assert not any(r.rule_id == "SEC082" for r in findings)


# ── Go-specific ──────────────────────────────────────────────────────────────

class TestGoSpecific:
    def test_tls_skip_verify(self) -> None:
        f = _make_file("client.go", '@@ -1,3 +1,4 @@\n ctx\n+InsecureSkipVerify: true,')
        findings = scan_diff([f])
        assert any(r.rule_id == "SEC101" for r in findings)

    def test_tls_skip_verify_not_in_python(self) -> None:
        f = _make_file("client.py", '@@ -1,3 +1,4 @@\n ctx\n+InsecureSkipVerify: true,')
        findings = scan_diff([f])
        assert not any(r.rule_id == "SEC101" for r in findings)


# ── Scanner behavior ────────────────────────────────────────────────────────

class TestScannerBehavior:
    def test_disabled_returns_empty(self) -> None:
        f = _make_file("db.py", '@@ -1,3 +1,4 @@\n ctx\n+cursor.execute(f"SELECT {x}")')
        assert scan_diff([f], enabled=False) == []

    def test_no_files(self) -> None:
        assert scan_diff([]) == []

    def test_no_patch(self) -> None:
        f = PRFile(filename="bin.dat", status="modified", additions=0, deletions=0, patch="")
        assert scan_diff([f]) == []

    def test_sorted_by_severity(self) -> None:
        files = [
            _make_file("a.py", '@@ -1,3 +1,4 @@\n ctx\n+allow_origins = "*"'),  # medium
            _make_file("b.py", '@@ -1,3 +1,4 @@\n ctx\n+api_key = "sk_live_abcdefghij1234567890"'),  # critical
        ]
        findings = scan_diff(files)
        if len(findings) >= 2:
            assert findings[0].severity == "critical"

    def test_language_filter(self) -> None:
        # Go-specific rule should not fire on Python files
        rule = SecurityRule(
            id="TEST", name="Go only", pattern="fmt.Sprintf",
            severity="high", category="test", description="test",
            languages=["go"],
        )
        f = _make_file("main.py", '@@ -1,3 +1,4 @@\n ctx\n+fmt.Sprintf("test")')
        findings = scan_diff([f], rules=[rule])
        assert len(findings) == 0

    def test_custom_rules(self) -> None:
        rule = SecurityRule(
            id="CUSTOM001", name="No console.log", pattern=r"console\.log",
            severity="low", category="quality", description="Remove console.log",
        )
        f = _make_file("app.js", '@@ -1,3 +1,4 @@\n ctx\n+console.log("debug")')
        findings = scan_diff([f], rules=[rule])
        assert len(findings) == 1
        assert findings[0].rule_id == "CUSTOM001"


# ── Formatting ───────────────────────────────────────────────────────────────

class TestFormatFindings:
    def test_format_comment(self) -> None:
        findings = [
            SecurityFinding(
                rule_id="SEC001", rule_name="SQL Injection",
                severity="critical", category="injection",
                description="SQL query with f-string.",
                fix_hint="Use parameterized queries.",
                path="db.py", line=42, matched_text='execute(f"SELECT',
            ),
        ]
        comments = format_security_findings(findings)
        assert len(comments) == 1
        assert "[CRITICAL]" in comments[0]["body"]
        assert "SEC001" in comments[0]["body"]
        assert "parameterized" in comments[0]["body"]
        assert comments[0]["path"] == "db.py"
        assert comments[0]["line"] == 42

    def test_format_empty(self) -> None:
        assert format_security_findings([]) == []


class TestFormatSummary:
    def test_summary(self) -> None:
        findings = [
            SecurityFinding("SEC001", "SQLi", "critical", "injection", "", "", "a.py", 1, ""),
            SecurityFinding("SEC010", "XSS", "high", "xss", "", "", "b.js", 2, ""),
            SecurityFinding("SEC020", "Secret", "critical", "secrets", "", "", "c.py", 3, ""),
        ]
        summary = format_security_summary(findings)
        assert "3 security issues" in summary
        assert "CRITICAL" in summary
        assert "HIGH" in summary
        assert "injection" in summary

    def test_empty_summary(self) -> None:
        assert format_security_summary([]) == ""
