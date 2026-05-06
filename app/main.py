from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from redis.asyncio import Redis
from sqlalchemy import text

from app.api.repositories import router as repositories_router
from app.api.stats import router as stats_router
from app.api.streaming import router as streaming_router
from app.api.webhooks import router as webhooks_router
from app.config import get_settings
from app.db.session import engine
from app.logging_config import setup_logging

settings = get_settings()
setup_logging(log_level=settings.log_level, log_format=settings.log_format)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: verify connections
    logger.info("startup_begin")

    # Check Postgres
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("postgres_connected")

    # Check Redis
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    await redis.ping()
    await redis.aclose()
    logger.info("redis_connected")

    logger.info("startup_complete")
    yield

    # Shutdown
    await engine.dispose()
    logger.info("shutdown_complete")


app = FastAPI(
    title="PR Reviewer Agent",
    description="AI agent that reviews pull requests with full repository context",
    version="0.1.0",
    lifespan=lifespan,
)

# Routers
app.include_router(webhooks_router)
app.include_router(stats_router)
app.include_router(repositories_router)
app.include_router(streaming_router)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
    import uuid

    request_id = str(uuid.uuid4())[:8]
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/health")
async def health() -> dict[str, object]:
    checks: dict[str, object] = {"status": "ok"}

    # Postgres check
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"
        checks["status"] = "degraded"

    # Redis check
    try:
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        await redis.ping()
        await redis.aclose()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
        checks["status"] = "degraded"

    return checks


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> str:
    return """<!DOCTYPE html>
<html>
<head>
    <title>PR Reviewer Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { font-family: -apple-system, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: #0d1117; color: #c9d1d9; }
        h1 { color: #58a6ff; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin: 20px 0; }
        .stat-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
        .stat-value { font-size: 2em; font-weight: bold; color: #58a6ff; }
        .stat-label { color: #8b949e; font-size: 0.9em; }
        canvas { background: #161b22; border-radius: 8px; padding: 10px; margin: 20px 0; }
        input, button { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 8px 12px; border-radius: 6px; }
        button { cursor: pointer; background: #238636; border-color: #238636; }
        button:hover { background: #2ea043; }
    </style>
</head>
<body>
    <h1>PR Reviewer Agent Dashboard</h1>
    <div>
        <input id="repo" type="text" placeholder="owner/repo" value="">
        <button onclick="loadStats()">Load Stats</button>
    </div>
    <div class="stats-grid">
        <div class="stat-card"><div class="stat-value" id="total-prs">-</div><div class="stat-label">PRs Reviewed</div></div>
        <div class="stat-card"><div class="stat-value" id="avg-cost">-</div><div class="stat-label">Avg Cost (USD)</div></div>
        <div class="stat-card"><div class="stat-value" id="p50-latency">-</div><div class="stat-label">p50 Latency (s)</div></div>
        <div class="stat-card"><div class="stat-value" id="p95-latency">-</div><div class="stat-label">p95 Latency (s)</div></div>
        <div class="stat-card"><div class="stat-value" id="precision">-</div><div class="stat-label">Precision %</div></div>
    </div>
    <canvas id="costChart" width="800" height="300"></canvas>
    <canvas id="toolChart" width="800" height="300"></canvas>
    <script>
        let costChart, toolChart;
        async function loadStats() {
            const repo = document.getElementById('repo').value;
            if (!repo) return;
            const res = await fetch(`/stats?repo=${encodeURIComponent(repo)}&period=30d`);
            const data = await res.json();
            document.getElementById('total-prs').textContent = data.total_prs_reviewed;
            document.getElementById('avg-cost').textContent = '$' + data.avg_cost_usd.toFixed(4);
            document.getElementById('p50-latency').textContent = (data.p50_latency_ms / 1000).toFixed(1);
            document.getElementById('p95-latency').textContent = (data.p95_latency_ms / 1000).toFixed(1);
            document.getElementById('precision').textContent = data.precision_percent.toFixed(1) + '%';
            if (costChart) costChart.destroy();
            costChart = new Chart(document.getElementById('costChart'), {
                type: 'line', data: { labels: data.cost_by_day.map(d => d.date), datasets: [{ label: 'Daily Cost (USD)', data: data.cost_by_day.map(d => d.cost), borderColor: '#58a6ff', tension: 0.3 }] },
                options: { responsive: true, plugins: { title: { display: true, text: 'Cost by Day', color: '#c9d1d9' } }, scales: { x: { ticks: { color: '#8b949e' } }, y: { ticks: { color: '#8b949e' } } } }
            });
            if (toolChart) toolChart.destroy();
            const tools = Object.keys(data.tool_call_distribution);
            toolChart = new Chart(document.getElementById('toolChart'), {
                type: 'bar', data: { labels: tools, datasets: [{ label: 'Tool Calls', data: tools.map(t => data.tool_call_distribution[t]), backgroundColor: '#238636' }] },
                options: { responsive: true, plugins: { title: { display: true, text: 'Tool Usage', color: '#c9d1d9' } }, scales: { x: { ticks: { color: '#8b949e' } }, y: { ticks: { color: '#8b949e' } } } }
            });
        }
    </script>
</body>
</html>"""
