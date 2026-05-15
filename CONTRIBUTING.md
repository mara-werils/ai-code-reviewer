# Contributing to AI Code Reviewer

Thanks for your interest! Whether it's a bug fix, new feature, or documentation improvement — we appreciate every contribution.

**Community**: [Discord](https://discord.gg/ai-code-reviewer) | [GitHub Discussions](https://github.com/mara-werils/ai-code-reviewer/discussions)

## Quick Start (5 minutes)

```bash
# 1. Fork and clone
git clone https://github.com/YOUR_USERNAME/ai-code-reviewer.git
cd ai-code-reviewer

# 2. Install in development mode
pip install -e ".[dev]"

# 3. Run tests
pytest tests/ -v

# 4. Check code quality
ruff check . && ruff format --check .
```

## Good First Issues

Look for issues labeled [`good first issue`](https://github.com/mara-werils/ai-code-reviewer/labels/good%20first%20issue). These are specifically curated for newcomers. Examples:

- Add a new security rule to `src/review/security.py`
- Add a new rule pack to `examples/rules/`
- Improve test coverage for an existing module
- Add a new LLM provider
- Translate review prompts to a new language

## Project Structure

```
src/                        # Lightweight action + CLI (no heavy deps)
├── action.py               # GitHub Action entrypoint
├── cli.py                  # CLI tool (pr-reviewer review, pr-reviewer init)
├── config.py               # Configuration management
├── wizard.py               # Interactive setup wizard
├── notifications.py        # Slack/Discord/Teams webhooks
├── providers/              # LLM providers (OpenAI, Anthropic, Groq, etc.)
├── github/                 # GitHub API client
├── gitlab/                 # GitLab API client
├── bitbucket/              # Bitbucket API client
├── dashboard/              # Analytics dashboard + report cards
└── review/                 # Core review engine
    ├── engine.py           # Main review logic
    ├── analyzer.py         # Diff parsing and file filtering
    ├── formatter.py        # GitHub markdown output
    ├── prompts.py          # All prompts (versioned)
    ├── security.py         # SAST scanner (35+ rules)
    ├── rules.py            # Declarative YAML rules engine
    ├── personas.py         # Review personas (security-hawk, mentor, etc.)
    ├── complexity.py       # PR complexity scoring
    ├── cache.py            # Diff-aware review cache
    ├── i18n.py             # Language support (15 languages)
    ├── chat.py             # PR chat (/ask, thread replies)
    ├── fixer.py            # /fix command
    ├── test_generator.py   # /generate-tests command
    ├── feedback.py         # Learn from reactions
    ├── monorepo.py         # Monorepo impact analysis
    └── multi_repo.py       # Cross-repo impact warnings

app/                        # Self-hosted mode (FastAPI + PostgreSQL + Redis)
├── services/
│   ├── indexer/            # AST-based code chunking
│   ├── reviewer/           # LangGraph agentic review
│   └── retrieval_service/  # Hybrid search (vector + identifier)
└── ...

tests/                      # 140+ tests
├── unit/                   # Fast, no external deps
├── integration/            # Requires services
├── eval/                   # Review quality benchmarks
└── fixtures/               # Test data
```

## Guidelines

### Code
- Write tests for new features — PR won't be merged without them
- Run `ruff check . && ruff format --check .` before committing
- Keep the GitHub Action lightweight — heavy deps go in `app/` with the `selfhosted` extra
- Prompts live in `src/review/prompts.py` — version them when changing
- Add provider tests that mock the client (no API keys needed)

### Commits
- Use conventional commit messages: `feat:`, `fix:`, `test:`, `docs:`, `chore:`
- One logical change per commit
- Keep PR scope focused — split large changes into multiple PRs

### PRs
- Fill out the PR template
- Link related issues with `Fixes #123`
- Add screenshots for UI changes
- Update CHANGELOG.md for user-facing changes

## Common Contribution Paths

### Adding a New Security Rule

1. Add a `SecurityRule` to `src/review/security.py`
2. Follow the naming convention: `SEC{category}{number}`
3. Add a test case to `tests/unit/test_security_scanner.py`
4. Add a sample to `tests/eval/golden_dataset/samples.json`
5. Run the benchmark: `python -m tests.eval.bench`

### Adding a New LLM Provider

1. Create `src/providers/your_provider.py` implementing `LLMProvider`
2. Add it to `src/providers/factory.py`
3. Add default model and pricing in `src/config.py`
4. Add a test in `tests/unit/test_providers.py` (mock the API)
5. Update README with provider info and example YAML

### Adding a New Rule Pack

1. Create `examples/rules/your-stack.yml`
2. Follow the format of existing packs (`python-django.yml`, etc.)
3. Include 5-10 practical rules for the stack
4. Test manually: copy to `.pr-reviewer-rules.yml` and run `pytest tests/unit/test_rules.py`

### Adding a New Review Persona

1. Add a `Persona` in `src/review/personas.py` using `_register()`
2. Write a clear system addendum that changes the reviewer's behavior
3. Add a test in `tests/unit/test_personas.py`
4. Add the name to the CLI `--persona` choices in `src/cli.py`

## Questions?

- Open a [Discussion](https://github.com/mara-werils/ai-code-reviewer/discussions) for general questions
- Join [Discord](https://discord.gg/ai-code-reviewer) for real-time chat
- File an [Issue](https://github.com/mara-werils/ai-code-reviewer/issues) for bugs
