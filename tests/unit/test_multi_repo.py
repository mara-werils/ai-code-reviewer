"""Tests for multi-repo intelligence."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from src.github.client import PRFile
from src.review.multi_repo import (
    CrossRepoImpact,
    DepsConfig,
    RepoDependency,
    _glob_to_regex,
    analyze_cross_repo_impact,
    format_cross_repo_comment,
    load_deps,
)


def _make_file(filename: str) -> PRFile:
    return PRFile(filename=filename, status="modified", additions=10, deletions=2, patch="")


class TestGlobToRegex:
    def test_simple_wildcard(self) -> None:
        pat = _glob_to_regex("src/*.py")
        assert pat.match("src/main.py")
        assert not pat.match("src/sub/main.py")

    def test_double_star(self) -> None:
        pat = _glob_to_regex("src/**/*.py")
        assert pat.match("src/main.py")
        assert pat.match("src/deep/nested/file.py")
        assert not pat.match("tests/main.py")

    def test_exact_match(self) -> None:
        pat = _glob_to_regex("openapi.yaml")
        assert pat.match("openapi.yaml")
        assert not pat.match("src/openapi.yaml")

    def test_question_mark(self) -> None:
        pat = _glob_to_regex("src/?.py")
        assert pat.match("src/a.py")
        assert not pat.match("src/ab.py")


class TestLoadDeps:
    def test_no_file(self, tmp_path: Path) -> None:
        config = load_deps(tmp_path / "nope.yml")
        assert config.dependencies == []

    def test_valid_config(self, tmp_path: Path) -> None:
        f = tmp_path / ".pr-reviewer-deps.yml"
        f.write_text(dedent("""\
            dependencies:
              - repo: org/frontend
                depends_on:
                  - "src/api/**"
                description: "Frontend uses API"
              - repo: org/mobile
                depends_on:
                  - "proto/*.proto"
        """))
        config = load_deps(f)
        assert len(config.dependencies) == 2
        assert config.dependencies[0].repo == "org/frontend"
        assert config.dependencies[0].depends_on == ["src/api/**"]
        assert config.dependencies[0].description == "Frontend uses API"

    def test_string_depends_on(self, tmp_path: Path) -> None:
        f = tmp_path / "deps.yml"
        f.write_text(dedent("""\
            dependencies:
              - repo: org/docs
                depends_on: "src/**/*.py"
        """))
        config = load_deps(f)
        assert config.dependencies[0].depends_on == ["src/**/*.py"]

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.yml"
        f.write_text("{{bad yaml")
        config = load_deps(f)
        assert config.dependencies == []

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.yml"
        f.write_text("")
        config = load_deps(f)
        assert config.dependencies == []

    def test_skips_invalid_entries(self, tmp_path: Path) -> None:
        f = tmp_path / "deps.yml"
        f.write_text(dedent("""\
            dependencies:
              - not_a_dict
              - depends_on: ["missing repo field"]
              - repo: org/valid
                depends_on: ["src/**"]
        """))
        config = load_deps(f)
        assert len(config.dependencies) == 1
        assert config.dependencies[0].repo == "org/valid"


class TestAnalyzeCrossRepoImpact:
    def test_detects_impact(self) -> None:
        deps = DepsConfig(dependencies=[
            RepoDependency(
                repo="org/frontend",
                depends_on=["src/api/schemas/*.py"],
                description="Frontend uses schemas",
            ),
        ])
        files = [
            _make_file("src/api/schemas/user.py"),
            _make_file("src/utils/helpers.py"),
        ]
        impacts = analyze_cross_repo_impact(files, deps)
        assert len(impacts) == 1
        assert impacts[0].dependent_repo == "org/frontend"
        assert "src/api/schemas/user.py" in impacts[0].changed_files_in_pr

    def test_no_impact(self) -> None:
        deps = DepsConfig(dependencies=[
            RepoDependency(repo="org/frontend", depends_on=["src/api/**"]),
        ])
        files = [_make_file("tests/test_api.py")]
        impacts = analyze_cross_repo_impact(files, deps)
        assert len(impacts) == 0

    def test_multiple_repos_affected(self) -> None:
        deps = DepsConfig(dependencies=[
            RepoDependency(repo="org/frontend", depends_on=["src/api/**"]),
            RepoDependency(repo="org/mobile", depends_on=["src/api/v2/**"]),
        ])
        files = [_make_file("src/api/v2/users.py")]
        impacts = analyze_cross_repo_impact(files, deps)
        assert len(impacts) == 2

    def test_multiple_files_matched(self) -> None:
        deps = DepsConfig(dependencies=[
            RepoDependency(repo="org/frontend", depends_on=["src/api/**"]),
        ])
        files = [
            _make_file("src/api/routes.py"),
            _make_file("src/api/schemas.py"),
        ]
        impacts = analyze_cross_repo_impact(files, deps)
        assert len(impacts) == 1
        assert len(impacts[0].changed_files_in_pr) == 2

    def test_empty_deps(self) -> None:
        impacts = analyze_cross_repo_impact([_make_file("x.py")], DepsConfig())
        assert impacts == []

    def test_double_star_pattern(self) -> None:
        deps = DepsConfig(dependencies=[
            RepoDependency(repo="org/docs", depends_on=["src/**/*.py"]),
        ])
        files = [_make_file("src/deep/nested/module.py")]
        impacts = analyze_cross_repo_impact(files, deps)
        assert len(impacts) == 1


class TestFormatCrossRepoComment:
    def test_format_single_impact(self) -> None:
        impacts = [
            CrossRepoImpact(
                dependent_repo="org/frontend",
                affected_files=["src/api/schemas/*.py"],
                dependency_description="Frontend consumes these schemas",
                changed_files_in_pr=["src/api/schemas/user.py"],
            ),
        ]
        result = format_cross_repo_comment(impacts)
        assert "Cross-Repository Impact" in result
        assert "org/frontend" in result
        assert "Frontend consumes" in result
        assert "src/api/schemas/user.py" in result
        assert "Verify compatibility" in result

    def test_format_multiple_impacts(self) -> None:
        impacts = [
            CrossRepoImpact("org/a", ["api/**"], "A", ["api/x.py"]),
            CrossRepoImpact("org/b", ["api/**"], "B", ["api/y.py"]),
        ]
        result = format_cross_repo_comment(impacts)
        assert "2 dependent repo" in result
        assert "org/a" in result
        assert "org/b" in result

    def test_empty_impacts(self) -> None:
        assert format_cross_repo_comment([]) == ""

    def test_no_description(self) -> None:
        impacts = [
            CrossRepoImpact("org/x", ["src/*"], "", ["src/a.py"]),
        ]
        result = format_cross_repo_comment(impacts)
        assert "org/x" in result
        assert "src/a.py" in result
