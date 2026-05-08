# How to Set Up Free AI Code Review on GitHub in 30 Seconds

*Automated code review doesn't have to cost $19/user/month. Here's how to get AI reviews on every pull request for less than $1/month.*

## TL;DR

Add one file to your repo. Get AI code review on every PR. Total cost: ~$0.002/review with Groq (free tier available).

## Step 1: Create the Workflow

Create `.github/workflows/ai-review.yml` in your repo:

```yaml
name: AI Code Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: mara-werils/ai-code-reviewer@v1
        with:
          provider: 'groq'
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
```

## Step 2: Get Your API Key

1. Go to [console.groq.com](https://console.groq.com) and sign up (free)
2. Create an API key
3. In your GitHub repo: **Settings > Secrets > Actions > New secret**
4. Name: `GROQ_API_KEY`, Value: your key

## Step 3: Open a PR

That's it. Every PR now gets:

- **Inline comments** pointing to exact lines with issues
- **Severity levels** — critical, warning, suggestion, info
- **Suggested fixes** — one-click apply on GitHub
- **Security checks** — catches common vulnerabilities
- **Risk assessment** — low/medium/high rating
- **Cost tracking** — shows exactly what each review costs

## Why Groq?

Groq runs Llama 3.3 70B at ~$0.002/review. Their free tier gives you enough for most open-source projects. For comparison:

| Provider | Cost/Review | Quality |
|----------|------------|---------|
| Groq (Llama 3.3) | $0.002 | Very good |
| Google (Gemini Flash) | $0.003 | Good |
| OpenAI (GPT-4o) | $0.05 | Excellent |
| Anthropic (Claude) | $0.08 | Excellent |
| Ollama (local) | $0.00 | Depends on model |

You can switch providers with one line — no lock-in.

## Customizing Reviews

### Reduce noise

```yaml
# .pr-reviewer.yml (drop in repo root)
review_style: minimal
severity_threshold: warning
max_comments: 5

ignore_paths:
  - "*.lock"
  - "generated/**"
  - "docs/**"
```

### Add team conventions

```yaml
# .pr-reviewer.yml
custom_instructions: |
  - We use FastAPI with Pydantic v2
  - All API endpoints need input validation
  - We follow the Repository pattern for database access
  - Security-sensitive: we handle PII data
```

### On-demand reviews

Add `/review` support so anyone can trigger a review by commenting on a PR:

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened]
  issue_comment:
    types: [created]
```

See the [full on-demand setup](https://github.com/mara-werils/ai-code-reviewer#on-demand-review).

## What About GitLab?

AI Code Reviewer works with GitLab too:

```yaml
# .gitlab-ci.yml
ai-code-review:
  stage: test
  image: python:3.11-slim
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  script:
    - pip install --quiet pr-reviewer
    - pr-reviewer review --platform gitlab --repo "$CI_PROJECT_PATH" --mr "$CI_MERGE_REQUEST_IID" --post
```

## FAQ

**Is my code safe?**
Your code is sent only to the LLM provider you choose. Use Ollama for 100% local reviews where nothing leaves your network.

**Does it work with private repos?**
Yes. The GitHub Action uses the built-in `GITHUB_TOKEN`.

**Can I review in other languages?**
Yes — supports English, Chinese, Japanese, Korean, Spanish, German, French, Russian, Portuguese.

---

*[AI Code Reviewer](https://github.com/mara-werils/ai-code-reviewer) — free, open source, works with any LLM. Star it on GitHub.*
