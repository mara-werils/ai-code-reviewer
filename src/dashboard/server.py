"""Lightweight dashboard server — serves analytics from JSON log.

Usage:
    pr-reviewer dashboard
    pr-reviewer dashboard --port 8080
    uvicorn src.dashboard.server:app --port 8000

No database needed — reads from .pr-reviewer-log.json.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from src.dashboard.review_log import load_log

app = FastAPI(title="AI Code Reviewer Dashboard", docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/analytics")
async def analytics() -> JSONResponse:
    """Return full analytics as JSON."""
    log = load_log()
    return JSONResponse(log.to_analytics())


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    """Serve the interactive dashboard."""
    log = load_log()
    stats = log.to_analytics()
    return _render_dashboard(stats)


def _render_dashboard(stats: dict) -> str:
    """Render the dashboard HTML with embedded data."""
    total = stats.get("total_reviews", 0)
    cost = stats.get("total_cost_usd", 0)
    avg_cost = stats.get("avg_cost_usd", 0)
    avg_dur = stats.get("avg_duration_ms", 0)
    comments = stats.get("total_comments", 0)

    risk = stats.get("risk_distribution", {})
    categories = stats.get("category_distribution", {})
    severity = stats.get("severity_totals", {})
    top_authors = stats.get("top_authors", [])
    reviews_by_day = stats.get("reviews_by_day", [])
    cost_by_day = stats.get("cost_by_day", [])

    # Build table rows
    author_rows = ""
    for name, count in top_authors:
        author_rows += f"<tr><td>{name}</td><td>{count}</td></tr>"

    risk_items = ""
    for level, count in sorted(risk.items()):
        color = {"low": "#22c55e", "medium": "#f59e0b", "high": "#ef4444"}.get(level, "#6b7280")
        risk_items += (
            f'<span style="color:{color};font-weight:bold">{level}: {count}</span>&nbsp;&nbsp;'
        )

    cat_items = ""
    for cat, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
        cat_items += f"<span>{cat}: {count}</span>&nbsp;&nbsp;"

    sev_items = ""
    for sev in ("critical", "warning", "suggestion", "info"):
        count = severity.get(sev, 0)
        if count:
            sev_items += f"<span>{sev}: {count}</span>&nbsp;&nbsp;"

    # Sparkline data
    review_dates = [r["date"][-5:] for r in reviews_by_day[-30:]]
    review_counts = [r["count"] for r in reviews_by_day[-30:]]
    cost_dates = [r["date"][-5:] for r in cost_by_day[-30:]]
    cost_values = [r["cost"] for r in cost_by_day[-30:]]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Code Reviewer — Dashboard</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0d1117; color: #e6edf3; padding: 24px; }}
  .header {{ text-align: center; margin-bottom: 32px; }}
  .header h1 {{ font-size: 24px; color: #c9d1d9; }}
  .header p {{ color: #8b949e; margin-top: 4px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 32px; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; text-align: center; }}
  .card .value {{ font-size: 28px; font-weight: bold; color: #58a6ff; }}
  .card .label {{ font-size: 13px; color: #8b949e; margin-top: 4px; }}
  .section {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-bottom: 16px; }}
  .section h2 {{ font-size: 16px; color: #c9d1d9; margin-bottom: 12px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #21262d; }}
  th {{ color: #8b949e; font-size: 12px; text-transform: uppercase; }}
  .chart {{ display: flex; align-items: flex-end; gap: 2px; height: 80px; margin-top: 8px; }}
  .bar {{ background: #58a6ff; border-radius: 2px 2px 0 0; min-width: 8px; flex: 1; }}
  .bar:hover {{ background: #79c0ff; }}
  .dist {{ display: flex; gap: 16px; flex-wrap: wrap; font-size: 14px; }}
  .footer {{ text-align: center; color: #484f58; font-size: 12px; margin-top: 32px; }}
  .footer a {{ color: #58a6ff; text-decoration: none; }}
</style>
</head>
<body>
  <div class="header">
    <h1>AI Code Reviewer</h1>
    <p>Review Analytics Dashboard</p>
  </div>

  <div class="cards">
    <div class="card"><div class="value">{total}</div><div class="label">Reviews</div></div>
    <div class="card"><div class="value">{comments}</div><div class="label">Comments</div></div>
    <div class="card"><div class="value">${cost:.2f}</div><div class="label">Total Cost</div></div>
    <div class="card"><div class="value">${avg_cost:.4f}</div><div class="label">Avg Cost/Review</div></div>
    <div class="card"><div class="value">{avg_dur / 1000:.1f}s</div><div class="label">Avg Duration</div></div>
  </div>

  <div class="section">
    <h2>Reviews per Day (last 30 days)</h2>
    <div class="chart">
      {"".join(f'<div class="bar" style="height:{max(4, c / max(max(review_counts, default=1), 1) * 76)}px" title="{review_dates[i]}: {c}"></div>' for i, c in enumerate(review_counts))}
    </div>
  </div>

  <div class="section">
    <h2>Cost per Day (last 30 days)</h2>
    <div class="chart">
      {"".join(f'<div class="bar" style="height:{max(4, c / max(max(cost_values, default=0.01), 0.01) * 76)}px;background:#f59e0b" title="{cost_dates[i]}: ${c:.4f}"></div>' for i, c in enumerate(cost_values))}
    </div>
  </div>

  <div class="section">
    <h2>Risk Distribution</h2>
    <div class="dist">{risk_items or "<span>No data</span>"}</div>
  </div>

  <div class="section">
    <h2>PR Categories</h2>
    <div class="dist">{cat_items or "<span>No data</span>"}</div>
  </div>

  <div class="section">
    <h2>Severity Totals</h2>
    <div class="dist">{sev_items or "<span>No data</span>"}</div>
  </div>

  <div class="section">
    <h2>Top Authors</h2>
    <table>
      <tr><th>Author</th><th>PRs Reviewed</th></tr>
      {author_rows or "<tr><td colspan='2'>No data</td></tr>"}
    </table>
  </div>

  <div class="footer">
    <a href="https://github.com/mara-werils/ai-code-reviewer">AI Code Reviewer</a>
    &middot; <a href="/api/analytics">JSON API</a>
  </div>
</body>
</html>"""
