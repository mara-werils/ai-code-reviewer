"""Tests for review policies engine."""

from src.github.client import PRFile, PRInfo
from src.review.policies import evaluate_policies, ReviewPolicies, SizeLimitPolicy, format_policy_report


def _pr(title="feat: add thing", body="A good description for testing.") -> PRInfo:
    return PRInfo(
        number=1, title=title, body=body,
        head_sha="abc", base_sha="def",
        base_ref="main", head_ref="feat/test",
        repo_full_name="owner/repo", author="dev",
    )


def _file(name: str, additions: int = 10) -> PRFile:
    return PRFile(filename=name, status="modified", additions=additions, deletions=0, patch="")


class TestPolicies:
    def test_default_policies_pass(self):
        violations = evaluate_policies(
            _pr(), [_file("src/app.py", 10), _file("tests/test_app.py", 5)]
        )
        # Should have no errors (maybe warnings)
        errors = [v for v in violations if v.severity == "error"]
        assert len(errors) == 0

    def test_size_limit_warning(self):
        # Create many files to exceed default limit
        files = [_file(f"src/file{i}.py", 50) for i in range(40)]
        violations = evaluate_policies(_pr(), files)
        assert any(v.policy_id == "SIZE001" for v in violations)

    def test_empty_description_warning(self):
        violations = evaluate_policies(_pr(body=""), [_file("a.py")])
        assert any(v.policy_id == "DESC001" for v in violations)

    def test_convention_check(self):
        # Default convention requires conventional commit format
        violations = evaluate_policies(
            _pr(title="random title without prefix"),
            [_file("a.py")],
        )
        assert any(v.policy_id == "CONV001" for v in violations)

    def test_format_all_passed(self):
        report = format_policy_report([])
        assert "passed" in report.lower()

    def test_required_tests_warning(self):
        # Source code without test files
        files = [_file("src/app.py"), _file("src/utils.py")]
        violations = evaluate_policies(_pr(), files)
        assert any(v.policy_id == "REQ001" for v in violations)
