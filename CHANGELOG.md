# Changelog

All notable changes to this project will be documented in this file.

## [0.3.0] - 2026-05-06

### Added
- Real demo screenshots in README (summary + inline comments)
- AI review workflow for self-testing (`ai-review.yml`)
- Fallback to individual inline comments when batch review fails

### Fixed
- Inline review comments now use diff position instead of file line number
- Path matching for LLM responses with partial file paths
- Context lines included in valid comment targets
- All mypy strict mode errors resolved (37 errors across 12 files)
- Ruff formatting applied to all 29 unformatted files

## [0.2.0] - 2026-05-06

### Added
- GitHub Action with Docker-based execution
- Multi-provider LLM support (OpenAI, Anthropic, Groq, Google, Ollama)
- CLI tool for local and CI usage (`pr-reviewer review`)
- Custom instructions via `.pr-reviewer.yml`
- Multi-language review comments (9 languages)
- PR auto-labeling
- Test suggestion detection
- Duplicate review detection (skip if same commit already reviewed)

### Changed
- Transformed from standalone app to GitHub Action
- Updated all references to mara-werils/ai-code-reviewer

## [0.1.0] - 2026-05-06

### Added
- Initial implementation
- FastAPI self-hosted server with webhook handling
- AST-based code chunking (Python, JS/TS via tree-sitter)
- Hybrid retrieval with pgvector embeddings
- LangGraph agentic review pipeline
- Redis queue for async review processing
- Analytics dashboard with Chart.js
- Feedback loop from developer reactions
- SSE streaming for real-time review progress
