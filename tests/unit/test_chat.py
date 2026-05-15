"""Tests for the PR chat engine."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.review.chat import (
    ChatEngine,
    ChatResponse,
    _build_thread_history,
    _detect_language,
    _is_bot_comment,
    format_chat_response,
)


class TestDetectLanguage:
    def test_python(self) -> None:
        assert _detect_language("src/main.py") == "python"

    def test_typescript(self) -> None:
        assert _detect_language("app/index.ts") == "typescript"

    def test_go(self) -> None:
        assert _detect_language("cmd/server.go") == "go"

    def test_unknown(self) -> None:
        assert _detect_language("Makefile") == ""


class TestBuildThreadHistory:
    def test_single_bot_comment(self) -> None:
        thread = [
            {
                "user": {"login": "github-actions[bot]"},
                "body": "**[WARNING]** Missing null check",
            }
        ]
        result = _build_thread_history(thread, "github-actions[bot]")
        assert "AI Reviewer" in result
        assert "Missing null check" in result

    def test_conversation(self) -> None:
        thread = [
            {
                "user": {"login": "github-actions[bot]"},
                "body": "**[WARNING]** Missing null check",
            },
            {
                "user": {"login": "developer"},
                "body": "Why is this needed?",
            },
        ]
        result = _build_thread_history(thread, "github-actions[bot]")
        assert "AI Reviewer" in result
        assert "@developer" in result
        assert "Why is this needed?" in result

    def test_empty_thread(self) -> None:
        result = _build_thread_history([], "bot")
        assert result == ""


class TestIsBotComment:
    def test_bot_by_username(self) -> None:
        comment = {"user": {"login": "github-actions[bot]"}, "body": "hello"}
        assert _is_bot_comment(comment, "github-actions[bot]") is True

    def test_bot_by_marker(self) -> None:
        comment = {"user": {"login": "some-user"}, "body": "## AI Code Review\nSummary"}
        assert _is_bot_comment(comment, "bot") is True

    def test_human_comment(self) -> None:
        comment = {"user": {"login": "developer"}, "body": "Looks good to me!"}
        assert _is_bot_comment(comment, "github-actions[bot]") is False


class TestFormatChatResponse:
    def test_format(self) -> None:
        response = ChatResponse(
            body="The null check is needed because `user` can be None when...",
            cost_usd=0.002,
            model="gpt-4o",
            input_tokens=500,
            output_tokens=100,
        )
        result = format_chat_response(response)
        assert "The null check is needed" in result
        assert "$0.0020" in result
        assert "gpt-4o" in result
        assert "AI Code Reviewer" in result


class TestChatEngine:
    @pytest.mark.asyncio
    async def test_reply_to_thread(self) -> None:
        from src.config import ReviewConfig
        from src.github.client import PRInfo
        from src.providers.base import LLMResponse

        config = ReviewConfig(
            provider="openai",
            api_key="test-key",
            github_token="test-token",
        )

        pr = PRInfo(
            number=1,
            title="Add user validation",
            body="Adds validation for user input",
            head_sha="abc123",
            base_sha="def456",
            base_ref="main",
            head_ref="feature/validation",
            repo_full_name="owner/repo",
            author="developer",
        )

        mock_github = AsyncMock()
        mock_github.get_review_comment_thread.return_value = [
            {
                "id": 100,
                "user": {"login": "github-actions[bot]"},
                "body": "**[WARNING]** Missing null check on line 42",
                "path": "src/api.py",
                "diff_hunk": "@@ -40,6 +40,8 @@\n+    user = get_user(id)\n+    return user.name",
                "created_at": "2025-01-01T00:00:00Z",
            },
            {
                "id": 101,
                "user": {"login": "developer"},
                "body": "Why is this needed? We validate upstream.",
                "path": "src/api.py",
                "diff_hunk": "@@ -40,6 +40,8 @@\n+    user = get_user(id)\n+    return user.name",
                "in_reply_to_id": 100,
                "created_at": "2025-01-01T01:00:00Z",
            },
        ]
        mock_github.get_review_comment.return_value = {
            "id": 100,
            "path": "src/api.py",
            "diff_hunk": "@@ -40,6 +40,8 @@\n+    user = get_user(id)\n+    return user.name",
        }
        mock_github.get_file_content.return_value = "def get_user(id):\n    return db.query(id)\n"

        mock_response = LLMResponse(
            content="The upstream validation only checks format, not existence. "
            "`get_user()` can return `None` if the user was deleted between validation and this call.",
            input_tokens=800,
            output_tokens=50,
            model="gpt-4o",
            cost_usd=0.003,
        )

        with patch.object(
            ChatEngine,
            "__init__",
            lambda self, cfg: (
                setattr(self, "config", cfg) or setattr(self, "provider", AsyncMock())
            ),
        ):
            engine = ChatEngine(config)
            engine.provider.complete = AsyncMock(return_value=mock_response)

            result = await engine.reply_to_thread(
                github=mock_github,
                repo="owner/repo",
                pr=pr,
                comment_id=100,
                user_message="Why is this needed? We validate upstream.",
                bot_username="github-actions[bot]",
            )

            assert "upstream validation" in result.body
            assert result.cost_usd == 0.003
            assert result.model == "gpt-4o"
            engine.provider.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_answer_question(self) -> None:
        from src.config import ReviewConfig
        from src.github.client import PRFile, PRInfo
        from src.providers.base import LLMResponse

        config = ReviewConfig(
            provider="openai",
            api_key="test-key",
            github_token="test-token",
        )

        pr = PRInfo(
            number=1,
            title="Add caching layer",
            body="Implements Redis caching",
            head_sha="abc123",
            base_sha="def456",
            base_ref="main",
            head_ref="feature/cache",
            repo_full_name="owner/repo",
            author="developer",
        )

        files = [
            PRFile(
                filename="src/cache.py",
                status="added",
                additions=50,
                deletions=0,
                patch="@@ -0,0 +1,50 @@\n+import redis",
            ),
        ]

        mock_response = LLMResponse(
            content="The TTL is set to 300 seconds (5 minutes) by default.",
            input_tokens=1000,
            output_tokens=30,
            model="gpt-4o",
            cost_usd=0.004,
        )

        with patch.object(
            ChatEngine,
            "__init__",
            lambda self, cfg: (
                setattr(self, "config", cfg) or setattr(self, "provider", AsyncMock())
            ),
        ):
            engine = ChatEngine(config)
            engine.provider.complete = AsyncMock(return_value=mock_response)

            result = await engine.answer_question(
                pr=pr,
                files=files,
                diff="@@ -0,0 +1,50 @@\n+import redis",
                user_message="What's the default TTL?",
            )

            assert "300 seconds" in result.body
            assert result.cost_usd == 0.004
