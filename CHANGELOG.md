# Changelog

All notable changes to this project will be documented in this file.

## [0.5.0] - 2026-05-15

### Added
- **Review personas** — 6 built-in reviewer personalities (security-hawk, mentor, nitpicker, quick-scan, dora)
  - Configurable via `.pr-reviewer.yml` (`persona: security-hawk`) or action input
  - Each persona bundles review style, priorities, tone, and max comments
  - 11 tests for persona system
- **PR complexity scoring** — algorithmic 1-100 score based on 6 metrics
  - Size, spread, language mix, coupling, sensitive files, code churn
  - Zero LLM cost — instant, deterministic
  - 12 tests for complexity scoring
- **15 new SAST security rules** — now 35+ built-in rules
  - Path traversal, timing attacks, prototype pollution, open redirect, XXE, ReDoS
  - JWT secrets, mass assignment, file upload, CSRF, insecure cookies, log leaks
  - TypeScript `any` abuse, Go defer-in-loop
- **Slack/Discord/Microsoft Teams notifications**
  - Webhook-based alerts when risk level exceeds threshold
  - Rich formatting with risk colors, comment counts, direct PR links
  - 7 tests for notification system
- **Diff-aware review cache** — skip unchanged files on subsequent pushes
  - SHA-256 patch hashing, per-PR cache at `~/.pr-reviewer/cache/`
  - Can reduce LLM costs 30-70% on iterative PRs
  - 8 tests for cache system
- **Review quality benchmark suite** — golden dataset with 8 test cases
  - Automated recall/precision measurement for security scanner
  - CI workflow posts benchmark results on security rule changes
- **Setup wizard** (`pr-reviewer init`) — interactive config generator
  - Generates `.pr-reviewer.yml` and workflow YAML
  - Auto-detects frameworks (Next.js, venv) for smart ignore paths
- **CLI improvements** — `--dry-run`, `--persona`, `--json` output flags
- **Rule packs** — ready-to-use YAML rules for Django, React, and Go
- **15-language support** — added Chinese Traditional, Brazilian Portuguese, Italian, Turkish, Polish, Dutch, Arabic (10 tests)
- **Migration guides** from CodeRabbit and PR-Agent with config translation
- **GitHub Discussion templates** for show-and-tell and custom rules
- **Improved issue templates** with dropdown selectors for platform, provider, command
- **Blog post** — "Best Free AI Code Review Tools in 2026" comparison
- **Reddit launch posts** for r/programming, r/devops, r/selfhosted
- **Updated Product Hunt listing** with all new features
- **Repository settings** with 20 GitHub topics for discoverability
- **Benchmark CI workflow** for automatic regression detection

### Changed
- Bumped version to 0.5.0 (Production/Stable)
- Expanded PyPI keywords for SEO (18 keywords)
- Updated README with new feature sections and comparison table
- Rewritten CONTRIBUTING.md with contribution paths
- Updated example `.pr-reviewer.yml` with all new options
- Removed unused `src/context/` and `src/server/` directories

### Stats
- **73 new tests** (total: ~190)
- **10 new source files** added
- **15 new security rules**
- **3 rule packs** for popular stacks

## [0.4.0] - 2026-05-08

### Added
- **VS Code extension** — review files, selections, and uncommitted changes directly in the editor
  - Inline diagnostics in Problems panel with severity levels
  - Status bar with review progress and cost tracking
  - Keyboard shortcuts: `Cmd+Shift+R` (review file), `Cmd+Shift+D` (review diff)
  - Right-click context menu for selection review
  - Auto-review on save (optional)
  - All providers supported (OpenAI, Anthropic, Groq, Google, Ollama)
- **GitLab CI integration** — review merge requests with `--platform gitlab`
  - Full GitLab API client (MR info, inline comments, discussions, labels)
  - GitLab CI template (`examples/gitlab-ci.yml`)
  - Self-hosted GitLab support via `GITLAB_URL`
- **On-demand `/review` command** — type `/review` in any PR comment to trigger a review
  - Emoji reaction feedback (eyes on start, rocket on success)
  - Works alongside automatic reviews
- **Viral review footer** — branded badge with CTA in every review comment
- **SEO blog posts** — CodeRabbit alternative comparison, free AI code review guide
- **Launch materials** — Product Hunt, Hacker News, Twitter thread, awesome-lists plan
- **Community setup** — Discord badge, FUNDING.yml for GitHub Sponsors
- **8 new unit tests** for GitLab client (117 total, all passing)

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
