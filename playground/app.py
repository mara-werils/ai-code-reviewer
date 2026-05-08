"""Web playground — review any GitHub PR by URL. Zero install, zero config.

Usage:
    pip install pr-reviewer uvicorn
    export GROQ_API_KEY=gsk_...
    uvicorn playground.app:app --port 8000

    # Or with Docker:
    docker build -t pr-reviewer-playground playground/
    docker run -p 8000:8000 -e GROQ_API_KEY=gsk_... pr-reviewer-playground
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import time
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request  # noqa: TC002
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from src.config import ReviewConfig
from src.github.client import GitHubAPI
from src.review.engine import ReviewEngine
from src.review.formatter import format_review_body

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Rate limiting: per-IP cooldown
_recent_requests: dict[str, float] = {}
RATE_LIMIT_SECONDS = 30
MAX_CONCURRENT = 5
_semaphore = asyncio.Semaphore(MAX_CONCURRENT)

# Config
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
DEFAULT_PROVIDER = os.getenv("PROVIDER", "groq")


def _parse_pr_url(url: str) -> tuple[str, int] | None:
    """Extract owner/repo and PR number from a GitHub PR URL."""
    # https://github.com/owner/repo/pull/123
    m = re.match(r"https?://github\.com/([^/]+/[^/]+)/pull/(\d+)", url.strip())
    if m:
        return m.group(1), int(m.group(2))
    # owner/repo#123
    m = re.match(r"([^/]+/[^/]+)#(\d+)", url.strip())
    if m:
        return m.group(1), int(m.group(2))
    return None


def _rate_limit_check(client_ip: str) -> str | None:
    """Return error message if rate limited, None if OK."""
    now = time.time()
    last = _recent_requests.get(client_ip, 0)
    if now - last < RATE_LIMIT_SECONDS:
        remaining = int(RATE_LIMIT_SECONDS - (now - last))
        return f"Rate limited. Try again in {remaining}s."
    _recent_requests[client_ip] = now
    # Cleanup old entries
    cutoff = now - RATE_LIMIT_SECONDS * 2
    for ip in list(_recent_requests):
        if _recent_requests[ip] < cutoff:
            del _recent_requests[ip]
    return None


async def homepage(request: Request) -> HTMLResponse:
    """Serve the playground landing page."""
    html_path = Path(__file__).parent / "index.html"
    content = html_path.read_text()
    return HTMLResponse(content)


async def review_api(request: Request) -> JSONResponse:
    """POST /api/review — review a PR by URL."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    pr_url = body.get("url", "").strip()
    if not pr_url:
        return JSONResponse({"error": "Missing 'url' field"}, status_code=400)

    parsed = _parse_pr_url(pr_url)
    if not parsed:
        return JSONResponse(
            {"error": "Invalid PR URL. Use: https://github.com/owner/repo/pull/123"},
            status_code=400,
        )

    repo, pr_number = parsed

    # Rate limit
    client_ip = request.client.host if request.client else "unknown"
    rate_error = _rate_limit_check(client_ip)
    if rate_error:
        return JSONResponse({"error": rate_error}, status_code=429)

    # Build config
    config = ReviewConfig(
        provider=DEFAULT_PROVIDER,
        github_token=GITHUB_TOKEN,
        review_style="concise",
        max_comments=10,
        max_diff_size=20000,
    )
    config.__post_init__()

    # Resolve API key
    if not config.api_key:
        key_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "groq": "GROQ_API_KEY",
            "google": "GOOGLE_API_KEY",
        }
        env_name = key_map.get(config.provider, "")
        config.api_key = os.getenv(env_name, "")

    if not config.api_key and config.provider != "ollama":
        return JSONResponse(
            {"error": "Server not configured: missing LLM API key"},
            status_code=500,
        )

    if not config.github_token:
        return JSONResponse(
            {"error": "Server not configured: missing GITHUB_TOKEN"},
            status_code=500,
        )

    # Run review with concurrency limit
    try:
        async with _semaphore:
            github = GitHubAPI(config.github_token)
            engine = ReviewEngine(config)
            try:
                pr = await github.get_pr(repo, pr_number)
                files = await github.get_pr_files(repo, pr_number)
                diff = await github.get_pr_diff(repo, pr_number)

                result = await engine.review_pr(pr, files, diff)
            finally:
                await github.close()

        review_body = format_review_body(result)

        return JSONResponse(
            {
                "summary": result.summary,
                "risk_level": result.risk_level,
                "category": result.category,
                "comments_count": len(result.comments),
                "cost_usd": round(result.cost_usd, 6),
                "duration_ms": result.duration_ms,
                "model": result.model,
                "review_markdown": review_body,
                "comments": [
                    {
                        "path": c.path,
                        "line": c.line,
                        "severity": c.severity,
                        "body": c.body,
                    }
                    for c in result.comments
                ],
            }
        )

    except Exception as e:
        logger.error(f"Review failed for {repo}#{pr_number}: {e}")
        return JSONResponse(
            {"error": f"Review failed: {type(e).__name__}: {html.escape(str(e)[:200])}"},
            status_code=500,
        )


async def health(request: Request) -> JSONResponse:
    """GET /health"""
    return JSONResponse({"status": "ok", "provider": DEFAULT_PROVIDER})


app = Starlette(
    routes=[
        Route("/", homepage),
        Route("/api/review", review_api, methods=["POST"]),
        Route("/health", health),
    ],
)
