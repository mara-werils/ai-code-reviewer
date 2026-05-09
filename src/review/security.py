"""Built-in security scanner (SAST-lite).

Pattern-based static analysis that runs on every PR diff.
Detects OWASP Top 10 vulnerabilities, hardcoded secrets,
and language-specific security anti-patterns.

Zero LLM cost — all rules are regex-based, instant.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.github.client import PRFile
from src.review.analyzer import extract_diff_line_map

logger = logging.getLogger(__name__)


@dataclass
class SecurityRule:
    """A single security scanning rule."""

    id: str
    name: str
    pattern: str
    severity: str  # critical, high, medium, low
    category: str  # injection, secrets, xss, auth, crypto, etc.
    description: str
    fix_hint: str = ""
    languages: list[str] = field(default_factory=list)  # empty = all languages
    exclude_test_files: bool = True


@dataclass
class SecurityFinding:
    """A vulnerability found by the scanner."""

    rule_id: str
    rule_name: str
    severity: str
    category: str
    description: str
    fix_hint: str
    path: str
    line: int
    matched_text: str


# ── File extension → language mapping ────────────────────────────────────────

_EXT_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".rs": "rust",
    ".kt": "kotlin",
    ".swift": "swift",
    ".sh": "shell",
    ".bash": "shell",
    ".sql": "sql",
    ".yaml": "yaml",
    ".yml": "yaml",
}

_TEST_PATTERNS = ("test_", "_test.", ".test.", ".spec.", "tests/", "__tests__/")


def _detect_lang(path: str) -> str:
    for ext, lang in _EXT_LANG.items():
        if path.endswith(ext):
            return lang
    return ""


def _is_test_file(path: str) -> bool:
    lower = path.lower()
    return any(p in lower for p in _TEST_PATTERNS)


# ── Security rules ──────────────────────────────────────────────────────────

SECURITY_RULES: list[SecurityRule] = [
    # ── SQL Injection ────────────────────────────────────────────────────
    SecurityRule(
        id="SEC001",
        name="SQL Injection (string formatting)",
        pattern=r"""(?:execute|cursor\.execute|query|raw|rawQuery)\s*\(\s*(?:f[\"']|[\"'].*\{|[\"'].*\+\s*\w)""",
        severity="critical",
        category="injection",
        description="SQL query built with string formatting/concatenation. This is vulnerable to SQL injection.",
        fix_hint="Use parameterized queries: `cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))`",
        languages=["python", "javascript", "typescript", "ruby", "php"],
    ),
    SecurityRule(
        id="SEC002",
        name="SQL Injection (ORM raw)",
        pattern=r"""\.(?:raw|execute_sql|from_raw)\s*\(\s*f[\"']""",
        severity="critical",
        category="injection",
        description="Raw SQL in ORM query using f-string. Vulnerable to SQL injection.",
        fix_hint="Use ORM query builders or parameterized raw queries.",
        languages=["python"],
    ),

    # ── XSS ──────────────────────────────────────────────────────────────
    SecurityRule(
        id="SEC010",
        name="Cross-Site Scripting (innerHTML)",
        pattern=r"""\.innerHTML\s*=\s*(?!['"][^'"]*['"]$)""",
        severity="high",
        category="xss",
        description="Setting innerHTML with dynamic content enables XSS attacks.",
        fix_hint="Use `textContent` for text, or sanitize with DOMPurify before setting innerHTML.",
        languages=["javascript", "typescript"],
    ),
    SecurityRule(
        id="SEC011",
        name="Cross-Site Scripting (dangerouslySetInnerHTML)",
        pattern=r"""dangerouslySetInnerHTML\s*=\s*\{""",
        severity="high",
        category="xss",
        description="dangerouslySetInnerHTML bypasses React's XSS protection.",
        fix_hint="Avoid dangerouslySetInnerHTML. If necessary, sanitize with DOMPurify.",
        languages=["javascript", "typescript"],
    ),
    SecurityRule(
        id="SEC012",
        name="Cross-Site Scripting (template unescaped)",
        pattern=r"""\{\{\{.*\}\}\}|\{%\s*autoescape\s+false|mark_safe\(|safe\s*\||\|safe\b""",
        severity="high",
        category="xss",
        description="Unescaped template output can lead to XSS.",
        fix_hint="Use escaped output. Avoid mark_safe() and |safe unless content is trusted.",
        languages=["python", "ruby"],
    ),

    # ── Hardcoded Secrets ────────────────────────────────────────────────
    SecurityRule(
        id="SEC020",
        name="Hardcoded API key",
        pattern=r"""(?:api[_-]?key|apikey)\s*[:=]\s*[\"'][A-Za-z0-9_\-]{16,}[\"']""",
        severity="critical",
        category="secrets",
        description="Hardcoded API key detected. Secrets should never be in source code.",
        fix_hint="Use environment variables: `os.getenv('API_KEY')` or a secrets manager.",
    ),
    SecurityRule(
        id="SEC021",
        name="Hardcoded password",
        pattern=r"""(?:password|passwd|pwd)\s*[:=]\s*[\"'][^\"']{4,}[\"']""",
        severity="critical",
        category="secrets",
        description="Hardcoded password detected.",
        fix_hint="Use environment variables or a secrets manager. Never hardcode passwords.",
        exclude_test_files=True,
    ),
    SecurityRule(
        id="SEC022",
        name="Hardcoded secret/token",
        pattern=r"""(?:secret|token|private[_-]?key)\s*[:=]\s*[\"'][A-Za-z0-9_\-/+=]{16,}[\"']""",
        severity="critical",
        category="secrets",
        description="Hardcoded secret or token detected.",
        fix_hint="Use environment variables or a secrets manager.",
    ),
    SecurityRule(
        id="SEC023",
        name="AWS credentials",
        pattern=r"""(?:AKIA[0-9A-Z]{16}|(?:aws_secret_access_key|aws_access_key_id)\s*[:=]\s*[\"'][^\"']+[\"'])""",
        severity="critical",
        category="secrets",
        description="AWS credentials detected in source code.",
        fix_hint="Use IAM roles, AWS Secrets Manager, or environment variables.",
    ),
    SecurityRule(
        id="SEC024",
        name="Private key in code",
        pattern=r"""-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----""",
        severity="critical",
        category="secrets",
        description="Private key embedded in source code.",
        fix_hint="Store private keys in a secure key store, not in source code.",
        exclude_test_files=True,
    ),

    # ── Path Traversal ───────────────────────────────────────────────────
    SecurityRule(
        id="SEC030",
        name="Path traversal",
        pattern=r"""(?:open|readFile|readFileSync|read_file|send_file|send_from_directory)\s*\(.*(?:request\.|req\.|params\.|args\.|input)""",
        severity="high",
        category="path-traversal",
        description="File operation using user input without sanitization. Vulnerable to path traversal.",
        fix_hint="Validate and sanitize file paths. Use `os.path.basename()` or resolve against a safe base directory.",
        languages=["python", "javascript", "typescript"],
    ),

    # ── Command Injection ────────────────────────────────────────────────
    SecurityRule(
        id="SEC040",
        name="Command injection (os.system/exec)",
        pattern=r"""(?:os\.system|os\.popen|subprocess\.call|subprocess\.run|exec|eval)\s*\(\s*(?:f[\"']|[\"'].*\+|[\"'].*\{|.*\+\s*(?:request|req|params|args|input|user))""",
        severity="critical",
        category="injection",
        description="System command built with user input. Vulnerable to command injection.",
        fix_hint="Use subprocess with a list of args (not shell=True). Never pass user input to system commands.",
        languages=["python"],
    ),
    SecurityRule(
        id="SEC041",
        name="Shell injection (shell=True)",
        pattern=r"""subprocess\.(?:call|run|Popen)\s*\(.*shell\s*=\s*True""",
        severity="high",
        category="injection",
        description="subprocess with shell=True can enable command injection.",
        fix_hint="Use `subprocess.run(['cmd', 'arg1', 'arg2'])` without shell=True.",
        languages=["python"],
    ),
    SecurityRule(
        id="SEC042",
        name="eval() with dynamic input",
        pattern=r"""(?<!\.)\beval\s*\(\s*(?!['\"]\s*\))""",
        severity="high",
        category="injection",
        description="eval() executes arbitrary code. Extremely dangerous with any dynamic input.",
        fix_hint="Use ast.literal_eval() for Python, JSON.parse() for JS, or avoid eval entirely.",
        languages=["python", "javascript", "typescript"],
    ),

    # ── Insecure Crypto ──────────────────────────────────────────────────
    SecurityRule(
        id="SEC050",
        name="Weak hash algorithm (MD5/SHA1)",
        pattern=r"""(?:hashlib\.md5|hashlib\.sha1|MD5\.Create|SHA1\.Create|createHash\s*\(\s*['\"](?:md5|sha1)['\"])""",
        severity="medium",
        category="crypto",
        description="MD5/SHA1 are cryptographically broken. Do not use for security purposes.",
        fix_hint="Use SHA-256 or SHA-3: `hashlib.sha256()`, `crypto.createHash('sha256')`",
    ),
    SecurityRule(
        id="SEC051",
        name="Insecure random for security",
        pattern=r"""(?:random\.random|random\.randint|Math\.random)\s*\(""",
        severity="medium",
        category="crypto",
        description="Standard random is not cryptographically secure. Don't use for tokens, keys, or security.",
        fix_hint="Use `secrets` module (Python) or `crypto.randomBytes()` (Node.js).",
        exclude_test_files=True,
    ),

    # ── SSRF ─────────────────────────────────────────────────────────────
    SecurityRule(
        id="SEC060",
        name="Server-Side Request Forgery (SSRF)",
        pattern=r"""(?:requests\.get|requests\.post|httpx\.get|httpx\.post|fetch|axios\.get|urllib\.request\.urlopen|http\.Get)\s*\(\s*(?:f[\"']|.*\+\s*(?:request|req|params|args|input|user)|.*\{.*(?:request|req|params|input))""",
        severity="high",
        category="ssrf",
        description="HTTP request with user-controlled URL. Vulnerable to SSRF.",
        fix_hint="Validate URLs against an allowlist. Block internal/private IP ranges.",
    ),

    # ── Insecure Deserialization ─────────────────────────────────────────
    SecurityRule(
        id="SEC070",
        name="Insecure deserialization (pickle)",
        pattern=r"""pickle\.(?:loads?|Unpickler)\s*\(""",
        severity="critical",
        category="deserialization",
        description="pickle deserialization of untrusted data enables remote code execution.",
        fix_hint="Use JSON or msgpack instead of pickle for untrusted data.",
        languages=["python"],
    ),
    SecurityRule(
        id="SEC071",
        name="Insecure deserialization (yaml.load)",
        pattern=r"""yaml\.load\s*\((?!.*Loader\s*=\s*(?:yaml\.)?SafeLoader)""",
        severity="high",
        category="deserialization",
        description="yaml.load() without SafeLoader can execute arbitrary code.",
        fix_hint="Use `yaml.safe_load()` or `yaml.load(data, Loader=yaml.SafeLoader)`.",
        languages=["python"],
    ),

    # ── Auth Issues ──────────────────────────────────────────────────────
    SecurityRule(
        id="SEC080",
        name="JWT without verification",
        pattern=r"""(?:jwt\.decode|verify\s*[:=]\s*false|algorithms\s*[:=]\s*\[\s*['\"]none['\"])""",
        severity="high",
        category="auth",
        description="JWT decoded without proper verification or with 'none' algorithm.",
        fix_hint="Always verify JWT signatures. Never allow 'none' algorithm.",
    ),
    SecurityRule(
        id="SEC081",
        name="CORS wildcard",
        pattern=r"""(?:Access-Control-Allow-Origin|allow_origins)\s*[:=]\s*[\"']\*[\"']|cors\s*\(\s*\)""",
        severity="medium",
        category="auth",
        description="CORS wildcard (*) allows any origin to access the API.",
        fix_hint="Restrict CORS to specific trusted origins.",
    ),
    SecurityRule(
        id="SEC082",
        name="Debug mode in production",
        pattern=r"""(?:DEBUG\s*=\s*True|debug\s*[:=]\s*true|app\.run\s*\(.*debug\s*=\s*True)""",
        severity="medium",
        category="auth",
        description="Debug mode enabled. This can expose sensitive information in production.",
        fix_hint="Disable debug mode in production. Use environment variables to control it.",
        exclude_test_files=True,
    ),

    # ── Dangerous Functions ──────────────────────────────────────────────
    SecurityRule(
        id="SEC090",
        name="Debugger/breakpoint left in code",
        pattern=r"""(?:debugger\s*;|pdb\.set_trace|breakpoint\s*\(\s*\)|import\s+pdb)""",
        severity="medium",
        category="quality",
        description="Debugger statement left in code. Remove before merging.",
        fix_hint="Remove all debugger statements before merging.",
        exclude_test_files=True,
    ),

    # ── Go-specific ──────────────────────────────────────────────────────
    SecurityRule(
        id="SEC100",
        name="SQL injection (Go)",
        pattern=r"""(?:db\.(?:Query|Exec|QueryRow))\s*\(\s*(?:fmt\.Sprintf|.*\+)""",
        severity="critical",
        category="injection",
        description="SQL query built with fmt.Sprintf or concatenation in Go.",
        fix_hint="Use parameterized queries: `db.Query(\"SELECT * FROM users WHERE id = $1\", id)`",
        languages=["go"],
    ),
    SecurityRule(
        id="SEC101",
        name="TLS verification disabled (Go)",
        pattern=r"""InsecureSkipVerify\s*:\s*true""",
        severity="high",
        category="crypto",
        description="TLS certificate verification disabled. Vulnerable to MITM attacks.",
        fix_hint="Never disable TLS verification in production.",
        languages=["go"],
    ),
]


def scan_diff(
    files: list[PRFile],
    rules: list[SecurityRule] | None = None,
    enabled: bool = True,
) -> list[SecurityFinding]:
    """Scan PR diff for security vulnerabilities.

    Args:
        files: PR files with patches
        rules: Custom rules (defaults to SECURITY_RULES)
        enabled: Whether scanning is enabled (from config)

    Returns:
        List of security findings
    """
    if not enabled:
        return []

    if rules is None:
        rules = SECURITY_RULES

    findings: list[SecurityFinding] = []

    for f in files:
        if not f.patch:
            continue

        file_lang = _detect_lang(f.filename)
        is_test = _is_test_file(f.filename)
        line_map = extract_diff_line_map(f.patch)

        for rule in rules:
            # Skip if rule is language-specific and doesn't match
            if rule.languages and file_lang not in rule.languages:
                continue

            # Skip test files if rule says so
            if rule.exclude_test_files and is_test:
                continue

            try:
                compiled = re.compile(rule.pattern, re.IGNORECASE)
            except re.error:
                continue

            for line_num, line_content in line_map.items():
                match = compiled.search(line_content)
                if match:
                    findings.append(
                        SecurityFinding(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            severity=rule.severity,
                            category=rule.category,
                            description=rule.description,
                            fix_hint=rule.fix_hint,
                            path=f.filename,
                            line=line_num,
                            matched_text=match.group(0)[:100],
                        )
                    )

    # Sort by severity
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda f: severity_order.get(f.severity, 4))

    return findings


