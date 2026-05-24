"""CLI for running reviews locally or in CI.

Usage:
    pr-reviewer review --repo owner/name --pr 42
    pr-reviewer review --repo owner/name --pr 42 --provider groq
    pr-reviewer review --diff ./changes.diff
    pr-reviewer review --repo group/project --mr 42 --platform gitlab
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from src import __version__
from src.bitbucket.client import BitbucketAPI
from src.config import ReviewConfig
from src.github.client import GitHubAPI
from src.gitlab.client import GitLabAPI
from src.review.engine import ReviewEngine
from src.review.formatter import format_review_body

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


async def cmd_review(args: argparse.Namespace) -> None:
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config = ReviewConfig.from_env()

    # Load YAML config if specified or auto-detect
    if args.config:
        from pathlib import Path

        config = ReviewConfig.from_yaml(Path(args.config), base=config)

    # Override from CLI args
    if args.provider:
        config.provider = args.provider
        config.model = ""
        config.__post_init__()  # Reset model default
    if args.model:
        config.model = args.model
    if args.api_key:
        config.api_key = args.api_key
    if args.persona:
        config.persona = args.persona

    engine = ReviewEngine(config)

    platform = getattr(args, "platform", "github") or "github"
    mr_number = args.mr or args.pr  # --mr alias for GitLab

    if args.diff:
        # Review from local diff file
        with open(args.diff) as f:
            diff = f.read()

        from src.github.client import PRInfo

        pr = PRInfo(
            number=0,
            title=args.title or "Local review",
            body="",
            head_sha="local",
            base_sha="local",
            base_ref="main",
            head_ref="local",
            repo_full_name="local/repo",
            author="local",
        )
        files = []  # No file info for local diff
        result = await engine.review_pr(pr, files, diff)
    elif platform == "bitbucket":
        # Review from Bitbucket PR
        if not mr_number:
            logger.error("--pr is required for Bitbucket")
            sys.exit(1)

        import os

        bb_username = args.bb_username or os.getenv("BITBUCKET_USERNAME", "")
        bb_password = args.bb_app_password or os.getenv("BITBUCKET_APP_PASSWORD", "")
        if not bb_username or not bb_password:
            logger.error("BITBUCKET_USERNAME and BITBUCKET_APP_PASSWORD required")
            sys.exit(1)

        # Parse workspace/repo_slug from --repo
        repo_parts = (args.repo or "").split("/")
        if len(repo_parts) != 2:
            logger.error("--repo must be workspace/repo_slug for Bitbucket")
            sys.exit(1)
        workspace, repo_slug = repo_parts

        bb = BitbucketAPI(bb_username, bb_password)
        try:
            pr = await bb.get_pr(workspace, repo_slug, mr_number)
            files = await bb.get_pr_files(workspace, repo_slug, mr_number)
            diff = await bb.get_pr_diff(workspace, repo_slug, mr_number)
            result = await engine.review_pr(pr, files, diff)
        finally:
            await bb.close()
    elif platform == "gitlab":
        # Review from GitLab MR
        if not args.repo or not mr_number:
            logger.error("--repo and --mr (or --pr) are required for GitLab")
            sys.exit(1)

        gitlab_token = config.gitlab_token
        if not gitlab_token:
            logger.error("GITLAB_TOKEN environment variable required")
            sys.exit(1)

        gitlab = GitLabAPI(gitlab_token, base_url=config.gitlab_url)
        try:
            pr = await gitlab.get_mr(args.repo, mr_number)
            files = await gitlab.get_mr_files(args.repo, mr_number)
            diff = await gitlab.get_mr_diff(args.repo, mr_number)
            result = await engine.review_pr(pr, files, diff)
        finally:
            await gitlab.close()
    else:
        # Review from GitHub PR
        if not args.repo or not mr_number:
            logger.error("Either --diff or --repo + --pr are required")
            sys.exit(1)

        if not config.github_token:
            logger.error("GITHUB_TOKEN environment variable required")
            sys.exit(1)

        github = GitHubAPI(config.github_token)
        try:
            pr = await github.get_pr(args.repo, mr_number)
            files = await github.get_pr_files(args.repo, mr_number)
            diff = await github.get_pr_diff(args.repo, mr_number)
            result = await engine.review_pr(pr, files, diff)
        finally:
            await github.close()

    # Summary-only mode
    if args.summary_only:
        summary = await engine.generate_summary(pr, files)
        print(summary)
        return

    # Output
    if args.output_json:
        import json

        output = {
            "summary": result.summary,
            "risk_level": result.risk_level,
            "category": result.category,
            "comments_count": len(result.comments),
            "cost_usd": result.cost_usd,
            "duration_ms": result.duration_ms,
            "model": result.model,
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
        print(json.dumps(output, indent=2))
        return

    body = format_review_body(result)
    print(body)

    if args.post and args.repo and mr_number:
        from src.review.formatter import build_github_review_comments

        if platform == "bitbucket":
            import os

            bb_username = args.bb_username or os.getenv("BITBUCKET_USERNAME", "")
            bb_password = args.bb_app_password or os.getenv("BITBUCKET_APP_PASSWORD", "")
            repo_parts = args.repo.split("/")
            workspace, repo_slug = repo_parts[0], repo_parts[1]
            bb = BitbucketAPI(bb_username, bb_password)
            try:
                inline = build_github_review_comments(result)
                await bb.post_comment(workspace, repo_slug, mr_number, body)
                if inline:
                    await bb.post_inline_comments(workspace, repo_slug, mr_number, inline)
                logger.info(f"Posted review to Bitbucket PR #{mr_number}")
            finally:
                await bb.close()
        elif platform == "gitlab":
            gitlab = GitLabAPI(config.gitlab_token, base_url=config.gitlab_url)
            try:
                inline = build_github_review_comments(result)
                await gitlab.post_mr_note(args.repo, mr_number, body)
                if inline:
                    await gitlab.post_inline_comments(
                        args.repo, mr_number, pr.head_sha, pr.base_sha, inline
                    )
                logger.info(f"Posted review to MR !{mr_number}")
            finally:
                await gitlab.close()
        else:
            github = GitHubAPI(config.github_token)
            try:
                inline = build_github_review_comments(result)
                if inline:
                    await github.post_review(args.repo, mr_number, body, inline)
                else:
                    await github.post_comment(args.repo, mr_number, body)
                logger.info(f"Posted review to PR #{mr_number}")
            finally:
                await github.close()

    print(
        f"\n---\nCost: ${result.cost_usd:.4f} | Model: {result.model} | Duration: {result.duration_ms}ms"
    )

    # Exit with non-zero code if high-risk issues found (for CI gating)
    if args.exit_code:
        critical_count = sum(1 for c in result.comments if c.severity == "critical")
        if critical_count > 0:
            logger.info(f"Exiting with code 1: {critical_count} critical issues found")
            sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pr-reviewer",
        description="AI-powered code review for pull requests",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    # review command
    review_parser = subparsers.add_parser("review", help="Review a PR or diff")
    review_parser.add_argument(
        "--repo", help="Repository (owner/name for GitHub, group/project for GitLab)"
    )
    review_parser.add_argument("--pr", type=int, help="PR number (GitHub)")
    review_parser.add_argument("--mr", type=int, help="MR number (GitLab)")
    review_parser.add_argument("--diff", help="Path to local diff file")
    review_parser.add_argument("--title", help="PR title (for local diff)")
    review_parser.add_argument(
        "--platform",
        choices=["github", "gitlab", "bitbucket"],
        default="github",
        help="Platform (default: github)",
    )
    review_parser.add_argument(
        "--provider",
        choices=["openai", "anthropic", "groq", "ollama", "google"],
        help="LLM provider",
    )
    review_parser.add_argument("--model", help="Model name override")
    review_parser.add_argument("--api-key", help="API key (or use env var)")
    review_parser.add_argument("--post", action="store_true", help="Post review to platform")
    review_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show review output without posting (default when --post is not set)",
    )
    review_parser.add_argument(
        "--persona",
        choices=["default", "security-hawk", "mentor", "nitpicker", "quick-scan", "dora"],
        help="Review persona (overrides review style and priorities)",
    )
    review_parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output review as JSON (for CI integration)",
    )
    review_parser.add_argument("--bb-username", help="Bitbucket username")
    review_parser.add_argument("--bb-app-password", help="Bitbucket app password")
    review_parser.add_argument(
        "--config",
        help="Path to .pr-reviewer.yml config file",
    )
    review_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    review_parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Generate only a PR summary (no inline comments)",
    )
    review_parser.add_argument(
        "--exit-code",
        action="store_true",
        help="Exit with code 1 if critical issues found (for CI gating)",
    )

    # init command
    subparsers.add_parser(
        "init", help="Interactive setup wizard — generates config and workflow files"
    )

    # dashboard command
    dash_parser = subparsers.add_parser("dashboard", help="Launch analytics dashboard")
    dash_parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    dash_parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")

    # batch command
    batch_parser = subparsers.add_parser("batch", help="Review multiple PRs at once")
    batch_parser.add_argument("--repo", required=True, help="Repository (owner/name)")
    batch_parser.add_argument("--prs", type=int, nargs="*", help="Specific PR numbers")
    batch_parser.add_argument("--labels", nargs="*", help="Filter by labels")
    batch_parser.add_argument("--max", type=int, default=20, help="Max PRs to review")
    batch_parser.add_argument("--concurrency", type=int, default=3, help="Concurrent reviews")
    batch_parser.add_argument("--dry-run", action="store_true", help="Preview without posting")
    batch_parser.add_argument("--provider", help="LLM provider")
    batch_parser.add_argument("-v", "--verbose", action="store_true")

    # export command
    export_parser = subparsers.add_parser("export", help="Export review to SARIF/JSON/CSV")
    export_parser.add_argument("--repo", required=True, help="Repository")
    export_parser.add_argument("--pr", type=int, required=True, help="PR number")
    export_parser.add_argument(
        "--format", choices=["sarif", "json", "csv", "markdown"], default="json",
        help="Export format",
    )
    export_parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    export_parser.add_argument("--provider", help="LLM provider")
    export_parser.add_argument("-v", "--verbose", action="store_true")

    # validate command
    validate_parser = subparsers.add_parser("validate", help="Validate .pr-reviewer.yml config")
    validate_parser.add_argument("--config", default=".pr-reviewer.yml", help="Config file path")

    # stats command
    stats_parser = subparsers.add_parser("stats", help="Show local review telemetry stats")
    stats_parser.add_argument("--days", type=int, default=30, help="Days of history")
    stats_parser.add_argument("--clear", action="store_true", help="Clear telemetry data")

    args = parser.parse_args()

    if args.command == "review":
        asyncio.run(cmd_review(args))
    elif args.command == "init":
        from src.wizard import run_wizard

        run_wizard()
    elif args.command == "dashboard":
        import uvicorn

        from src.dashboard.server import app as dashboard_app

        logger.info(f"Dashboard: http://{args.host}:{args.port}")
        uvicorn.run(dashboard_app, host=args.host, port=args.port, log_level="info")
    elif args.command == "batch":
        asyncio.run(_cmd_batch(args))
    elif args.command == "export":
        asyncio.run(_cmd_export(args))
    elif args.command == "validate":
        _cmd_validate(args)
    elif args.command == "stats":
        _cmd_stats(args)
    else:
        parser.print_help()


async def _cmd_batch(args: argparse.Namespace) -> None:
    """Handle batch review command."""
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config = ReviewConfig.from_env()
    if args.provider:
        config.provider = args.provider
        config.model = ""
        config.__post_init__()

    from src.review.batch import batch_review, format_batch_summary

    summary = await batch_review(
        config=config,
        repo=args.repo,
        pr_numbers=args.prs,
        labels=args.labels,
        max_prs=args.max,
        concurrency=args.concurrency,
        dry_run=args.dry_run,
    )
    print(format_batch_summary(summary))


async def _cmd_export(args: argparse.Namespace) -> None:
    """Handle export command."""
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config = ReviewConfig.from_env()
    if args.provider:
        config.provider = args.provider
        config.model = ""
        config.__post_init__()

    engine = ReviewEngine(config)
    github = GitHubAPI(config.github_token)

    try:
        pr = await github.get_pr(args.repo, args.pr)
        files = await github.get_pr_files(args.repo, args.pr)
        diff = await github.get_pr_diff(args.repo, args.pr)
        result = await engine.review_pr(pr, files, diff)
    finally:
        await github.close()

    from src.review.export import export_csv, export_json, export_markdown, export_sarif

    exporters = {
        "json": export_json,
        "sarif": lambda r: export_sarif(r, args.repo),
        "csv": export_csv,
        "markdown": export_markdown,
    }

    output = exporters[args.format](result)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        logger.info(f"Exported to {args.output}")
    else:
        print(output)


def _cmd_validate(args: argparse.Namespace) -> None:
    """Handle validate command."""
    from pathlib import Path

    from src.review.config_validator import format_validation_result, validate_config

    result = validate_config(config_path=Path(args.config))
    print(format_validation_result(result))

    if not result.valid:
        sys.exit(1)


def _cmd_stats(args: argparse.Namespace) -> None:
    """Handle stats command."""
    from src.review.telemetry import TelemetryCollector, format_stats

    collector = TelemetryCollector()

    if args.clear:
        count = collector.clear()
        print(f"Cleared {count} telemetry files.")
        return

    stats = collector.get_stats(days=args.days)
    print(format_stats(stats))


if __name__ == "__main__":
    main()
