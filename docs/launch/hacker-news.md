# Hacker News Show HN Post

## Title (80 chars max)

```
Show HN: AI Code Reviewer – Free, open-source, works with any LLM (GPT/Claude/Llama)
```

## Body

```
I built an open-source AI code review tool for GitHub pull requests (and GitLab MRs).

The problem: existing AI code review tools cost $19/user/month and lock you into their LLM.

AI Code Reviewer:
- Free and open source (MIT)
- Works with any LLM: GPT-4o, Claude, Llama 3.3, Gemini, or 100% local via Ollama
- Sets up in 30 seconds: add one YAML file, no config needed
- Costs ~$0.002/review using Groq's Llama 3.3 (free tier available)
- Posts inline comments with severity levels and suggested fixes (one-click apply)
- On-demand: type /review in any PR comment to trigger a review
- GitLab CI support (not just GitHub)
- Self-hosted option with RAG-powered codebase understanding

GitHub Action setup:

    - uses: mara-werils/ai-code-reviewer@v1
      env:
        OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}

Tech stack: Python, httpx, supports OpenAI/Anthropic/Groq/Google/Ollama SDKs. Self-hosted mode uses FastAPI + LangGraph + pgvector + Redis.

GitHub: https://github.com/mara-werils/ai-code-reviewer

I'd love feedback on the review quality and what features would make this useful for your team.
```

## Timing

- Best days: weekdays (Tue-Thu)
- Best time: 8-9 AM EST (when US east coast wakes up)
- Avoid weekends and holidays

## Expected Questions & Answers

**Q: How is this different from PR-Agent/CodeRabbit/Copilot?**
A: Multi-LLM support (switch with one line), much cheaper ($0.002 vs $0.05+ per review), /review command for on-demand, GitLab support, and a self-hosted mode with actual codebase understanding via AST indexing and vector search.

**Q: Why not just use GitHub Copilot's review?**
A: Copilot locks you to their model and pricing. This lets you choose your LLM, run locally for privacy, and costs a fraction of the price.

**Q: Is the code sent to OpenAI/Anthropic?**
A: Your code goes to whichever LLM you choose. For full privacy, use Ollama — nothing leaves your machine.

**Q: How accurate are the reviews?**
A: Depends on the model. GPT-4o and Claude produce excellent reviews. Groq's Llama 3.3 70B is surprisingly good for the price. We're working on benchmarks.

**Q: Will you add Bitbucket?**
A: It's on the roadmap. GitHub and GitLab are done.
