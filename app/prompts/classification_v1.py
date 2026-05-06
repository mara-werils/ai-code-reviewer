VERSION = "v1"

CLASSIFICATION_PROMPT = """You are a PR classification system. Analyze the following pull request and classify it.

**PR Title:** {pr_title}
**PR Body:** {pr_body}

**Changed files:**
{changed_files}

**Diff summary (first 3000 chars):**
```
{diff_summary}
```

Classify this PR into exactly one category and assess its risk level.

Categories:
- bugfix: Fixes a bug or defect
- feature: Adds new functionality
- refactor: Code restructuring without behavior change
- docs: Documentation changes only
- chore: Build, CI, dependencies, tooling
- other: None of the above

Risk levels:
- low: Small, isolated changes, unlikely to break anything
- medium: Moderate changes, touches important logic
- high: Large changes, touches critical paths, security-sensitive, or cross-cutting

Respond with a JSON object:
{{
    "category": "...",
    "risk_level": "...",
    "reasoning": "One sentence explaining why"
}}"""
