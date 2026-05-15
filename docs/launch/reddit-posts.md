# Reddit Launch Posts

## r/programming

**Title:** I built an open-source AI code reviewer that works with any LLM — GPT, Claude, Llama, Ollama — for $0.002/review (or $0 locally)

**Body:**
After paying $19/user/month for CodeRabbit, I decided to build a free alternative.

**What it does:**
- Reviews your PRs automatically when you open them
- Posts inline comments with severity levels and suggested fixes
- Runs a built-in security scanner (35+ SAST rules, zero LLM cost)
- Has slash commands: /fix (commits fixes), /generate-tests (creates tests), /ask (chat)

**What makes it different:**
- Works with ANY LLM — not locked into one provider
- 6 "review personas" — security-hawk for fintech, mentor for junior devs, quick-scan for large PRs
- Declarative rules engine — codify team conventions in YAML
- PR complexity scoring — algorithmic, no LLM needed
- GitHub + GitLab + Bitbucket + VS Code + CLI + pre-commit

**Setup is 30 seconds** — one YAML file in your repo.

GitHub: https://github.com/mara-werils/ai-code-reviewer

Open source (MIT). No telemetry. No lock-in.

Happy to answer questions.

---

## r/devops

**Title:** We added AI code review to our CI/CD — here's how it works with GitHub Actions, GitLab CI, and Bitbucket Pipelines

**Body:**
We've been running an open-source AI code reviewer across all our repos. It:

1. Reviews every PR automatically (30s setup)
2. Posts inline comments with severity and suggested fixes
3. Runs 35+ SAST rules for free (no LLM needed)
4. Sends Slack/Discord notifications when risk is high
5. Computes PR complexity scores to enforce small PRs

The killer feature for our DevOps team is the **DORA persona** — it focuses on deployment risk, rollback safety, and feature flags instead of code style.

Works with Groq ($0.002/review), OpenAI, Anthropic, or Ollama (free, local).

GitHub: https://github.com/mara-werils/ai-code-reviewer

---

## r/selfhosted

**Title:** Open-source self-hosted AI code reviewer — runs locally with Ollama, your code never leaves your network

**Body:**
Built an AI code reviewer that can run 100% locally:

- Use Ollama as the LLM — nothing sent to external APIs
- Self-hosted mode with Docker: PostgreSQL + Redis + FastAPI
- RAG-powered: indexes your codebase with AST parsing (Python, JS, TS, Go)
- LangGraph agent with 7 tools to investigate code
- Full analytics dashboard

Even without the self-hosted mode, the basic setup (GitHub Action + Ollama on a private runner) takes 5 minutes and keeps everything in your network.

GitHub: https://github.com/mara-werils/ai-code-reviewer
License: MIT
