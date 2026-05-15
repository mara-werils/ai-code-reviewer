"""Interactive setup wizard — generates .pr-reviewer.yml and workflow YAML.

Usage:
    pr-reviewer init
"""

from __future__ import annotations

import os
from pathlib import Path

WORKFLOW_TEMPLATE = """name: AI Code Review

on:
  pull_request:
    types: [opened, synchronize, reopened]
  issue_comment:
    types: [created]
  pull_request_review_comment:
    types: [created]

permissions:
  contents: write
  pull-requests: write

jobs:
  review:
    if: |
      github.event_name == 'pull_request' ||
      (github.event_name == 'issue_comment' && github.event.issue.pull_request &&
       contains(fromJSON('["/review", "/fix", "/ask", "/generate-tests"]'),
                split(github.event.comment.body, ' ')[0])) ||
      github.event_name == 'pull_request_review_comment'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: mara-werils/ai-code-reviewer@v1
        env:
          {api_key_env}: ${{{{ secrets.{api_key_secret} }}}}
"""

CONFIG_TEMPLATE = """# AI Code Reviewer configuration
# Docs: https://github.com/mara-werils/ai-code-reviewer#configuration

{persona_line}review_style: {review_style}
max_comments: {max_comments}

{custom_instructions_block}
ignore_paths:
  - "*.lock"
  - "*.min.js"
  - "*.min.css"
  - "package-lock.json"
  - "yarn.lock"
  - "pnpm-lock.yaml"
  - "vendor/**"
  - "node_modules/**"
  - "dist/**"
  - "build/**"
{extra_ignores}
check_security: true
suggest_tests: true
"""

PROVIDER_INFO = {
    "groq": {
        "env": "GROQ_API_KEY",
        "cost": "$0.002/review",
        "url": "https://console.groq.com",
        "note": "Fastest and cheapest. Free tier available.",
    },
    "openai": {
        "env": "OPENAI_API_KEY",
        "cost": "~$0.05/review",
        "url": "https://platform.openai.com/api-keys",
        "note": "GPT-4o. Best quality, higher cost.",
    },
    "anthropic": {
        "env": "ANTHROPIC_API_KEY",
        "cost": "~$0.08/review",
        "url": "https://console.anthropic.com",
        "note": "Claude Sonnet. Excellent for nuanced reviews.",
    },
    "google": {
        "env": "GOOGLE_API_KEY",
        "cost": "~$0.003/review",
        "url": "https://aistudio.google.com/apikey",
        "note": "Gemini 2.0 Flash. Good balance of cost and quality.",
    },
    "ollama": {
        "env": "",
        "cost": "$0.00",
        "url": "https://ollama.com",
        "note": "100% local. No data leaves your machine.",
    },
}


def _prompt(question: str, options: list[str] | None = None, default: str = "") -> str:
    """Simple prompt with optional choices."""
    if options:
        print(f"\n{question}")
        for i, opt in enumerate(options, 1):
            marker = " (default)" if opt == default else ""
            print(f"  {i}. {opt}{marker}")
        while True:
            raw = input(f"Choose [1-{len(options)}]: ").strip()
            if not raw and default:
                return default
            try:
                idx = int(raw)
                if 1 <= idx <= len(options):
                    return options[idx - 1]
            except ValueError:
                if raw in options:
                    return raw
            print(f"  Please enter 1-{len(options)}")
    else:
        suffix = f" [{default}]" if default else ""
        raw = input(f"{question}{suffix}: ").strip()
        return raw or default


def run_wizard() -> None:
    """Interactive setup wizard."""
    print("=" * 60)
    print("  AI Code Reviewer — Setup Wizard")
    print("=" * 60)

    # 1. Provider
    provider = _prompt(
        "Which LLM provider?",
        options=list(PROVIDER_INFO.keys()),
        default="groq",
    )
    info = PROVIDER_INFO[provider]
    print(f"\n  {info['note']}")
    print(f"  Cost: {info['cost']}")
    if info["url"]:
        print(f"  Get API key: {info['url']}")

    # 2. Persona
    persona = _prompt(
        "Review persona?",
        options=["default", "security-hawk", "mentor", "nitpicker", "quick-scan", "dora"],
        default="default",
    )

    # 3. Review style (skip if persona chosen)
    if persona == "default":
        review_style = _prompt(
            "Review style?",
            options=["concise", "thorough", "minimal"],
            default="concise",
        )
    else:
        from src.review.personas import get_persona

        p = get_persona(persona)
        review_style = p.review_style if p else "concise"

    # 4. Max comments
    max_comments_str = _prompt("Max comments per review?", default="15")
    try:
        max_comments = int(max_comments_str)
    except ValueError:
        max_comments = 15

    # 5. Custom instructions
    print("\nCustom instructions (team conventions, press Enter to skip):")
    custom = input("  > ").strip()

    # 6. Framework detection
    extra_ignores = ""
    if Path("next.config.js").exists() or Path("next.config.mjs").exists():
        extra_ignores += '  - ".next/**"\n'
    if Path("venv").exists() or Path(".venv").exists():
        extra_ignores += '  - "venv/**"\n  - ".venv/**"\n'

    # Generate files
    persona_line = f"persona: {persona}\n" if persona != "default" else ""
    custom_block = f"custom_instructions: |\n  - {custom}" if custom else ""

    config_content = CONFIG_TEMPLATE.format(
        persona_line=persona_line,
        review_style=review_style,
        max_comments=max_comments,
        custom_instructions_block=custom_block,
        extra_ignores=extra_ignores,
    )

    api_env = info["env"] or "OPENAI_API_KEY"
    workflow_content = WORKFLOW_TEMPLATE.format(
        api_key_env=api_env,
        api_key_secret=api_env,
    )

    # Write files
    print("\n" + "=" * 60)

    config_path = Path(".pr-reviewer.yml")
    config_path.write_text(config_content)
    print(f"  Created: {config_path}")

    workflow_dir = Path(".github/workflows")
    workflow_dir.mkdir(parents=True, exist_ok=True)
    workflow_path = workflow_dir / "ai-review.yml"
    if workflow_path.exists():
        overwrite = input(f"  {workflow_path} exists. Overwrite? [y/N]: ").strip().lower()
        if overwrite != "y":
            print(f"  Skipped: {workflow_path}")
        else:
            workflow_path.write_text(workflow_content)
            print(f"  Updated: {workflow_path}")
    else:
        workflow_path.write_text(workflow_content)
        print(f"  Created: {workflow_path}")

    print("\n  Next steps:")
    if info["env"]:
        print(f"  1. Add {info['env']} to GitHub repo secrets")
        print(f"     Settings > Secrets > Actions > New repository secret")
    print(f"  2. Push to GitHub and open a PR")
    print(f"  3. AI review lands in ~30 seconds")
    print("=" * 60)
