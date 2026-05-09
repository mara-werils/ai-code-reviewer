"""AI Test Generator — generates unit tests for PR changes and commits them.

Flow:
1. Identify testable source files from the PR diff
2. For each file: detect test framework, find existing tests, generate new tests via LLM
3. Commit generated test files to the PR branch
4. Post a summary comment
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from src.config import ReviewConfig
from src.github.client import GitHubAPI, PRFile
from src.providers import LLMProvider, create_provider
from src.review.prompts import TEST_GEN_PROMPT, TEST_GEN_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# File extensions that are testable source code
_TESTABLE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
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
}

# Patterns that indicate a file is already a test file
_TEST_FILE_PATTERNS = (
    "test_",
    "_test.",
    ".test.",
    ".spec.",
    "tests/",
    "test/",
    "__tests__/",
    "spec/",
)

# Patterns to skip (config, docs, generated, etc.)
_SKIP_PATTERNS = (
    "*.lock",
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.generated.*",
    "*_generated.*",
    "*.pb.go",
    "migrations/",
    "alembic/",
    "node_modules/",
    "vendor/",
    "dist/",
    "build/",
    ".github/",
    "docs/",
    "*.md",
    "*.yml",
    "*.yaml",
    "*.json",
    "*.toml",
    "*.cfg",
    "*.ini",
    "*.txt",
    "*.sh",
    "Dockerfile",
    "Makefile",
    "*.html",
    "*.css",
    "*.svg",
    "*.png",
    "*.jpg",
)

# Test framework detection hints per language
_FRAMEWORK_HINTS: dict[str, str] = {
    "python": "Use pytest. Import pytest. Use classes with `Test` prefix or standalone `test_` functions. Use `@pytest.mark.asyncio` for async tests.",
    "typescript": "Use Jest or Vitest. Use `describe`/`it` blocks. Use `expect()` assertions.",
    "javascript": "Use Jest or Vitest. Use `describe`/`it` blocks. Use `expect()` assertions.",
    "go": "Use the standard `testing` package. Functions named `TestXxx(t *testing.T)`. Use `t.Run()` for subtests.",
    "rust": "Use `#[cfg(test)]` module with `#[test]` functions. Use `assert_eq!`, `assert!` macros.",
    "java": "Use JUnit 5. Use `@Test` annotation. Use `assertEquals`, `assertThrows`.",
    "ruby": "Use RSpec. Use `describe`/`it` blocks. Use `expect().to` assertions.",
    "kotlin": "Use JUnit 5 or kotest. Use `@Test` annotation.",
    "swift": "Use XCTest. Subclass `XCTestCase`. Use `XCTAssertEqual`.",
    "php": "Use PHPUnit. Extend `TestCase`. Use `$this->assert*` methods.",
    "csharp": "Use xUnit or NUnit. Use `[Fact]` or `[Test]` attributes.",
    "cpp": "Use Google Test. Use `TEST()` and `EXPECT_*` macros.",
    "c": "Use Unity or CMocka test framework.",
}

# Test file extension mapping
_TEST_FILE_EXT: dict[str, str] = {
    "python": "py",
    "typescript": "ts",
    "javascript": "js",
    "go": "go",
    "rust": "rs",
    "java": "java",
    "ruby": "rb",
    "kotlin": "kt",
    "swift": "swift",
    "php": "php",
    "csharp": "cs",
    "cpp": "cpp",
    "c": "c",
}


@dataclass
class GeneratedTestResult:
    """Result of generating tests for a single file."""

    source_path: str
    test_file_path: str
    test_content: str
    tests_generated: list[str]
    skipped: list[str]
    commit_sha: str
    is_new_file: bool = True


@dataclass
class GeneratedTestSummary:
    """Summary of all test generation for a PR."""

    files_processed: int
    files_with_tests: int
    total_tests: int
    total_skipped: int
    results: list[GeneratedTestResult]
    cost_usd: float
    errors: list[str] = field(default_factory=list)


def _detect_language(path: str) -> str:
    """Detect programming language from file extension."""
    for ext, lang in _TESTABLE_EXTENSIONS.items():
        if path.endswith(ext):
            return lang
    return ""


def _is_test_file(path: str) -> bool:
    """Check if a file path is already a test file."""
    lower = path.lower()
    return any(pattern in lower for pattern in _TEST_FILE_PATTERNS)


def _is_testable_file(path: str) -> bool:
    """Check if a file is a testable source file."""
    if _is_test_file(path):
        return False

    lower = path.lower()
    for pattern in _SKIP_PATTERNS:
        clean = pattern.strip("*")
        if clean in lower:
            return False

    return _detect_language(path) != ""


def _guess_test_path(source_path: str, language: str) -> str:
    """Guess the test file path based on source path and project conventions."""
    p = PurePosixPath(source_path)
    stem = p.stem
    ext = _TEST_FILE_EXT.get(language, p.suffix.lstrip("."))

    if language == "python":
        # Python: tests/unit/test_<name>.py or tests/test_<name>.py
        parts = list(p.parts)
        if "src" in parts:
            idx = parts.index("src")
            rest = parts[idx + 1 :]
            return str(PurePosixPath("tests", "unit", *rest[:-1], f"test_{stem}.{ext}"))
        return f"tests/test_{stem}.{ext}"

    if language == "go":
        # Go: same directory, <name>_test.go
        return str(p.with_name(f"{stem}_test.{ext}"))

    if language in ("typescript", "javascript"):
        # JS/TS: __tests__/<name>.test.ts or <name>.test.ts next to source
        parts = list(p.parts)
        if "src" in parts:
            idx = parts.index("src")
            rest = parts[idx + 1 :]
            return str(PurePosixPath("src", "__tests__", *rest[:-1], f"{stem}.test.{ext}"))
        return str(p.with_name(f"{stem}.test.{ext}"))

    if language == "rust":
        # Rust: tests are usually in the same file, but standalone: tests/<name>.rs
        return f"tests/{stem}.{ext}"

    if language == "java":
        # Java: src/test/java/... mirroring src/main/java/...
        path_str = str(p)
        if "src/main/" in path_str:
            return path_str.replace("src/main/", "src/test/").replace(
                f"{stem}.java", f"{stem}Test.java"
            )
        return str(p.with_name(f"{stem}Test.{ext}"))

    if language == "kotlin":
        path_str = str(p)
        if "src/main/" in path_str:
            return path_str.replace("src/main/", "src/test/").replace(
                f"{stem}.kt", f"{stem}Test.kt"
            )
        return str(p.with_name(f"{stem}Test.{ext}"))

    # Default: test_<name>.<ext> in same directory
    return str(p.with_name(f"test_{stem}.{ext}"))


def filter_testable_files(files: list[PRFile]) -> list[PRFile]:
    """Filter PR files to only testable source files."""
    testable = []
    for f in files:
        if f.status == "removed":
            continue
        if _is_testable_file(f.filename):
            testable.append(f)
    return testable


async def generate_tests(
    github: GitHubAPI,
    config: ReviewConfig,
    repo: str,
    pr_number: int,
    head_ref: str,
    files: list[PRFile],
) -> GeneratedTestSummary:
    """Generate tests for changed files in a PR.

    Args:
        github: GitHub API client
        config: Review config (for LLM provider)
        repo: Repository full name (owner/repo)
        pr_number: PR number
        head_ref: PR head branch name
        files: List of changed files in the PR

    Returns:
        GeneratedTestSummary with all generated tests
    """
    provider: LLMProvider = create_provider(config)
    total_cost = 0.0
    results: list[GeneratedTestResult] = []
    errors: list[str] = []

    # Filter to testable files
    testable = filter_testable_files(files)

    if not testable:
        return GeneratedTestSummary(
            files_processed=0,
            files_with_tests=0,
            total_tests=0,
            total_skipped=0,
            results=[],
            cost_usd=0,
        )

    # Cap at 10 files to avoid excessive cost
    if len(testable) > 10:
        testable = testable[:10]

    logger.info(f"/generate-tests: Processing {len(testable)} testable files")

    for source_file in testable:
        path = source_file.filename
        language = _detect_language(path)

        try:
            # Get file content
            content = await github.get_file_content(repo, path, head_ref)
            if not content:
                logger.warning(f"Could not read {path}, skipping")
                errors.append(f"{path}: file not found")
                continue

            # Get file diff
            file_diff = source_file.patch or ""

            # Check if tests already exist
            guessed_test_path = _guess_test_path(path, language)
            existing_test_content = await github.get_file_content(repo, guessed_test_path, head_ref)

            existing_tests_section = ""
            if existing_test_content:
                existing_tests_section = (
                    f"### Existing tests (ADD to these, do not overwrite)\n"
                    f"File: `{guessed_test_path}`\n"
                    f"```{language}\n{existing_test_content[:10000]}\n```"
                )

            framework_hint = _FRAMEWORK_HINTS.get(language, "")
            if framework_hint:
                framework_hint = f"### Test framework\n{framework_hint}"

            ext = _TEST_FILE_EXT.get(language, "py")

            custom = ""
            if config.custom_instructions:
                custom = f"\n## Additional Instructions\n{config.custom_instructions}"

            system = TEST_GEN_SYSTEM_PROMPT.format(custom_instructions=custom)
            user_prompt = TEST_GEN_PROMPT.format(
                title=f"PR #{pr_number}",
                author="",
                file_path=path,
                language=language,
                file_content=content[:20000],
                file_diff=file_diff[:10000],
                existing_tests_section=existing_tests_section,
                test_framework_hint=framework_hint,
                ext=ext,
            )

            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ]

            response = await provider.complete(
                messages=messages,
                temperature=0.1,
                max_tokens=8192,
                json_mode=True,
            )
            total_cost += response.cost_usd

            # Parse response
            try:
                text = response.content.strip()
                json_match = re.search(r"\{.*\}", text, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                else:
                    data = json.loads(text)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to parse LLM response for {path}: {e}")
                errors.append(f"{path}: failed to parse AI response")
                continue

            test_file_path = data.get("test_file_path", guessed_test_path)
            test_content = data.get("test_content", "")
            tests_generated = data.get("tests_generated", [])
            skipped = data.get("skipped", [])

            if not test_content or not tests_generated:
                results.append(
                    GeneratedTestResult(
                        source_path=path,
                        test_file_path=test_file_path,
                        test_content="",
                        tests_generated=[],
                        skipped=skipped or ["No tests generated"],
                        commit_sha="",
                    )
                )
                continue

            # Ensure file ends with newline
            if not test_content.endswith("\n"):
                test_content += "\n"

            # Commit the test file
            is_new = not existing_test_content
            file_sha = ""
            if not is_new:
                file_sha = await github.get_file_sha(repo, test_file_path, head_ref)

            test_name = PurePosixPath(test_file_path).name
            commit_msg = f"test({test_name}): add {len(tests_generated)} tests for {PurePosixPath(path).name}"
            if len(commit_msg) > 72:
                commit_msg = commit_msg[:69] + "..."

            commit_sha = await github.create_or_update_file(
                repo=repo,
                path=test_file_path,
                content=test_content,
                message=commit_msg,
                branch=head_ref,
                file_sha=file_sha,
            )

            logger.info(
                f"Generated {len(tests_generated)} tests for {path} "
                f"→ {test_file_path} ({commit_sha[:8]})"
            )

            results.append(
                GeneratedTestResult(
                    source_path=path,
                    test_file_path=test_file_path,
                    test_content=test_content,
                    tests_generated=tests_generated,
                    skipped=skipped,
                    commit_sha=commit_sha,
                    is_new_file=is_new,
                )
            )

        except Exception as e:
            logger.error(f"Failed to generate tests for {path}: {e}")
            errors.append(f"{path}: {e}")

    return GeneratedTestSummary(
        files_processed=len(testable),
        files_with_tests=sum(1 for r in results if r.commit_sha),
        total_tests=sum(len(r.tests_generated) for r in results),
        total_skipped=sum(len(r.skipped) for r in results),
        results=results,
        cost_usd=total_cost,
        errors=errors,
    )


def format_test_gen_comment(summary: GeneratedTestSummary) -> str:
    """Format the /generate-tests result as a GitHub comment."""
    if summary.total_tests == 0 and not summary.errors:
        parts = [
            "## AI Test Generator",
            "",
            "No testable source files found in this PR. "
            "The command works on new or modified source code files "
            "(`.py`, `.js`, `.ts`, `.go`, `.java`, `.rs`, etc.).",
        ]
        return "\n".join(parts)

    if summary.total_tests == 0 and summary.errors:
        parts = [
            "## AI Test Generator",
            "",
            "Failed to generate tests:",
            "",
        ]
        for err in summary.errors:
            parts.append(f"- {err}")
        return "\n".join(parts)

    parts = [
        "## AI Test Generator",
        "",
        f"Generated **{summary.total_tests} tests** across "
        f"**{summary.files_with_tests} files** "
        f"for {summary.files_processed} source files.",
        "",
    ]

    for result in summary.results:
        if result.tests_generated:
            action = "Created" if result.is_new_file else "Updated"
            parts.append(f"### `{result.source_path}`")
            parts.append(f"{action}: `{result.test_file_path}`")
            parts.append("")
            for t in result.tests_generated:
                parts.append(f"- {t}")
            if result.skipped:
                parts.append("")
                for s in result.skipped:
                    parts.append(f"- _Skipped: {s}_")
            parts.append(f"- Commit: `{result.commit_sha[:8]}`")
            parts.append("")
        elif result.skipped:
            parts.append(f"### `{result.source_path}` (skipped)")
            for s in result.skipped:
                parts.append(f"- _{s}_")
            parts.append("")

    if summary.errors:
        parts.append("### Errors")
        for err in summary.errors:
            parts.append(f"- {err}")
        parts.append("")

    parts.extend(
        [
            "---",
            f"<sub>Cost: ${summary.cost_usd:.4f} | "
            f"[AI Code Reviewer](https://github.com/mara-werils/ai-code-reviewer)</sub>",
        ]
    )

    return "\n".join(parts)
