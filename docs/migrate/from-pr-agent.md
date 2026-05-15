# Migrate from PR-Agent to AI Code Reviewer

PR-Agent (by CodiumAI) is a solid tool. Here's why you might switch and how.

## Why switch?

| | PR-Agent | AI Code Reviewer |
|---|---|---|
| **LLM support** | GPT-4 only | **Any** (GPT, Claude, Llama, Gemini, Ollama) |
| **Cost** | GPT-4 at ~$0.10/review | **$0.002** (Groq) or **$0.00** (Ollama) |
| **Setup** | Complex (Docker + config) | **30 seconds** (3 lines of YAML) |
| **Auto-fix** | No native `/fix` | **Yes** (commits fixes to branch) |
| **Test generation** | No | **Yes** (`/generate-tests`) |
| **Security scanner** | No (LLM-only) | **Yes** (35+ deterministic SAST rules) |
| **Rules engine** | No | **Yes** (declarative YAML) |
| **GitLab native** | Yes | **Yes** |
| **Bitbucket native** | No | **Yes** |
| **VS Code extension** | No | **Yes** |
| **Review personas** | No | **Yes** (security-hawk, mentor, etc.) |
| **Complexity scoring** | No | **Yes** (algorithmic, zero cost) |

## Step 1: Remove PR-Agent

1. Delete the PR-Agent workflow from `.github/workflows/`
2. Remove any PR-Agent Docker configuration

## Step 2: Add AI Code Reviewer

Create `.github/workflows/ai-review.yml`:

```yaml
name: AI Code Review

on:
  pull_request:
    types: [opened, synchronize, reopened]
  issue_comment:
    types: [created]

permissions:
  contents: write
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: mara-werils/ai-code-reviewer@v1
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
```

## Step 3: Migrate PR-Agent commands

| PR-Agent | AI Code Reviewer | Notes |
|----------|-----------------|-------|
| `/review` | `/review` | Same command |
| `/describe` | Auto-summarize | Enabled by default |
| `/improve` | `/fix` | AI Code Reviewer commits fixes directly |
| `/ask` | `/ask` | Same command |
| N/A | `/generate-tests` | New — no PR-Agent equivalent |

## Step 4: Migrate configuration

### PR-Agent config → .pr-reviewer.yml
```yaml
# PR-Agent (.pr_agent.toml)
[pr_reviewer]
extra_instructions = "Focus on Python best practices"
num_max_findings = 10

# AI Code Reviewer (.pr-reviewer.yml)
custom_instructions: |
  - Focus on Python best practices
max_comments: 10
```

## Done

Open a PR and see the difference. Most teams report faster reviews and lower costs.
