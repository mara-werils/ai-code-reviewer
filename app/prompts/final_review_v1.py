VERSION = "v1"

FINAL_REVIEW_PROMPT = """Based on all your research and analysis of this pull request, produce a structured review.

You MUST respond with a valid JSON object in this exact format:
{{
    "summary": "2-4 sentences summarizing the PR and your overall assessment",
    "risk_level": "low|medium|high",
    "comments": [
        {{
            "file_path": "path/to/file.py",
            "line_number": 42,
            "body": "Clear, actionable comment explaining the issue and suggesting a fix",
            "severity": "info|suggestion|warning|critical",
            "category": "correctness|performance|security|style|test_coverage|design"
        }}
    ]
}}

Rules for comments:
- Only include comments about real issues or important suggestions.
- Each comment must reference a specific file and ideally a specific line.
- line_number can be null if the comment is about the file in general.
- severity: critical = must fix before merge, warning = should fix, suggestion = nice to have, info = FYI.
- Be specific: say what's wrong AND how to fix it.
- Limit to at most 10 comments. Prioritize by severity.
- If the PR looks good, return an empty comments array with a positive summary.

Do not include any text outside the JSON object."""
