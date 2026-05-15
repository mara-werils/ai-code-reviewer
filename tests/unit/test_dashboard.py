"""Tests for the analytics dashboard."""

from __future__ import annotations

from pathlib import Path

from src.dashboard.review_log import (
    ReviewLog,
    ReviewLogEntry,
    load_log,
    save_log,
)


class TestReviewLogEntry:
    def test_defaults(self) -> None:
        e = ReviewLogEntry(
            pr_number=1,
            title="Fix bug",
            author="dev",
            repo="o/r",
            risk_level="low",
            category="bugfix",
            comments_count=3,
            cost_usd=0.01,
            duration_ms=2000,
            model="gpt-4o",
            provider="openai",
        )
        assert e.timestamp != ""
        assert e.files_changed == 0
        assert e.severity_counts == {}


class TestReviewLog:
    def _make_entry(self, **kwargs) -> ReviewLogEntry:
        defaults = dict(
            pr_number=1,
            title="PR",
            author="dev",
            repo="o/r",
            risk_level="low",
            category="bugfix",
            comments_count=2,
            cost_usd=0.01,
            duration_ms=1000,
            model="gpt-4o",
            provider="openai",
            timestamp="2025-01-15T00:00:00",
        )
        defaults.update(kwargs)
        return ReviewLogEntry(**defaults)

    def test_add_and_count(self) -> None:
        log = ReviewLog()
        log.add(self._make_entry())
        log.add(self._make_entry())
        assert log.total_reviews == 2

    def test_total_cost(self) -> None:
        log = ReviewLog()
        log.add(self._make_entry(cost_usd=0.01))
        log.add(self._make_entry(cost_usd=0.03))
        assert abs(log.total_cost - 0.04) < 0.001

    def test_avg_cost(self) -> None:
        log = ReviewLog()
        log.add(self._make_entry(cost_usd=0.02))
        log.add(self._make_entry(cost_usd=0.04))
        assert abs(log.avg_cost - 0.03) < 0.001

    def test_avg_cost_empty(self) -> None:
        assert ReviewLog().avg_cost == 0.0

    def test_avg_duration(self) -> None:
        log = ReviewLog()
        log.add(self._make_entry(duration_ms=1000))
        log.add(self._make_entry(duration_ms=3000))
        assert log.avg_duration_ms == 2000.0

    def test_risk_distribution(self) -> None:
        log = ReviewLog()
        log.add(self._make_entry(risk_level="low"))
        log.add(self._make_entry(risk_level="low"))
        log.add(self._make_entry(risk_level="high"))
        dist = log.risk_distribution()
        assert dist["low"] == 2
        assert dist["high"] == 1

    def test_category_distribution(self) -> None:
        log = ReviewLog()
        log.add(self._make_entry(category="bugfix"))
        log.add(self._make_entry(category="feature"))
        log.add(self._make_entry(category="bugfix"))
        dist = log.category_distribution()
        assert dist["bugfix"] == 2
        assert dist["feature"] == 1

    def test_top_authors(self) -> None:
        log = ReviewLog()
        log.add(self._make_entry(author="alice"))
        log.add(self._make_entry(author="alice"))
        log.add(self._make_entry(author="bob"))
        top = log.top_authors(2)
        assert top[0] == ("alice", 2)
        assert top[1] == ("bob", 1)

    def test_reviews_by_day(self) -> None:
        log = ReviewLog()
        log.add(self._make_entry(timestamp="2025-01-15T10:00:00"))
        log.add(self._make_entry(timestamp="2025-01-15T14:00:00"))
        log.add(self._make_entry(timestamp="2025-01-16T09:00:00"))
        by_day = log.reviews_by_day()
        assert len(by_day) == 2
        assert by_day[0]["count"] == 2
        assert by_day[1]["count"] == 1

    def test_cost_by_day(self) -> None:
        log = ReviewLog()
        log.add(self._make_entry(timestamp="2025-01-15T10:00:00", cost_usd=0.01))
        log.add(self._make_entry(timestamp="2025-01-15T14:00:00", cost_usd=0.02))
        by_day = log.cost_by_day()
        assert len(by_day) == 1
        assert by_day[0]["cost"] == 0.03

    def test_severity_totals(self) -> None:
        log = ReviewLog()
        log.add(self._make_entry(severity_counts={"critical": 1, "warning": 2}))
        log.add(self._make_entry(severity_counts={"critical": 1, "info": 3}))
        totals = log.severity_totals()
        assert totals["critical"] == 2
        assert totals["warning"] == 2
        assert totals["info"] == 3

    def test_to_analytics(self) -> None:
        log = ReviewLog()
        log.add(self._make_entry())
        stats = log.to_analytics()
        assert "total_reviews" in stats
        assert "total_cost_usd" in stats
        assert "risk_distribution" in stats
        assert "top_authors" in stats

    def test_eviction(self) -> None:
        log = ReviewLog()
        for i in range(550):
            log.add(self._make_entry(pr_number=i))
        assert len(log.entries) == 500


class TestLoadSaveLog:
    def test_load_nonexistent(self, tmp_path: Path) -> None:
        log = load_log(tmp_path / "nope.json")
        assert log.total_reviews == 0

    def test_save_and_load(self, tmp_path: Path) -> None:
        path = tmp_path / "log.json"
        log = ReviewLog()
        log.add(
            ReviewLogEntry(
                pr_number=42,
                title="Fix",
                author="dev",
                repo="o/r",
                risk_level="low",
                category="bugfix",
                comments_count=3,
                cost_usd=0.005,
                duration_ms=1500,
                model="gpt-4o",
                provider="openai",
                severity_counts={"warning": 2, "info": 1},
            )
        )
        save_log(log, path)

        loaded = load_log(path)
        assert loaded.total_reviews == 1
        assert loaded.entries[0].pr_number == 42
        assert loaded.entries[0].severity_counts["warning"] == 2

    def test_load_invalid(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{bad json")
        log = load_log(path)
        assert log.total_reviews == 0


class TestDashboardServer:
    def test_health(self) -> None:
        from fastapi.testclient import TestClient

        from src.dashboard.server import app

        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

    def test_analytics_api(self) -> None:
        from fastapi.testclient import TestClient

        from src.dashboard.server import app

        with TestClient(app) as client:
            resp = client.get("/api/analytics")
            assert resp.status_code == 200
            data = resp.json()
            assert "total_reviews" in data

    def test_dashboard_html(self) -> None:
        from fastapi.testclient import TestClient

        from src.dashboard.server import app

        with TestClient(app) as client:
            resp = client.get("/")
            assert resp.status_code == 200
            assert "AI Code Reviewer" in resp.text
            assert "Reviews" in resp.text
