"""Tests for the self-learning feedback system."""

from __future__ import annotations

from pathlib import Path

from src.review.feedback import (
    FeedbackEntry,
    FeedbackStore,
    _extract_category,
    _extract_severity,
    _is_disagreement,
    build_learning_prompt,
    collect_feedback_from_reactions,
    load_feedback,
    save_feedback,
)


class TestFeedbackEntry:
    def test_defaults(self) -> None:
        e = FeedbackEntry(
            comment_body="Bug found",
            severity="critical",
            file_path="src/api.py",
            category="correctness",
            outcome="accepted",
        )
        assert e.developer_reply == ""
        assert e.pr_number == 0


class TestFeedbackStore:
    def test_add_entry(self) -> None:
        store = FeedbackStore()
        entry = FeedbackEntry(
            comment_body="test",
            severity="warning",
            file_path="a.py",
            category="design",
            outcome="accepted",
        )
        store.add(entry)
        assert len(store.entries) == 1
        assert store.stats["total"] == 1
        assert store.stats["accepted"] == 1

    def test_acceptance_rate(self) -> None:
        store = FeedbackStore(stats={"total": 10, "accepted": 7, "rejected": 3})
        assert store.acceptance_rate == 0.7

    def test_acceptance_rate_empty(self) -> None:
        store = FeedbackStore()
        assert store.acceptance_rate == 0.0

    def test_acceptance_rate_with_resolved(self) -> None:
        store = FeedbackStore(stats={"total": 10, "accepted": 3, "resolved": 4, "rejected": 3})
        assert store.acceptance_rate == 0.7

    def test_evicts_old_entries(self) -> None:
        store = FeedbackStore()
        for i in range(250):
            store.add(
                FeedbackEntry(
                    comment_body=f"comment {i}",
                    severity="info",
                    file_path="f.py",
                    category="general",
                    outcome="accepted",
                )
            )
        assert len(store.entries) == 200  # Max entries


