# Contributing

Thanks for considering contributing! Here's how to get started.

Join the community: [Discord](https://discord.gg/YOUR_INVITE_LINK) | [GitHub Discussions](https://github.com/mara-werils/ai-code-reviewer/discussions)

## Development Setup

```bash
git clone https://github.com/mara-werils/ai-code-reviewer.git
cd ai-code-reviewer
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest tests/ -v
ruff check .
```

## Project Structure

```
src/                    # Lightweight action + CLI (no heavy deps)
├── action.py           # GitHub Action entrypoint
├── cli.py              # CLI tool
├── config.py           # Configuration management
├── providers/          # LLM providers (OpenAI, Anthropic, Groq, etc.)
├── github/             # GitHub API client
├── gitlab/             # GitLab API client
└── review/             # Core review engine
    ├── engine.py       # Main review logic
    ├── analyzer.py     # Diff analysis
    ├── formatter.py    # Output formatting
    └── prompts.py      # All prompts (versioned)

app/                    # Self-hosted mode (FastAPI + PostgreSQL + Redis)
├── services/
│   ├── indexer/        # AST-based code chunking
│   ├── reviewer/       # LangGraph agentic review
│   └── retrieval/      # Hybrid search (vector + identifier)
└── ...
```

## Guidelines

- Write tests for new features
- Run `ruff check .` before committing
- Keep the GitHub Action lightweight — heavy deps go in `app/`
- Prompts live in `src/review/prompts.py` — version them when changing
- Add provider tests that don't require API keys (mock the client)

## Adding a New Provider

1. Create `src/providers/your_provider.py` implementing `LLMProvider`
2. Add it to `src/providers/factory.py`
3. Add default model/pricing
4. Add a test in `tests/unit/test_providers.py`
5. Update README with provider info
