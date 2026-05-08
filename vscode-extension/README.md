# AI Code Reviewer — VS Code Extension

AI-powered code review directly in your editor. Works with any LLM: GPT-4o, Claude, Llama, Gemini, Ollama.

## Features

- **Review Current File** (`Cmd+Shift+R` / `Ctrl+Shift+R`) — AI reviews the active file and shows issues in the Problems panel
- **Review Uncommitted Changes** (`Cmd+Shift+D` / `Ctrl+Shift+D`) — Reviews your git diff before you commit
- **Review Selection** — Right-click selected code for targeted review
- **Auto-Review on Save** — Optional: automatically review files when you save
- **Any LLM** — GPT-4o, Claude, Llama 3.3 (Groq), Gemini, Ollama (local, free)
- **Inline Diagnostics** — Issues appear directly in VS Code's Problems panel with severity levels

## Quick Start

1. Install the extension
2. Open Settings and search for "AI Code Reviewer"
3. Set your provider and API key
4. Open a file and press `Cmd+Shift+R` (Mac) or `Ctrl+Shift+R` (Windows/Linux)

### Cheapest Setup (Groq — $0.002/review)

1. Get a free API key at [console.groq.com](https://console.groq.com)
2. Set provider to `groq`
3. Paste your API key

### Free Setup (Ollama — $0.00/review)

1. Install [Ollama](https://ollama.ai) and pull a model: `ollama pull llama3.1:8b`
2. Set provider to `ollama`
3. Leave API key empty

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `provider` | `openai` | LLM provider (openai, anthropic, groq, google, ollama) |
| `model` | auto | Model name (auto-selected per provider) |
| `apiKey` | — | API key (or use env vars) |
| `apiBaseUrl` | — | Custom API URL (for Ollama, vLLM, etc.) |
| `reviewStyle` | `concise` | Review style (concise, thorough, minimal) |
| `maxComments` | `15` | Maximum comments per review |
| `language` | `en` | Review language (en, zh, ja, ko, es, de, fr, ru, pt) |
| `customInstructions` | — | Team conventions and coding standards |
| `autoReviewOnSave` | `false` | Auto-review on save (experimental) |

## Commands

| Command | Keybinding | Description |
|---------|-----------|-------------|
| Review Current File | `Cmd+Shift+R` | Review the active file |
| Review Uncommitted Changes | `Cmd+Shift+D` | Review git diff |
| Review Selection | Right-click menu | Review selected code |
| Clear Review Comments | Command palette | Clear all diagnostics |

## How It Works

1. The extension sends your code to the selected LLM provider
2. The AI analyzes it for bugs, security issues, and design problems
3. Results appear as VS Code diagnostics in the Problems panel
4. Each issue has a severity level: Error (critical), Warning, Info (suggestion), Hint

## Privacy

Your code is sent only to the LLM provider you choose. Use Ollama for 100% local reviews where nothing leaves your machine.

## Part of AI Code Reviewer

This extension is part of the [AI Code Reviewer](https://github.com/mara-werils/ai-code-reviewer) project, which also includes:
- **GitHub Action** — Automated PR reviews
- **GitLab CI** — MR reviews
- **CLI** — `pr-reviewer review` from your terminal
- **Self-hosted** — Full RAG-powered review with Docker Compose

## License

MIT
