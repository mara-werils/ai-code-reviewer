# Migrate from CodeRabbit to AI Code Reviewer

Switching from CodeRabbit takes about 5 minutes. Here's the step-by-step guide.

## Why switch?

| | CodeRabbit | AI Code Reviewer |
|---|---|---|
| **Price** | $19/user/month | **Free** (bring your API key) |
| **LLM choice** | Fixed (no control) | **Any** (GPT, Claude, Llama, Gemini, Ollama) |
| **Local mode** | No | **Yes** (Ollama, 100% private) |
| **Custom rules** | No | **Yes** (declarative YAML) |
| **Security scanner** | No | **Yes** (35+ SAST rules, free) |
| **Auto-fix** | No | **Yes** (`/fix` commits to branch) |
| **Test generation** | No | **Yes** (`/generate-tests`) |
| **Self-hosted** | No | **Yes** (Docker, full control) |
| **Cost per review** | ~$0.50 (bundled) | **$0.002** (Groq) or **$0.00** (Ollama) |

## Step 1: Remove CodeRabbit

1. Go to [github.com/apps/coderabbitai](https://github.com/apps/coderabbitai) and uninstall the app
2. Delete `.coderabbit.yaml` from your repos (optional — we can migrate settings)

## Step 2: Add AI Code Reviewer

Create `.github/workflows/ai-review.yml`:

```yaml
name: AI Code Review

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
      (github.event_name == 'issue_comment' && github.event.issue.pull_request)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: mara-werils/ai-code-reviewer@v1
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
```

## Step 3: Add your API key

Go to **Settings > Secrets > Actions** and add `GROQ_API_KEY`.

Get a free key at [console.groq.com](https://console.groq.com).

## Step 4: Migrate your CodeRabbit config (optional)

If you had a `.coderabbit.yaml`, here's how to translate common settings:

### Path ignore
```yaml
# CodeRabbit
path_filters:
  - "!dist/**"
  - "!*.lock"

# AI Code Reviewer (.pr-reviewer.yml)
ignore_paths:
  - "dist/**"
  - "*.lock"
```

### Review instructions
```yaml
# CodeRabbit
reviews:
  instructions: "Focus on security and performance"

# AI Code Reviewer (.pr-reviewer.yml)
custom_instructions: |
  - Focus on security and performance
```

### Language
```yaml
# CodeRabbit
language: "ja"

# AI Code Reviewer
# In workflow or .pr-reviewer.yml
language: ja
```

## Step 5: Open a PR

That's it. AI review lands in 30 seconds at ~1/100th the cost.

## FAQ

**Q: Will I lose review history?**
A: CodeRabbit reviews stay on your PRs as comments. They won't be deleted.

**Q: Can I run both side by side?**
A: Yes, but you'll get duplicate reviews. We recommend switching fully.

**Q: What about CodeRabbit's learnings?**
A: Add your team's conventions to `custom_instructions` in `.pr-reviewer.yml`. The `/fix` command and rules engine give you more control than CodeRabbit's implicit learning.
