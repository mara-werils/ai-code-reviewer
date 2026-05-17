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
    ".mjs": "javascript",
    ".cjs": "javascript",
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
    ".zsh": "shell",
    ".sql": "sql",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".dockerfile": "docker",
    ".tf": "terraform",
    ".hcl": "terraform",
}

_TEST_PATTERNS = (
    "test_",
    "_test.",
    ".test.",
    ".spec.",
    "tests/",
    "__tests__/",
    "testing/",
    "fixtures/",
    "mocks/",
    "testdata/",
    "test-data/",
)


def _detect_lang(path: str) -> str:
    # Handle files without extensions (e.g., Dockerfile, Makefile)
    basename = path.rsplit("/", 1)[-1].lower()
    if basename == "dockerfile" or basename.startswith("dockerfile."):
        return "docker"
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
        fix_hint='Use parameterized queries: `db.Query("SELECT * FROM users WHERE id = $1", id)`',
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
    # ── Additional rules (expanded coverage) ────────────────────────────────
    # Path traversal via user input in filenames
    SecurityRule(
        id="SEC031",
        name="Path traversal (os.path.join with user input)",
        pattern=r"""os\.path\.join\s*\(.*(?:request|req\.|params|args|input|user)""",
        severity="high",
        category="path-traversal",
        description="os.path.join with user input can be bypassed with absolute paths.",
        fix_hint="Use pathlib and resolve against a safe base: `base.joinpath(user_input).resolve().relative_to(base)`",
        languages=["python"],
    ),
    # Timing attack on secret comparison
    SecurityRule(
        id="SEC052",
        name="Timing attack (string comparison of secrets)",
        pattern=r"""(?:secret|token|password|api_key|hash|digest)\s*(?:==|!=)\s*""",
        severity="medium",
        category="crypto",
        description="String comparison of secrets is vulnerable to timing attacks.",
        fix_hint="Use `hmac.compare_digest()` (Python) or `crypto.timingSafeEqual()` (Node.js).",
        exclude_test_files=True,
    ),
    # Prototype pollution (JS)
    SecurityRule(
        id="SEC110",
        name="Prototype pollution",
        pattern=r"""(?:__proto__|constructor\s*\[|Object\.assign\s*\(\s*\{\s*\}\s*,.*(?:req|request|params|body))""",
        severity="high",
        category="injection",
        description="Potential prototype pollution via user-controlled object merge.",
        fix_hint="Validate input keys. Use Object.create(null) or a safe merge library.",
        languages=["javascript", "typescript"],
    ),
    # Open redirect
    SecurityRule(
        id="SEC111",
        name="Open redirect",
        pattern=r"""(?:redirect|location\.href|window\.location|res\.redirect)\s*(?:=|\()\s*(?:req\.|request\.|params\.|args\.|query\.)""",
        severity="medium",
        category="auth",
        description="Redirect URL from user input. Vulnerable to open redirect attacks.",
        fix_hint="Validate redirect URLs against an allowlist of trusted domains.",
    ),
    # XML External Entity (XXE)
    SecurityRule(
        id="SEC112",
        name="XML External Entity (XXE)",
        pattern=r"""(?:etree\.parse|xml\.dom\.minidom\.parse|parseString|XMLParser)\s*\(""",
        severity="high",
        category="injection",
        description="XML parsing without disabling external entities is vulnerable to XXE.",
        fix_hint="Disable external entities: use defusedxml library or set parser features.",
        languages=["python"],
    ),
    # Unsafe regex (ReDoS)
    SecurityRule(
        id="SEC113",
        name="ReDoS (catastrophic backtracking)",
        pattern=r"""re\.(?:compile|match|search|findall)\s*\(\s*[\"'](?:.*\.\*.*\.\*|.*\+.*\+|.*\{.*\}.*\{.*\})""",
        severity="medium",
        category="quality",
        description="Complex regex with nested quantifiers may cause catastrophic backtracking (ReDoS).",
        fix_hint="Simplify regex or use re2/google-re2 for guaranteed linear time.",
        languages=["python"],
    ),
    # Hardcoded JWT secret
    SecurityRule(
        id="SEC025",
        name="Hardcoded JWT secret",
        pattern=r"""jwt\.(?:encode|sign)\s*\(.*[\"'][A-Za-z0-9_\-]{8,}[\"']""",
        severity="critical",
        category="secrets",
        description="JWT signed with hardcoded secret. Secret will be exposed in source control.",
        fix_hint="Load JWT secret from environment variable or secrets manager.",
    ),
    # Mass assignment
    SecurityRule(
        id="SEC114",
        name="Mass assignment",
        pattern=r"""\.(?:update|create)\s*\(\s*\*\*(?:request\.(?:data|json|POST|body)|kwargs)""",
        severity="high",
        category="auth",
        description="Mass assignment: passing request data directly to ORM create/update can allow privilege escalation.",
        fix_hint="Explicitly list allowed fields instead of passing **request.data directly.",
        languages=["python"],
    ),
    # Unvalidated file upload
    SecurityRule(
        id="SEC115",
        name="Unvalidated file upload",
        pattern=r"""(?:save|write|upload).*(?:request\.files|uploaded_file|file\.save)\s*\(""",
        severity="high",
        category="path-traversal",
        description="File upload without validation. Check file type, size, and sanitize filename.",
        fix_hint="Validate MIME type, limit file size, use `secure_filename()`, and store outside web root.",
    ),
    # Disabled CSRF protection
    SecurityRule(
        id="SEC083",
        name="CSRF protection disabled",
        pattern=r"""(?:csrf_exempt|@csrf_exempt|WTF_CSRF_ENABLED\s*=\s*False|CSRF_ENABLED\s*=\s*False)""",
        severity="high",
        category="auth",
        description="CSRF protection disabled. State-changing endpoints are vulnerable to CSRF attacks.",
        fix_hint="Enable CSRF protection. Use token-based CSRF for APIs, SameSite cookies for sessions.",
        languages=["python"],
    ),
    # Insecure cookie
    SecurityRule(
        id="SEC084",
        name="Insecure cookie settings",
        pattern=r"""(?:set_cookie|cookies\[)\s*.*(?:httponly\s*=\s*False|secure\s*=\s*False|samesite\s*=\s*[\"'](?:none|None)[\"'])""",
        severity="medium",
        category="auth",
        description="Cookie set without security flags (httponly, secure, samesite).",
        fix_hint="Set httponly=True, secure=True, samesite='Lax' for session cookies.",
    ),
    # Logging sensitive data
    SecurityRule(
        id="SEC091",
        name="Sensitive data in logs",
        pattern=r"""(?:log(?:ger)?\.(?:info|debug|warning|error)|print|console\.log)\s*\(.*(?:password|secret|token|api_key|credit_card|ssn)""",
        severity="medium",
        category="secrets",
        description="Sensitive data (password, token, etc.) may be written to logs.",
        fix_hint="Redact sensitive fields before logging. Use structured logging with field filtering.",
        exclude_test_files=True,
    ),
    # Hardcoded IP / internal URLs
    SecurityRule(
        id="SEC026",
        name="Hardcoded internal URL",
        pattern=r"""(?:https?://(?:localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+))""",
        severity="low",
        category="secrets",
        description="Hardcoded internal URL/IP. Use configuration or service discovery.",
        fix_hint="Use environment variables for service URLs.",
        exclude_test_files=True,
    ),
    # TypeScript any abuse
    SecurityRule(
        id="SEC120",
        name="TypeScript 'any' type in security context",
        pattern=r"""(?:token|auth|session|credential|password|secret)\s*:\s*any\b""",
        severity="medium",
        category="quality",
        description="Using 'any' type for security-sensitive variables disables type checking.",
        fix_hint="Use specific types for auth/security variables to catch misuse at compile time.",
        languages=["typescript"],
        exclude_test_files=True,
    ),
    # Go defer in loop
    SecurityRule(
        id="SEC102",
        name="Defer in loop (Go resource leak)",
        pattern=r"""for\s.*\{[^}]*defer\s""",
        severity="medium",
        category="quality",
        description="defer inside a loop delays cleanup until function exit, causing resource leaks.",
        fix_hint="Extract the loop body into a separate function, or close resources manually.",
        languages=["go"],
        exclude_test_files=True,
    ),
    # ── NoSQL Injection ─────────────────────────────────────────────────
    SecurityRule(
        id="SEC130",
        name="NoSQL injection (MongoDB)",
        pattern=r"""(?:\.find|\.findOne|\.updateOne|\.deleteOne|\.aggregate)\s*\(\s*(?:f[\"']|.*\{.*\$(?:where|regex|ne|gt|lt|gte|lte|in|nin|or|and|not|nor|exists))""",
        severity="high",
        category="injection",
        description="MongoDB query with operator injection. Attacker can manipulate query logic via $-operators.",
        fix_hint="Validate and sanitize user input. Use explicit field matching, not raw query objects from user input.",
        languages=["python", "javascript", "typescript"],
    ),
    # ── Server-Side Template Injection ──────────────────────────────────
    SecurityRule(
        id="SEC131",
        name="Server-Side Template Injection (SSTI)",
        pattern=r"""(?:render_template_string|Template\s*\(\s*(?:request|req|params|args|user|input)|Jinja2.*from_string|Environment\s*\(.*loader)""",
        severity="critical",
        category="injection",
        description="Template rendered from user input enables server-side template injection (SSTI).",
        fix_hint="Never pass user input as a template. Use render_template() with a file, not render_template_string().",
        languages=["python"],
    ),
    # ── LDAP Injection ──────────────────────────────────────────────────
    SecurityRule(
        id="SEC132",
        name="LDAP injection",
        pattern=r"""(?:ldap\.search|search_s|search_ext_s)\s*\(.*(?:f[\"']|[\"'].*\{|[\"'].*\+\s*\w)""",
        severity="high",
        category="injection",
        description="LDAP query built with string formatting. Vulnerable to LDAP injection.",
        fix_hint="Use parameterized LDAP filters or escape special characters with ldap.filter.escape_filter_chars().",
        languages=["python"],
    ),
    # ── Unsafe Rust ─────────────────────────────────────────────────────
    SecurityRule(
        id="SEC140",
        name="Unsafe Rust block",
        pattern=r"""unsafe\s*\{""",
        severity="medium",
        category="quality",
        description="unsafe block bypasses Rust's memory safety guarantees. Requires careful review.",
        fix_hint="Minimize unsafe scope. Document safety invariants. Consider safe alternatives.",
        languages=["rust"],
        exclude_test_files=True,
    ),
    # ── PHP-specific ────────────────────────────────────────────────────
    SecurityRule(
        id="SEC150",
        name="PHP code injection",
        pattern=r"""(?:eval|assert|preg_replace\s*\(.*['\"]\/.*\/e)\s*\(""",
        severity="critical",
        category="injection",
        description="eval/assert/preg_replace with 'e' modifier enables arbitrary code execution.",
        fix_hint="Avoid eval(). Use preg_replace_callback() instead of the /e modifier.",
        languages=["php"],
    ),
    SecurityRule(
        id="SEC151",
        name="PHP file inclusion",
        pattern=r"""(?:include|require|include_once|require_once)\s*\(\s*\$""",
        severity="critical",
        category="injection",
        description="Dynamic file inclusion with user-controlled variable enables Local/Remote File Inclusion.",
        fix_hint="Use an allowlist of permitted files. Never include files based on user input.",
        languages=["php"],
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
        body = f"**[{icon}] Security: {f.rule_name}** (`{f.rule_id}`)\n\n{f.description}\n\n"
        if f.fix_hint:
            body += f"**Fix:** {f.fix_hint}\n\n"
        if f.matched_text:
            body += f"Matched: `{f.matched_text}`"

        comments.append(
            {
                "path": f.path,
                "line": f.line,
                "body": body,
                "severity": "critical" if f.severity in ("critical", "high") else "warning",
            }
        )

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
    parts.append(
        "Categories: " + ", ".join(f"{cat} ({count})" for cat, count in sorted(by_category.items()))
    )

    return "\n".join(parts)
