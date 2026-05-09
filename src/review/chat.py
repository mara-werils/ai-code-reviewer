"""PR Chat engine — interactive conversations within pull requests.

Supports two modes:
1. Inline thread reply — developer replies to a bot review comment
2. PR-level /ask — developer asks a question about the whole PR
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.config import ReviewConfig
from src.github.client import GitHubAPI, PRFile, PRInfo
from src.providers import LLMProvider, create_provider
from src.review.analyzer import build_diff_text, build_files_summary, filter_files
from src.review.prompts import CHAT_INLINE_PROMPT, CHAT_PR_PROMPT, CHAT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Bot markers to identify our own comments
_BOT_MARKERS = ("**[CRITICAL]", "**[WARNING]", "**[SUGGESTION]", "**[INFO]", "## AI Code Review")

_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".c": "c",
    ".swift": "swift",
    ".kt": "kotlin",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".sh": "bash",
}


@dataclass
class ChatResponse:
    """Result of a chat interaction."""

    body: str
    cost_usd: float
    model: str
    input_tokens: int
    output_tokens: int


def _detect_language(path: str) -> str:
    for ext, lang in _EXT_TO_LANG.items():
        if path.endswith(ext):
            return lang
    return ""


def _build_thread_history(thread: list[dict], bot_username: str) -> str:
    """Format a comment thread into a readable conversation."""
    parts: list[str] = []
    for c in thread:
        user = c.get("user", {}).get("login", "unknown")
        body = c.get("body", "")
        is_bot = user == bot_username or user.endswith("[bot]")
        role = "🤖 AI Reviewer" if is_bot else f"👤 @{user}"
        parts.append(f"**{role}:**\n{body}")
    return "\n\n---\n\n".join(parts)


def _is_bot_comment(comment: dict, bot_username: str) -> bool:
    """Check if a comment was posted by our bot."""
    user = comment.get("user", {}).get("login", "")
    if user == bot_username or user.endswith("[bot]"):
        return True
    body = comment.get("body", "")
    return any(marker in body for marker in _BOT_MARKERS)


class ChatEngine:
    """Handles interactive conversations in PR comment threads."""

    def __init__(self, config: ReviewConfig) -> None:
        self.config = config
        self.provider: LLMProvider = create_provider(config)

    async def reply_to_thread(
        self,
        github: GitHubAPI,
        repo: str,
        pr: PRInfo,
        comment_id: int,
        user_message: str,
        bot_username: str,
    ) -> ChatResponse:
        """Generate a reply to an inline review comment thread.

        Fetches the full thread history, the file content and diff,
        then generates a contextual response.
        """
        # Get thread context
        thread = await github.get_review_comment_thread(repo, pr.number, comment_id)

        # Get the root comment to find the file path
        root = thread[0] if thread else await github.get_review_comment(repo, comment_id)
        file_path = root.get("path", "")

        # Fetch file content for full context
        file_content = ""
        if file_path:
            file_content = await github.get_file_content(repo, file_path, pr.head_ref)

        # Get the file diff
        file_diff = root.get("diff_hunk", "")

        # Build thread history (exclude the latest user message — it's separate)
        history_thread = thread[:-1] if len(thread) > 1 else thread
        thread_history = _build_thread_history(history_thread, bot_username)

        language = _detect_language(file_path)

        # Truncate file content if too large
        max_file_size = 15000
        if len(file_content) > max_file_size:
            file_content = file_content[:max_file_size] + "\n... (truncated)"

        custom = ""
        if self.config.custom_instructions:
            custom = f"\n## Additional Instructions\n{self.config.custom_instructions}"

        system = CHAT_SYSTEM_PROMPT.format(custom_instructions=custom)
        user_prompt = CHAT_INLINE_PROMPT.format(
            title=pr.title,
            author=pr.author,
            file_path=file_path,
            language=language,
            file_content=file_content,
            file_diff=file_diff,
            thread_history=thread_history,
            user_message=user_message,
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ]

        response = await self.provider.complete(
            messages=messages,
            temperature=0.2,
            max_tokens=2048,
        )

        return ChatResponse(
            body=response.content,
            cost_usd=response.cost_usd,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

    async def answer_question(
        self,
        pr: PRInfo,
        files: list[PRFile],
        diff: str,
        user_message: str,
    ) -> ChatResponse:
        """Answer a PR-level question (/ask command).

        Uses the full PR diff as context.
        """
        filtered = filter_files(files, self.config.ignore_paths)
        if not diff:
            diff = build_diff_text(filtered, max_size=self.config.max_diff_size)
        else:
            diff = diff[: self.config.max_diff_size]

        files_summary = build_files_summary(filtered)

        custom = ""
        if self.config.custom_instructions:
            custom = f"\n## Additional Instructions\n{self.config.custom_instructions}"

        system = CHAT_SYSTEM_PROMPT.format(custom_instructions=custom)
        user_prompt = CHAT_PR_PROMPT.format(
            title=pr.title,
            author=pr.author,
            body=(pr.body or "No description")[:2000],
            files_summary=files_summary,
            diff=diff,
            user_message=user_message,
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ]

        response = await self.provider.complete(
            messages=messages,
            temperature=0.2,
            max_tokens=2048,
        )

        return ChatResponse(
            body=response.content,
            cost_usd=response.cost_usd,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )


def format_chat_response(response: ChatResponse) -> str:
    """Format a chat response with a subtle footer."""
    parts = [
        response.body,
        "",
        "---",
        f"<sub>${response.cost_usd:.4f} | {response.model} | "
        f"[AI Code Reviewer](https://github.com/mara-werils/ai-code-reviewer)</sub>",
    ]
    return "\n".join(parts)
