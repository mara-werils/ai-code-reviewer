# Product Hunt Launch Plan

## Listing Details

**Name:** AI Code Reviewer

**Tagline (60 chars max):**
Free AI code review with any LLM. Drop-in CodeRabbit alternative.

**Description:**
AI Code Reviewer adds automated AI-powered code review to your pull requests in 30 seconds. Just add one workflow file — no config needed.

Unlike paid tools ($19/user/month), AI Code Reviewer is 100% free and open source. Bring your own LLM — GPT-4o, Claude, Llama, Gemini, or run 100% locally with Ollama for $0.

**Key features:**
- One-line setup, zero config (30 seconds)
- Works with ANY LLM (OpenAI, Anthropic, Groq, Google, Ollama)
- 6 review personas: security-hawk, mentor, nitpicker, quick-scan, dora
- `/fix` — AI commits fixes directly to your PR branch
- `/generate-tests` — AI creates and commits test files
- `/ask` — chat with the reviewer about any PR change
- 35+ built-in SAST security rules (zero LLM cost)
- Declarative rules engine (team-specific YAML rules)
- PR complexity scoring (1-100, algorithmic, free)
- Slack, Discord, and Teams notifications
- GitHub Actions + GitLab CI + Bitbucket Pipelines + VS Code
- Self-hosted mode with RAG-powered codebase understanding
- Reviews in 15 languages
- $0.002/review with Groq's free tier

**Topics:** Developer Tools, GitHub, Open Source, Artificial Intelligence, Code Review

**Makers comment (first comment):**
Hey PH! I built AI Code Reviewer because I was tired of paying $19/user/month for AI code reviews that I couldn't customize.

The existing tools are great, but they lock you into their models, their pricing, and their way of reviewing code.

So I built an open-source alternative that gives you FULL control:

**Choose your LLM** — GPT-4o? Claude? Llama on Groq for $0.002/review? Local Ollama for $0.00? Your choice.

**Choose your reviewer's personality** — `persona: security-hawk` for fintech, `persona: mentor` for junior devs, `persona: quick-scan` for large PRs.

**Features no competitor has:**
1. `/fix` — AI reads review comments and commits fixes to your branch
2. `/generate-tests` — AI creates test files and commits them
3. 35+ SAST security rules that run for FREE (no LLM needed)
4. Declarative rules engine — codify your team's conventions in YAML
5. PR complexity scoring — nudge teams toward smaller, reviewable PRs

**Switching from CodeRabbit?** We have a [5-minute migration guide](https://github.com/mara-werils/ai-code-reviewer/blob/main/docs/migrate/from-coderabbit.md).

Would love your feedback. What would make this a must-have for your team?

---

## Launch Checklist

- [ ] Schedule for Tuesday or Wednesday (best PH days)
- [ ] Post at 12:01 AM PST (when the day starts on PH)
- [ ] Have 5+ screenshots/GIFs ready:
  - [ ] Review summary with risk level
  - [ ] Inline comments with suggestion blocks
  - [ ] /fix command in action
  - [ ] Security scanner findings
  - [ ] Persona comparison (default vs security-hawk)
- [ ] Prepare a demo video (2-3 min)
- [ ] Alert community (Discord, Twitter, Reddit) day-of
- [ ] Cross-post to r/programming, r/devtools, r/opensource
- [ ] Respond to every comment within 1 hour
- [ ] Prepare answers for common questions:
  - "How is this different from CodeRabbit?" → Migration guide link
  - "Is my code safe?" → Explain LLM choice + Ollama local option
  - "Does it work with private repos?" → Yes, uses GITHUB_TOKEN
  - "What about cost?" → $0.002 with Groq, $0.00 with Ollama
