"""Tests for the GitHub App webhook server."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


def _sign(payload: bytes, secret: str = "test-secret") -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


@pytest.fixture
def client():
    """Create test client with mocked auth."""
    with patch.dict("os.environ", {
        "GITHUB_APP_ID": "12345",
        "GITHUB_WEBHOOK_SECRET": "test-secret",
    }):
        from src.github.app_webhook import app
        with TestClient(app) as c:
            yield c


class TestHealthEndpoint:
    def test_health(self, client) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["mode"] == "github-app"


class TestWebhookSignatureVerification:
    def test_invalid_signature_rejected(self, client) -> None:
        payload = b'{"action": "opened"}'
        resp = client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-GitHub-Event": "ping",
                "X-Hub-Signature-256": "sha256=invalid",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401

    def test_valid_signature_accepted(self, client) -> None:
        payload = json.dumps({"zen": "test", "app_id": 12345}).encode()
        resp = client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-GitHub-Event": "ping",
                "X-Hub-Signature-256": _sign(payload),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200


class TestPingEvent:
    def test_ping_returns_pong(self, client) -> None:
        payload = json.dumps({"zen": "Responsive is better", "app_id": 123}).encode()
        resp = client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-GitHub-Event": "ping",
                "X-Hub-Signature-256": _sign(payload),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.text == "pong"


class TestInstallationEvent:
    def test_installation_created(self, client) -> None:
        payload = json.dumps({
            "action": "created",
            "installation": {"id": 1001},
            "sender": {"login": "testuser"},
        }).encode()
        resp = client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-GitHub-Event": "installation",
                "X-Hub-Signature-256": _sign(payload),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200


class TestPullRequestEvent:
    @patch("src.github.app_webhook._handle_pr_review")
    def test_pr_opened_queued(self, mock_handler, client) -> None:
        mock_handler.return_value = None
        payload = json.dumps({
            "action": "opened",
            "pull_request": {"number": 1, "draft": False},
            "repository": {"full_name": "owner/repo"},
            "installation": {"id": 1001},
        }).encode()
        resp = client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": _sign(payload),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 202

    def test_pr_closed_ignored(self, client) -> None:
        payload = json.dumps({
            "action": "closed",
            "pull_request": {"number": 1},
            "repository": {"full_name": "owner/repo"},
            "installation": {"id": 1001},
        }).encode()
        resp = client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": _sign(payload),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.text == "ignored"


class TestIssueCommentEvent:
    @patch("src.github.app_webhook._handle_command")
    def test_review_command_queued(self, mock_handler, client) -> None:
        mock_handler.return_value = None
        payload = json.dumps({
            "action": "created",
            "comment": {"body": "/review"},
            "issue": {"number": 1, "pull_request": {"url": "..."}},
            "repository": {"full_name": "owner/repo"},
            "installation": {"id": 1001},
        }).encode()
        resp = client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _sign(payload),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 202

    @patch("src.github.app_webhook._handle_command")
    def test_generate_tests_command_queued(self, mock_handler, client) -> None:
        mock_handler.return_value = None
        payload = json.dumps({
            "action": "created",
            "comment": {"body": "/generate-tests"},
            "issue": {"number": 1, "pull_request": {"url": "..."}},
            "repository": {"full_name": "owner/repo"},
            "installation": {"id": 1001},
        }).encode()
        resp = client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _sign(payload),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 202

    def test_non_command_ignored(self, client) -> None:
        payload = json.dumps({
            "action": "created",
            "comment": {"body": "looks good!"},
            "issue": {"number": 1, "pull_request": {"url": "..."}},
            "repository": {"full_name": "owner/repo"},
            "installation": {"id": 1001},
        }).encode()
        resp = client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _sign(payload),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200


class TestReviewCommentEvent:
    @patch("src.github.app_webhook._handle_chat_reply")
    def test_thread_reply_queued(self, mock_handler, client) -> None:
        mock_handler.return_value = None
        payload = json.dumps({
            "action": "created",
            "comment": {
                "body": "Why is this needed?",
                "user": {"login": "developer"},
                "in_reply_to_id": 100,
            },
            "pull_request": {"number": 1},
            "repository": {"full_name": "owner/repo"},
            "installation": {"id": 1001},
        }).encode()
        resp = client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-GitHub-Event": "pull_request_review_comment",
                "X-Hub-Signature-256": _sign(payload),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 202

    def test_bot_comment_ignored(self, client) -> None:
        payload = json.dumps({
            "action": "created",
            "comment": {
                "body": "AI review comment",
                "user": {"login": "ai-reviewer[bot]"},
                "in_reply_to_id": 100,
            },
            "pull_request": {"number": 1},
            "repository": {"full_name": "owner/repo"},
            "installation": {"id": 1001},
        }).encode()
        resp = client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-GitHub-Event": "pull_request_review_comment",
                "X-Hub-Signature-256": _sign(payload),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
