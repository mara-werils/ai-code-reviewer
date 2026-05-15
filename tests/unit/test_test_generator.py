"""Tests for the AI test generator."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.github.client import PRFile
from src.review.test_generator import (
    GeneratedTestResult,
    GeneratedTestSummary,
    _detect_language,
    _guess_test_path,
    _is_test_file,
    _is_testable_file,
    filter_testable_files,
    format_test_gen_comment,
)


class TestDetectLanguage:
    def test_python(self) -> None:
        assert _detect_language("src/main.py") == "python"

    def test_typescript(self) -> None:
        assert _detect_language("app/index.ts") == "typescript"

    def test_tsx(self) -> None:
        assert _detect_language("components/Button.tsx") == "typescript"

    def test_go(self) -> None:
        assert _detect_language("cmd/server.go") == "go"

    def test_java(self) -> None:
        assert _detect_language("src/main/java/App.java") == "java"

    def test_rust(self) -> None:
        assert _detect_language("src/lib.rs") == "rust"

    def test_unknown(self) -> None:
        assert _detect_language("Makefile") == ""

    def test_config_not_testable(self) -> None:
        assert _detect_language("config.yml") == ""


class TestIsTestFile:
    def test_python_test(self) -> None:
        assert _is_test_file("tests/test_main.py") is True

    def test_go_test(self) -> None:
        assert _is_test_file("pkg/handler_test.go") is True

    def test_js_spec(self) -> None:
        assert _is_test_file("src/utils.spec.ts") is True

    def test_jest_test(self) -> None:
        assert _is_test_file("src/__tests__/utils.test.js") is True

    def test_source_file(self) -> None:
        assert _is_test_file("src/main.py") is False

    def test_source_with_test_in_name(self) -> None:
        assert _is_test_file("src/test_utils_helper.py") is True


class TestIsTestableFile:
    def test_python_source(self) -> None:
        assert _is_testable_file("src/api.py") is True

    def test_test_file_not_testable(self) -> None:
        assert _is_testable_file("tests/test_api.py") is False

    def test_config_not_testable(self) -> None:
        assert _is_testable_file("config.yml") is False

    def test_lock_file_not_testable(self) -> None:
        assert _is_testable_file("package-lock.json") is False

    def test_migration_not_testable(self) -> None:
        assert _is_testable_file("alembic/versions/001_init.py") is False

    def test_markdown_not_testable(self) -> None:
        assert _is_testable_file("README.md") is False

    def test_generated_not_testable(self) -> None:
        assert _is_testable_file("api.generated.ts") is False

    def test_typescript_source(self) -> None:
        assert _is_testable_file("src/components/Button.tsx") is True

    def test_go_source(self) -> None:
        assert _is_testable_file("pkg/handler.go") is True

    def test_removed_file_handled(self) -> None:
        # Removed files are handled by filter_testable_files, not _is_testable_file
        assert _is_testable_file("src/old.py") is True


class TestGuessTestPath:
    def test_python_src(self) -> None:
        result = _guess_test_path("src/api/handlers.py", "python")
        assert result == "tests/unit/api/test_handlers.py"

    def test_python_no_src(self) -> None:
        result = _guess_test_path("utils.py", "python")
        assert result == "tests/test_utils.py"

    def test_go(self) -> None:
        result = _guess_test_path("pkg/handler.go", "go")
        assert result == "pkg/handler_test.go"

    def test_typescript_src(self) -> None:
        result = _guess_test_path("src/components/Button.tsx", "typescript")
        assert result == "src/__tests__/components/Button.test.ts"

    def test_java_main(self) -> None:
        result = _guess_test_path("src/main/java/com/app/Service.java", "java")
        assert result == "src/test/java/com/app/ServiceTest.java"

    def test_rust(self) -> None:
        result = _guess_test_path("src/parser.rs", "rust")
        assert result == "tests/parser.rs"

    def test_kotlin_main(self) -> None:
        result = _guess_test_path("src/main/kotlin/Service.kt", "kotlin")
        assert result == "src/test/kotlin/ServiceTest.kt"


class TestFilterTestableFiles:
    def test_filters_correctly(self) -> None:
        files = [
            PRFile(
                filename="src/api.py", status="modified", additions=10, deletions=2, patch="@@ ..."
            ),
            PRFile(
                filename="tests/test_api.py", status="modified", additions=5, deletions=0, patch=""
            ),
            PRFile(filename="README.md", status="modified", additions=20, deletions=5, patch=""),
            PRFile(filename="src/old.py", status="removed", additions=0, deletions=50, patch=""),
            PRFile(
                filename="src/utils.ts", status="added", additions=30, deletions=0, patch="@@ ..."
            ),
        ]
        result = filter_testable_files(files)
        assert len(result) == 2
        assert result[0].filename == "src/api.py"
        assert result[1].filename == "src/utils.ts"

    def test_empty_list(self) -> None:
        assert filter_testable_files([]) == []

    def test_all_tests(self) -> None:
        files = [
            PRFile(filename="tests/test_a.py", status="added", additions=10, deletions=0, patch=""),
            PRFile(
                filename="tests/test_b.py", status="modified", additions=5, deletions=2, patch=""
            ),
        ]
        assert filter_testable_files(files) == []


class TestFormatTestGenComment:
    def test_no_testable_files(self) -> None:
        summary = GeneratedTestSummary(
            files_processed=0,
            files_with_tests=0,
            total_tests=0,
            total_skipped=0,
            results=[],
            cost_usd=0,
        )
        result = format_test_gen_comment(summary)
        assert "No testable source files" in result

    def test_with_generated_tests(self) -> None:
        summary = GeneratedTestSummary(
            files_processed=2,
            files_with_tests=1,
            total_tests=3,
            total_skipped=1,
            results=[
                GeneratedTestResult(
                    source_path="src/api.py",
                    test_file_path="tests/test_api.py",
                    test_content="import pytest\n...",
                    tests_generated=[
                        "test_create_user_success",
                        "test_create_user_duplicate_email",
                        "test_create_user_missing_fields",
                    ],
                    skipped=[],
                    commit_sha="abc12345",
                    is_new_file=True,
                ),
                GeneratedTestResult(
                    source_path="src/db.py",
                    test_file_path="tests/test_db.py",
                    test_content="",
                    tests_generated=[],
                    skipped=["Only contains ORM model definitions"],
                    commit_sha="",
                    is_new_file=True,
                ),
            ],
            cost_usd=0.012,
        )
        result = format_test_gen_comment(summary)
        assert "## AI Test Generator" in result
        assert "3 tests" in result
        assert "1 files" in result
        assert "src/api.py" in result
        assert "test_create_user_success" in result
        assert "abc12345" in result
        assert "Created" in result
        assert "src/db.py" in result
        assert "skipped" in result.lower()
        assert "$0.0120" in result

    def test_updated_existing_tests(self) -> None:
        summary = GeneratedTestSummary(
            files_processed=1,
            files_with_tests=1,
            total_tests=2,
            total_skipped=0,
            results=[
                GeneratedTestResult(
                    source_path="src/utils.py",
                    test_file_path="tests/test_utils.py",
                    test_content="...",
                    tests_generated=["test_parse_date", "test_parse_date_invalid"],
                    skipped=[],
                    commit_sha="def67890",
                    is_new_file=False,
                ),
            ],
            cost_usd=0.005,
        )
        result = format_test_gen_comment(summary)
        assert "Updated" in result

    def test_errors_only(self) -> None:
        summary = GeneratedTestSummary(
            files_processed=1,
            files_with_tests=0,
            total_tests=0,
            total_skipped=0,
            results=[],
            cost_usd=0,
            errors=["src/api.py: rate limit exceeded"],
        )
        result = format_test_gen_comment(summary)
        assert "Failed to generate" in result
        assert "rate limit" in result


class TestGenerateTests:
    @pytest.mark.asyncio
    async def test_generate_tests_flow(self) -> None:
        from src.config import ReviewConfig
        from src.providers.base import LLMResponse

        config = ReviewConfig(
            provider="openai",
            api_key="test-key",
            github_token="test-token",
        )

        files = [
            PRFile(
                filename="src/validator.py",
                status="added",
                additions=20,
                deletions=0,
                patch="@@ -0,0 +1,20 @@\n+def validate_email(email: str) -> bool:\n+    return '@' in email",
            ),
        ]

        mock_github = AsyncMock()
        mock_github.get_file_content.side_effect = lambda repo, path, ref: (
            "def validate_email(email: str) -> bool:\n    return '@' in email\n"
            if path == "src/validator.py"
            else ""
        )
        mock_github.get_file_sha.return_value = ""
        mock_github.create_or_update_file.return_value = "abc12345def"

        mock_response = LLMResponse(
            content='{"test_file_path": "tests/unit/test_validator.py", '
            '"test_content": "import pytest\\nfrom src.validator import validate_email\\n\\n'
            'def test_valid_email():\\n    assert validate_email(\\"a@b.com\\")\\n\\n'
            'def test_invalid_email():\\n    assert not validate_email(\\"invalid\\")\\n", '
            '"tests_generated": ["test_valid_email", "test_invalid_email"], '
            '"skipped": []}',
            input_tokens=1000,
            output_tokens=200,
            model="gpt-4o",
            cost_usd=0.006,
        )

        from src.review.test_generator import generate_tests

        with patch("src.review.test_generator.create_provider") as mock_factory:
            mock_provider = AsyncMock()
            mock_provider.complete.return_value = mock_response
            mock_factory.return_value = mock_provider

            result = await generate_tests(
                github=mock_github,
                config=config,
                repo="owner/repo",
                pr_number=1,
                head_ref="feature/validation",
                files=files,
            )

            assert result.files_processed == 1
            assert result.files_with_tests == 1
            assert result.total_tests == 2
            assert result.cost_usd == 0.006
            assert len(result.results) == 1
            assert result.results[0].commit_sha == "abc12345def"
            mock_github.create_or_update_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_non_testable_files(self) -> None:
        from src.config import ReviewConfig
        from src.review.test_generator import generate_tests

        config = ReviewConfig(provider="openai", api_key="k", github_token="t")

        files = [
            PRFile(filename="README.md", status="modified", additions=5, deletions=0, patch=""),
            PRFile(filename="config.yml", status="added", additions=10, deletions=0, patch=""),
        ]

        mock_github = AsyncMock()

        with patch("src.review.test_generator.create_provider"):
            result = await generate_tests(
                github=mock_github,
                config=config,
                repo="o/r",
                pr_number=1,
                head_ref="main",
                files=files,
            )

        assert result.files_processed == 0
        assert result.total_tests == 0