class TestLoadSaveFeedback:
    def test_load_nonexistent(self, tmp_path: Path) -> None:
        store = load_feedback(tmp_path / "nonexistent.json")
        assert store.entries == []

    def test_save_and_load(self, tmp_path: Path) -> None:
        path = tmp_path / "feedback.json"

        store = FeedbackStore(repo="owner/repo")
        store.add(
            FeedbackEntry(
                comment_body="SQL injection risk",
                severity="critical",
                file_path="db.py",
                category="security",
                outcome="accepted",
                developer_reply="Good catch!",
                pr_number=42,
            )
        )
        save_feedback(store, path)

        loaded = load_feedback(path)
        assert loaded.repo == "owner/repo"
        assert len(loaded.entries) == 1
        assert loaded.entries[0].comment_body == "SQL injection risk"
        assert loaded.entries[0].outcome == "accepted"
        assert loaded.stats["total"] == 1

    def test_load_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{invalid json")
        store = load_feedback(path)
        assert store.entries == []


class TestBuildLearningPrompt:
    def test_empty_store(self) -> None:
        assert build_learning_prompt(FeedbackStore()) == ""

    def test_with_rejected_entries(self) -> None:
        store = FeedbackStore(stats={"total": 5, "accepted": 2, "rejected": 3})
        store.entries = [
            FeedbackEntry("Missing type hint", "suggestion", "a.py", "design", "rejected"),
            FeedbackEntry("Add docstring", "info", "b.py", "design", "rejected"),
            FeedbackEntry("Unused import", "suggestion", "c.py", "design", "rejected"),
            FeedbackEntry("SQL injection", "critical", "d.py", "security", "accepted"),
            FeedbackEntry("Null check", "warning", "e.py", "correctness", "accepted"),
        ]
        prompt = build_learning_prompt(store)
        assert "Team Feedback" in prompt
        assert "DISMISS" in prompt
        assert "design" in prompt
        assert "VALUES" in prompt
        assert "40%" in prompt  # 2/5

    def test_with_only_accepted(self) -> None:
        store = FeedbackStore(stats={"total": 3, "accepted": 3})
        store.entries = [
            FeedbackEntry("Bug fix", "critical", "a.py", "correctness", "accepted"),
            FeedbackEntry("Security issue", "high", "b.py", "security", "accepted"),
            FeedbackEntry("Performance", "warning", "c.py", "performance", "accepted"),
        ]
        prompt = build_learning_prompt(store)
        assert "VALUES" in prompt
        assert "100%" in prompt

    def test_includes_developer_replies(self) -> None:
        store = FeedbackStore(stats={"total": 1, "rejected": 1})
        store.entries = [
            FeedbackEntry(
                "Add null check",
                "warning",
                "api.py",
                "correctness",
                "rejected",
                developer_reply="This is validated upstream in middleware",
            ),
        ]
        prompt = build_learning_prompt(store)
        assert "validated upstream" in prompt


class TestCollectFeedback:
    def test_thumbs_up_accepted(self) -> None:
        comments = [
            {
                "id": 1,
                "user": {"login": "bot[bot]"},
                "body": "**[WARNING]** Missing null check",
                "path": "api.py",
                "reactions": {"+1": 2, "-1": 0, "heart": 0, "confused": 0},
            },
        ]
        entries = collect_feedback_from_reactions(comments, "bot[bot]")
        assert len(entries) == 1
        assert entries[0].outcome == "accepted"

    def test_thumbs_down_rejected(self) -> None:
        comments = [
            {
                "id": 1,
                "user": {"login": "bot[bot]"},
                "body": "**[SUGGESTION]** Consider using map()",
                "path": "utils.py",
                "reactions": {"+1": 0, "-1": 1, "heart": 0, "confused": 0},
            },
        ]
        entries = collect_feedback_from_reactions(comments, "bot[bot]")
        assert len(entries) == 1
        assert entries[0].outcome == "rejected"

    def test_disagreement_reply_rejected(self) -> None:
        comments = [
            {
                "id": 1,
                "user": {"login": "bot[bot]"},
                "body": "**[WARNING]** Add error handling",
                "path": "api.py",
                "reactions": {},
            },
            {
                "id": 2,
                "user": {"login": "developer"},
                "body": "This is not necessary, already handled upstream",
                "in_reply_to_id": 1,
                "reactions": {},
            },
        ]
        entries = collect_feedback_from_reactions(comments, "bot[bot]")
        assert len(entries) == 1
        assert entries[0].outcome == "rejected"
        assert "already handled" in entries[0].developer_reply

    def test_no_reactions_skipped(self) -> None:
        comments = [
            {
                "id": 1,
                "user": {"login": "bot[bot]"},
                "body": "**[INFO]** Consider adding a docstring",
                "path": "utils.py",
                "reactions": {},
            },
        ]
        entries = collect_feedback_from_reactions(comments, "bot[bot]")
        assert len(entries) == 0

    def test_non_bot_comments_ignored(self) -> None:
        comments = [
            {
                "id": 1,
                "user": {"login": "developer"},
                "body": "Looks good",
                "path": "api.py",
                "reactions": {"+1": 5},
            },
        ]
        entries = collect_feedback_from_reactions(comments, "bot[bot]")
        assert len(entries) == 0


class TestHelpers:
    def test_extract_severity(self) -> None:
        assert _extract_severity("[CRITICAL] Bug") == "critical"
        assert _extract_severity("[WARNING] Issue") == "warning"
        assert _extract_severity("[SUGGESTION] Tip") == "suggestion"
        assert _extract_severity("Some text") == "info"

    def test_extract_category(self) -> None:
        assert _extract_category("SQL injection vulnerability") == "security"
        assert _extract_category("N+1 query detected") == "performance"
        assert _extract_category("Null pointer dereference") == "correctness"
        assert _extract_category("Tight coupling between modules") == "design"
        assert _extract_category("Missing test coverage") == "testing"
        assert _extract_category("Minor formatting issue") == "general"

    def test_is_disagreement(self) -> None:
        assert _is_disagreement("I don't think this is needed") is True
        assert _is_disagreement("This is intentional") is True
        assert _is_disagreement("False positive here") is True
        assert _is_disagreement("Good catch, will fix!") is False
        assert _is_disagreement("Thanks for the review") is False
