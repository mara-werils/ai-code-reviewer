"""Review personas — predefined reviewer personalities.

Instead of manual custom_instructions, teams can pick a persona
that bundles review style, priorities, and tone into a single keyword.

Usage in .pr-reviewer.yml:
    persona: security-hawk

Usage in action.yml:
    with:
      persona: mentor
"""

from __future__ import annotations

from dataclasses import dataclass

PERSONA_REGISTRY: dict[str, "Persona"] = {}


@dataclass
class Persona:
    name: str
    description: str
    system_addendum: str  # injected into the system prompt
    review_style: str  # overrides config.review_style
    max_comments: int | None = None  # override or None to keep default


def _register(persona: Persona) -> Persona:
    PERSONA_REGISTRY[persona.name] = persona
    return persona


# ── Built-in personas ────────────────────────────────────────────────────────

_register(Persona(
    name="default",
    description="Balanced reviewer — catches bugs without being noisy.",
    system_addendum="",
    review_style="concise",
))

_register(Persona(
    name="security-hawk",
    description="Security-focused reviewer — prioritizes vulnerabilities and auth issues.",
    system_addendum="""
## Security-First Review Mode

You are in SECURITY-HAWK mode. Your top priorities are:
1. **Injection vulnerabilities** — SQL, command, XSS, SSRF, template injection
2. **Authentication & authorization** — missing checks, privilege escalation, token handling
3. **Secrets exposure** — hardcoded keys, tokens, passwords in code or config
4. **Data validation** — untrusted input at API boundaries, deserialization
5. **Cryptography** — weak algorithms, insecure random, missing TLS verification

Skip style, naming, and minor design issues. Focus ONLY on security-relevant findings.
For each finding, include a CWE reference when applicable (e.g., CWE-89 for SQL injection).
""",
    review_style="thorough",
    max_comments=25,
))

_register(Persona(
    name="mentor",
    description="Educational reviewer — explains WHY, not just WHAT. Great for junior devs.",
    system_addendum="""
## Mentor Review Mode

You are reviewing code written by a developer who is learning. Your goal is to TEACH, not just find bugs.

For every comment:
1. **Explain WHY** the suggestion matters (performance, security, maintainability)
2. **Show the pattern** — don't just fix this line, explain the general principle
3. **Link to concepts** — mention design patterns, SOLID principles, or language idioms
4. **Be encouraging** — acknowledge good decisions alongside suggestions
5. **Rate skill level** — adapt your explanation depth to the code quality you see

Keep severity labels, but add a "Learn more" section with the underlying concept.
Example: "This is the **Strategy pattern** — by extracting the algorithm into a separate class..."
""",
    review_style="thorough",
    max_comments=20,
))

_register(Persona(
    name="nitpicker",
    description="Thorough reviewer — catches everything including style and naming.",
    system_addendum="""
## Nitpicker Review Mode

You catch EVERYTHING. Unlike the default mode, you DO comment on:
1. **Naming** — unclear variable names, inconsistent conventions, abbreviations
2. **Style** — formatting issues that linters might miss, import ordering
3. **Documentation** — missing docstrings, outdated comments, unclear type hints
4. **Design** — tight coupling, missing abstractions, code smells
5. **Performance** — even minor optimizations worth noting

Use severity levels strictly: style issues are INFO, naming is SUGGESTION.
""",
    review_style="thorough",
    max_comments=30,
))

_register(Persona(
    name="quick-scan",
    description="Fast, minimal reviewer — only catches critical bugs and security issues.",
    system_addendum="""
## Quick Scan Mode

Speed is the priority. Only flag:
1. **Bugs** that will cause runtime errors or data corruption
2. **Security** vulnerabilities (injection, auth bypass, secrets)
3. **Breaking changes** to public APIs

Skip everything else. Maximum 5 comments. No style, no performance, no design.
""",
    review_style="minimal",
    max_comments=5,
))

_register(Persona(
    name="dora",
    description="DORA metrics optimizer — focuses on deployment risk and change failure rate.",
    system_addendum="""
## DORA Review Mode

Review through the lens of DORA metrics (Deployment Frequency, Lead Time, Change Failure Rate, MTTR).

Focus on:
1. **Deployment risk** — could this change cause a rollback? Flag risky deploys.
2. **Rollback safety** — are database migrations reversible? Feature flags in place?
3. **Monitoring** — are new code paths observable? Logging, metrics, alerts?
4. **Test coverage** — will existing tests catch regressions from this change?
5. **Feature flags** — should this be behind a flag for progressive rollout?

For each issue, estimate the impact on Change Failure Rate (Low/Medium/High).
""",
    review_style="thorough",
))


def get_persona(name: str) -> Persona | None:
    """Look up a persona by name. Returns None if not found."""
    return PERSONA_REGISTRY.get(name.lower().strip())


def list_personas() -> list[Persona]:
    """Return all registered personas."""
    return list(PERSONA_REGISTRY.values())


def apply_persona(persona: Persona, system_prompt: str, config_style: str) -> tuple[str, str]:
    """Apply persona to system prompt and review style.

    Returns (modified_system_prompt, review_style).
    """
    modified = system_prompt
    if persona.system_addendum:
        modified = system_prompt + "\n" + persona.system_addendum

    style = persona.review_style if persona.review_style else config_style
    return modified, style