def format_security_findings(findings: list[SecurityFinding]) -> list[dict]:
    """Format findings as inline review comments.

    Returns list of dicts with: path, line, body, severity.
    """
    severity_icon = {
        "critical": "CRITICAL",
        "high": "HIGH",
        "medium": "MEDIUM",
        "low": "LOW",
    }

    comments: list[dict] = []
    for f in findings:
        icon = severity_icon.get(f.severity, "WARNING")
        body = (
            f"**[{icon}] Security: {f.rule_name}** (`{f.rule_id}`)\n\n"
            f"{f.description}\n\n"
        )
        if f.fix_hint:
            body += f"**Fix:** {f.fix_hint}\n\n"
        if f.matched_text:
            body += f"Matched: `{f.matched_text}`"

        comments.append({
            "path": f.path,
            "line": f.line,
            "body": body,
            "severity": "critical" if f.severity in ("critical", "high") else "warning",
        })

    return comments


def format_security_summary(findings: list[SecurityFinding]) -> str:
    """Format a summary section for the review body."""
    if not findings:
        return ""

    by_severity: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for f in findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        by_category[f.category] = by_category.get(f.category, 0) + 1

    parts = [
        "",
        "### Security Scan",
        "",
        f"Found **{len(findings)} security issues:**",
        "",
    ]

    for sev in ("critical", "high", "medium", "low"):
        count = by_severity.get(sev, 0)
        if count:
            parts.append(f"- **{sev.upper()}**: {count}")

    parts.append("")
    parts.append("Categories: " + ", ".join(
        f"{cat} ({count})" for cat, count in sorted(by_category.items())
    ))

    return "\n".join(parts)
