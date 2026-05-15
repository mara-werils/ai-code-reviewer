"""Tests for monorepo impact analysis."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from src.github.client import PRFile
from src.review.monorepo import (
    ImpactAnalysis,
    MonorepoConfig,
    Package,
    PackageImpact,
    _file_belongs_to_package,
    _find_downstream,
    analyze_monorepo_impact,
    format_impact_comment,
    load_monorepo_config,
)


def _f(name: str) -> PRFile:
    return PRFile(filename=name, status="modified", additions=5, deletions=0, patch="")


class TestFileBelongsToPackage:
    def test_direct_child(self) -> None:
        assert _file_belongs_to_package("packages/core/index.ts", "packages/core")

    def test_nested(self) -> None:
        assert _file_belongs_to_package("packages/core/src/util.ts", "packages/core")

    def test_no_match(self) -> None:
        assert not _file_belongs_to_package("packages/web/index.ts", "packages/core")

    def test_partial_name(self) -> None:
        assert not _file_belongs_to_package("packages/core-utils/x.ts", "packages/core")


class TestFindDownstream:
    def test_direct_dependents(self) -> None:
        packages = [
            Package("core", "packages/core"),
            Package("api", "services/api", depends_on=["core"]),
            Package("web", "apps/web", depends_on=["api"]),
        ]
        down = _find_downstream("core", packages)
        assert "api" in down

    def test_transitive(self) -> None:
        packages = [
            Package("core", "packages/core"),
            Package("api", "services/api", depends_on=["core"]),
            Package("web", "apps/web", depends_on=["api"]),
        ]
        down = _find_downstream("core", packages)
        assert "api" in down
        assert "web" in down

    def test_no_dependents(self) -> None:
        packages = [
            Package("core", "packages/core"),
            Package("api", "services/api"),
        ]
        assert _find_downstream("core", packages) == []

    def test_circular(self) -> None:
        packages = [
            Package("a", "a", depends_on=["b"]),
            Package("b", "b", depends_on=["a"]),
        ]
        down = _find_downstream("a", packages)
        assert "b" in down


class TestLoadMonorepoConfig:
    def test_no_file(self, tmp_path: Path) -> None:
        config = load_monorepo_config(tmp_path / "nope.yml")
        assert config.packages == []

    def test_valid(self, tmp_path: Path) -> None:
        f = tmp_path / "mono.yml"
        f.write_text(
            dedent("""\
            packages:
              - name: core
                path: packages/core
                owners: ["@backend"]
              - name: api
                path: services/api
                depends_on: [core]
                owners: ["@api-team"]
        """)
        )
        config = load_monorepo_config(f)
        assert len(config.packages) == 2
        assert config.packages[1].depends_on == ["core"]
        assert config.get_package("core") is not None

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.yml"
        f.write_text("{{bad")
        assert load_monorepo_config(f).packages == []

    def test_skips_invalid(self, tmp_path: Path) -> None:
        f = tmp_path / "mono.yml"
        f.write_text(
            dedent("""\
            packages:
              - name: valid
                path: pkg/valid
              - name: no-path
              - not_a_dict
        """)
        )
        config = load_monorepo_config(f)
        assert len(config.packages) == 1


class TestAnalyzeMonorepoImpact:
    def _config(self) -> MonorepoConfig:
        return MonorepoConfig(
            packages=[
                Package("core", "packages/core", owners=["@backend"]),
                Package("api", "services/api", depends_on=["core"], owners=["@api"]),
                Package("web", "apps/web", depends_on=["api"], owners=["@frontend"]),
                Package("db", "packages/db", owners=["@backend"]),
            ]
        )

    def test_direct_impact(self) -> None:
        files = [_f("packages/core/src/util.ts")]
        analysis = analyze_monorepo_impact(files, self._config())
        assert len(analysis.directly_changed) == 1
        assert analysis.directly_changed[0].package_name == "core"

    def test_transitive_impact(self) -> None:
        files = [_f("packages/core/src/util.ts")]
        analysis = analyze_monorepo_impact(files, self._config())
        # core → api → web
        assert len(analysis.transitively_affected) == 2
        names = {p.package_name for p in analysis.transitively_affected}
        assert "api" in names
        assert "web" in names

    def test_unowned_files(self) -> None:
        files = [_f("README.md"), _f("packages/core/x.ts")]
        analysis = analyze_monorepo_impact(files, self._config())
        assert "README.md" in analysis.unowned_files
        assert len(analysis.directly_changed) == 1

    def test_no_config(self) -> None:
        files = [_f("src/main.py")]
        analysis = analyze_monorepo_impact(files, MonorepoConfig())
        assert analysis.total_packages_affected == 0
        assert analysis.unowned_files == ["src/main.py"]

    def test_multiple_packages_changed(self) -> None:
        files = [_f("packages/core/a.ts"), _f("packages/db/b.ts")]
        analysis = analyze_monorepo_impact(files, self._config())
        assert len(analysis.directly_changed) == 2

    def test_all_owners(self) -> None:
        files = [_f("packages/core/x.ts")]
        analysis = analyze_monorepo_impact(files, self._config())
        assert "@backend" in analysis.all_owners
        assert "@api" in analysis.all_owners
        assert "@frontend" in analysis.all_owners

    def test_total_affected(self) -> None:
        files = [_f("packages/core/x.ts")]
        analysis = analyze_monorepo_impact(files, self._config())
        assert analysis.total_packages_affected == 3  # core + api + web


class TestFormatImpactComment:
    def test_format(self) -> None:
        analysis = ImpactAnalysis(
            directly_changed=[
                PackageImpact(
                    "core", "packages/core", ["a.ts"], ["api", "web"], ["@backend"], True
                ),
            ],
            transitively_affected=[
                PackageImpact("api", "services/api", [], [], ["@api"], False),
                PackageImpact("web", "apps/web", [], [], ["@frontend"], False),
            ],
            unowned_files=[],
        )
        result = format_impact_comment(analysis)
        assert "Monorepo Impact Radius" in result
        assert "1 package(s) directly" in result
        assert "2 transitively" in result
        assert "`core`" in result
        assert "`api`" in result
        assert "@backend" in result
        assert "Suggested reviewers" in result

    def test_empty(self) -> None:
        analysis = ImpactAnalysis([], [], [])
        assert format_impact_comment(analysis) == ""
