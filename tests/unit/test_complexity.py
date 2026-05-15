"""Tests for PR complexity scoring."""

from src.github.client import PRFile
from src.review.complexity import (
    ComplexityResult,
    compute_complexity,
    format_complexity_badge,
    format_complexity_section,
)


def _file(name: str, additions: int = 10, deletions: int = 5, patch: str = "") -> PRFile:
    return PRFile(
        filename=name,
        status="modified",
        additions=additions,
        deletions=deletions,
        patch=patch or f"@@ -1,{deletions} +1,{additions} @@\n+line",
    )


class TestComputeComplexity:
    def test_empty_files(self) -> None:
        result = compute_complexity([])
        assert result.score == 0
        assert result.level == "trivial"

    def test_trivial_pr(self) -> None:
        files = [_file("src/main.py", additions=5, deletions=2)]
        result = compute_complexity(files)
        assert result.level == "trivial"
        assert result.score <= 10

    def test_small_pr(self) -> None:
        files = [
            _file("src/api.py", additions=50, deletions=10),
            _file("tests/test_api.py", additions=30, deletions=0),
        ]
        result = compute_complexity(files)
        assert result.level in ("trivial", "low")

    def test_medium_pr(self) -> None:
        files = [_file(f"src/module{i}/handler.py", additions=40, deletions=20) for i in range(8)]
        result = compute_complexity(files)
        assert result.score >= 20

    def test_large_pr(self) -> None:
        files = [
            _file(f"src/pkg{i}/file{j}.py", additions=60, deletions=30)
            for i in range(5)
            for j in range(4)
        ]
        result = compute_complexity(files)
        assert result.level in ("medium", "high", "critical")
        assert result.score >= 40

    def test_multi_language_increases_score(self) -> None:
        single_lang = [
            _file("src/a.py", 50, 10),
            _file("src/b.py", 50, 10),
        ]
        multi_lang = [
            _file("src/a.py", 50, 10),
            _file("src/b.ts", 50, 10),
            _file("src/c.go", 50, 10),
        ]
        r1 = compute_complexity(single_lang)
        r2 = compute_complexity(multi_lang)
        assert r2.score > r1.score

    def test_sensitive_files_increase_risk(self) -> None:
        normal = [_file("src/utils.py", 100, 50)]
        sensitive = [_file("Dockerfile", 100, 50)]
        r1 = compute_complexity(normal)
        r2 = compute_complexity(sensitive)
        assert r2.breakdown.get("risk", 0) > r1.breakdown.get("risk", 0)

    def test_high_churn_ratio(self) -> None:
        """Deleting much more than adding signals risky refactoring."""
        files = [_file("src/old.py", additions=10, deletions=100)]
        result = compute_complexity(files)
        assert result.breakdown.get("churn", 0) > 0

    def test_high_risk_pattern_in_patch(self) -> None:
        patch = "@@ -1,5 +1,5 @@\n+ALTER TABLE users DROP COLUMN email;"
        files = [_file("migrations/001.sql", 5, 5, patch=patch)]
        result = compute_complexity(files)
        assert result.breakdown.get("risk", 0) > 0


class TestFormatComplexity:
    def test_badge_format(self) -> None:
        result = ComplexityResult(score=42, level="medium", breakdown={}, suggestions=[])
        badge = format_complexity_badge(result)
        assert "42/100" in badge
        assert "MEDIUM" in badge

    def test_section_hidden_for_trivial(self) -> None:
        result = ComplexityResult(score=5, level="trivial", breakdown={}, suggestions=[])
        section = format_complexity_section(result)
        assert section == ""

    def test_section_shows_breakdown(self) -> None:
        result = ComplexityResult(
            score=55,
            level="medium",
            breakdown={"size": 20, "spread": 10, "languages": 5},
            suggestions=["Consider splitting this PR."],
        )
        section = format_complexity_section(result)
        assert "Lines changed: +20" in section
        assert "Consider splitting" in section
