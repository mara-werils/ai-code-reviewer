"""Tests for the GitLab API client."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from src.gitlab.client import GitLabAPI


@pytest.fixture
def gitlab() -> GitLabAPI:
    return GitLabAPI(token="test-token", base_url="https://gitlab.example.com")


class TestGitLabAPI:
    @respx.mock
    @pytest.mark.asyncio
    async def test_get_mr(self, gitlab: GitLabAPI) -> None:
        respx.get("https://gitlab.example.com/api/v4/projects/group%2Frepo/merge_requests/1").mock(
            return_value=Response(
                200,
                json={
                    "iid": 1,
                    "title": "Add feature",
                    "description": "A new feature",
                    "sha": "abc123",
                    "diff_refs": {
                        "base_sha": "def456",
                        "head_sha": "abc123",
                        "start_sha": "def456",
                    },
                    "target_branch": "main",
                    "source_branch": "feature-branch",
                    "author": {"username": "dev"},
                },
            )
        )

        pr = await gitlab.get_mr("group/repo", 1)
        assert pr.number == 1
        assert pr.title == "Add feature"
        assert pr.head_sha == "abc123"
        assert pr.base_sha == "def456"
        assert pr.author == "dev"
        assert pr.head_ref == "feature-branch"
        assert pr.base_ref == "main"

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_mr_files(self, gitlab: GitLabAPI) -> None:
        respx.get(
            "https://gitlab.example.com/api/v4/projects/group%2Frepo/merge_requests/1/changes"
        ).mock(
            return_value=Response(
                200,
                json={
                    "changes": [
                        {
                            "old_path": "src/main.py",
                            "new_path": "src/main.py",
                            "new_file": False,
                            "deleted_file": False,
                            "renamed_file": False,
                            "diff": "@@ -1,3 +1,4 @@\n import os\n+import sys\n \n def main():\n",
                        },
                        {
                            "old_path": "tests/test_new.py",
                            "new_path": "tests/test_new.py",
                            "new_file": True,
                            "deleted_file": False,
                            "renamed_file": False,
                            "diff": "@@ -0,0 +1,5 @@\n+def test_something():\n+    pass\n",
                        },
                    ],
                },
            )
        )

        files = await gitlab.get_mr_files("group/repo", 1)
        assert len(files) == 2
        assert files[0].filename == "src/main.py"
        assert files[0].status == "modified"
        assert files[1].filename == "tests/test_new.py"
        assert files[1].status == "added"

    @respx.mock
    @pytest.mark.asyncio
    async def test_post_mr_note(self, gitlab: GitLabAPI) -> None:
        respx.post(
            "https://gitlab.example.com/api/v4/projects/group%2Frepo/merge_requests/1/notes"
        ).mock(return_value=Response(201, json={"id": 42}))

        note_id = await gitlab.post_mr_note("group/repo", 1, "Review comment")
        assert note_id == 42

    @respx.mock
    @pytest.mark.asyncio
    async def test_post_inline_comments(self, gitlab: GitLabAPI) -> None:
        respx.post(
            "https://gitlab.example.com/api/v4/projects/group%2Frepo/merge_requests/1/discussions"
        ).mock(return_value=Response(201, json={"id": "disc-1"}))

        comments = [
            {"path": "src/main.py", "line": 5, "body": "Bug here"},
            {"path": "src/utils.py", "line": 10, "body": "Missing check"},
        ]
        posted = await gitlab.post_inline_comments("group/repo", 1, "abc123", "def456", comments)
        assert posted == 2

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_file_content(self, gitlab: GitLabAPI) -> None:
        respx.get(
            "https://gitlab.example.com/api/v4/projects/group%2Frepo/repository/files/src%2Fmain.py/raw"
        ).mock(return_value=Response(200, text="print('hello')"))

        content = await gitlab.get_file_content("group/repo", "src/main.py", "main")
        assert content == "print('hello')"

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_file_content_not_found(self, gitlab: GitLabAPI) -> None:
        respx.get(
            "https://gitlab.example.com/api/v4/projects/group%2Frepo/repository/files/missing.py/raw"
        ).mock(return_value=Response(404))

        content = await gitlab.get_file_content("group/repo", "missing.py", "main")
        assert content == ""

    def test_encode_project(self) -> None:
        assert GitLabAPI._encode_project("group/repo") == "group%2Frepo"
        assert GitLabAPI._encode_project("org/sub/repo") == "org%2Fsub%2Frepo"

    @respx.mock
    @pytest.mark.asyncio
    async def test_add_labels(self, gitlab: GitLabAPI) -> None:
        respx.get("https://gitlab.example.com/api/v4/projects/group%2Frepo/merge_requests/1").mock(
            return_value=Response(200, json={"labels": ["existing"]})
        )
        respx.put("https://gitlab.example.com/api/v4/projects/group%2Frepo/merge_requests/1").mock(
            return_value=Response(200, json={})
        )

        await gitlab.add_labels("group/repo", 1, ["new-label"])
        # Verify the PUT was called (no exception = success)
