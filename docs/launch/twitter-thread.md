# Twitter/X Launch Thread

## Thread

**Tweet 1 (hook):**
I was paying $19/user/month for AI code reviews.

So I built an open-source alternative that costs $0.002/review.

AI Code Reviewer — free, works with any LLM, sets up in 30 seconds.

Here's what it does: [thread]

---

**Tweet 2 (the problem):**
The problem with existing AI code review tools:

- CodeRabbit: $19/user/month ($11,400/year for a 50-person team)
- GitHub Copilot: $19/user/month, locked to their model
- PR-Agent: Free but GPT-4 only, complex setup

I wanted: any LLM, zero config, free.

---

**Tweet 3 (the solution):**
AI Code Reviewer:

1. Add one YAML file to your repo
2. Every PR gets an AI review in 30 seconds
3. Choose your LLM: GPT-4o, Claude, Llama, Gemini, or local Ollama
4. Cost: $0.002/review with Groq (free tier exists)

That's it. No apps to install. No accounts to create.

---

**Tweet 4 (demo):**
What you get on every PR:

- Inline comments on the exact lines with issues
- Severity levels: critical > warning > suggestion > info
- Suggested fixes you can apply with one click
- Security checks
- Risk assessment

[screenshot/GIF of a review]

---

**Tweet 5 (killer features):**
Features that make it stand out:

- /review — type it in any PR comment to trigger a review
- GitLab CI support — not just GitHub
- .pr-reviewer.yml — teach it your team's conventions
- Cost estimation — know the cost before the review runs
- 9 languages — review in English, Chinese, Japanese, etc.

---

**Tweet 6 (self-hosted):**
For teams needing full control, there's a self-hosted mode:

- AST-based code indexing (understands your codebase)
- Vector search + semantic retrieval
- LangGraph agent with 7 investigation tools
- Analytics dashboard
- Feedback loop — learns from your reactions

docker-compose up -d

---

**Tweet 7 (CTA):**
AI Code Reviewer is MIT-licensed and free forever.

GitHub: github.com/mara-werils/ai-code-reviewer

If this saves you time:
- Star the repo
- Try it on one of your PRs
- Tell me what features would make it a must-have

Let's make AI code review accessible to every developer.

---

## Alt: Single Tweet (for shares)

I built an open-source AI code reviewer that works with ANY LLM (GPT, Claude, Llama, Gemini, Ollama).

- 30-second setup
- $0.002/review with Groq
- GitHub Actions + GitLab CI
- Inline comments + suggested fixes
- 100% free, MIT licensed

github.com/mara-werils/ai-code-reviewer
