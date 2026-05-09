"""Tests for the Bitbucket Cloud API client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bitbucket.client import BitbucketAPI, _parse_diff_patches
from src.github.client import PRFile, PRInfo


class TestParseDiffPatches:
    def test_single_file(self) -> None:
        diff = (
            "diff --git a/src/main.py b/src/main.py\n"
            "@@ -1,3 +1,4 @@\n"
            " existing\n"
            "+new line\n"
            " more existing\n"
        )
        patches = _parse_diff_patches(diff)
        assert "src/main.py" in patches
        assert "+new line" in patches["src/main.py"]

    def test_multiple_files(self) -> None:
        diff = (
            "diff --git a/a.py b/a.py\n"
            "@@ -1,3 +1,4 @@\n"
            "+line a\n"
            "diff --git a/b.py b/b.py\n"
            "@@ -1,3 +1,4 @@\n"
            "+line b\n"
        )
        patches = _parse_diff_patches(diff)
        assert len(patches) == 2
        assert "a.py" in patches
        assert "b.py" in patches

    def test_empty_diff(self) -> None:
        assert _parse_diff_patches("") == {}

    def test_no_hunks(self) -> None:
        diff = "diff --git a/empty.py b/empty.py\n"
        patches = _parse_diff_patches(diff)
        assert patches.get("empty.py", "") == ""


class TestBitbucketAPI:
    @pytest.fixture
    def mock_client(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def api(self, mock_client: AsyncMock) -> BitbucketAPI:
        api = BitbucketAPI("user", "pass")
        api._client = mock_client
        return api

    @pytest.mark.asyncio
    async def test_get_pr(self, api: BitbucketAPI, mock_client: AsyncMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "id": 42,
            "title": "Add feature",
            "description": "New feature",
            "source": {
                "branch": {"name": "feature/x"},
                "commit": {"hash": "abc123"},
            },
            "destination": {
                "branch": {"name": "main"},
                "commit": {"hash": "def456"},
            },
            "author": {"display_name": "Dev", "nickname": "dev"},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        pr = await api.get_pr("myteam", "myrepo", 42)

        assert isinstance(pr, PRInfo)
        assert pr.number == 42
        assert pr.title == "Add feature"
        assert pr.head_sha == "abc123"
        assert pr.base_ref == "main"
        assert pr.head_ref == "feature/x"
        assert pr.author == "Dev"
        assert pr.repo_full_name == "myteam/myrepo"

    @pytest.mark.asyncio
    async def test_get_pr_diff(self, api: BitbucketAPI, mock_client: AsyncMock) -> None:
        mock_resp = MagicMock()
        mock_resp.text = "diff --git a/f.py b/f.py\n@@ +1 @@\n+code"
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        diff = await api.get_pr_diff("team", "repo", 1)
        assert "diff --git" in diff

    @pytest.mark.asyncio
    async def test_post_comment(self, api: BitbucketAPI, mock_client: AsyncMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": 999}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp

        comment_id = await api.post_comment("team", "repo", 1, "Great PR!")

        assert comment_id == 999
        call_args = mock_client.post.call_args
        assert "content" in call_args.kwargs.get("json", call_args[1].get("json", {}))

    @pytest.mark.asyncio
    async def test_post_inline_comments(self, api: BitbucketAPI, mock_client: AsyncMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_client.post.return_value = mock_resp

        comments = [
            {"path": "src/api.py", "line": 10, "body": "Bug here"},
            {"path": "src/db.py", "line": 20, "body": "SQL issue"},
        ]
        posted = await api.post_inline_comments("team", "repo", 1, comments)
        assert posted == 2

    @pytest.mark.asyncio
    async def test_post_inline_comment_failure(self, api: BitbucketAPI, mock_client: AsyncMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad request"
        mock_client.post.return_value = mock_resp

        posted = await api.post_inline_comments(
            "team", "repo", 1,
            [{"path": "f.py", "line": 1, "body": "test"}],
        )
        assert posted == 0

    @pytest.mark.asyncio
    async def test_get_file_content(self, api: BitbucketAPI, mock_client: AsyncMock) -> None:
        mock_resp = MagicMock()
        mock_resp.text = "def hello():\n    print('hi')\n"
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        content = await api.get_file_content("team", "repo", "main.py", "abc123")
        assert "def hello" in content

    @pytest.mark.asyncio
    async def test_get_file_content_404(self, api: BitbucketAPI, mock_client: AsyncMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_client.get.return_value = mock_resp

        content = await api.get_file_content("team", "repo", "missing.py", "abc123")
        assert content == ""

    @pytest.mark.asyncio
    async def test_close(self, api: BitbucketAPI, mock_client: AsyncMock) -> None:
        await api.close()
        mock_client.aclose.assert_called_once()
