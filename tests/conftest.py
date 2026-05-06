import hashlib
import hmac
import json
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def webhook_secret() -> str:
    return "test-secret"


@pytest.fixture
def pr_opened_payload() -> dict:  # type: ignore[type-arg]
    payload_path = FIXTURES_DIR / "github_payloads" / "pr_opened.json"
    if payload_path.exists():
        return json.loads(payload_path.read_text())  # type: ignore[no-any-return]
    return {
        "action": "opened",
        "number": 1,
        "pull_request": {
            "number": 1,
            "title": "Add feature X",
            "body": "This PR adds feature X",
            "head": {"sha": "abc123def456"},
            "base": {"ref": "main"},
        },
        "repository": {
            "full_name": "test-owner/test-repo",
            "default_branch": "main",
        },
        "installation": {"id": 12345},
    }


def make_signature(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
