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

from src.bitbucket.client import BitbucketAPI
from src.config import ReviewConfig
from src.github.client import GitHubAPI
from src.gitlab.client import GitLabAPI
from src.review.engine import ReviewEngine
from src.review.formatter import format_review_body

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


async def cmd_review(args: argparse.Namespace) -> None:
    config = ReviewConfig.from_env()

    # Override from CLI args
    if args.provider:
        config.provider = args.provider
        config.model = ""
        config.__post_init__()  # Reset model default
    if args.model:
        config.model = args.model
    if args.api_key:
        config.api_key = args.api_key

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

    # Output
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
                    await bb.post_inline_comments(
                        workspace, repo_slug, mr_number, inline
                    )
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


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pr-reviewer",
        description="AI-powered code review for pull requests",
    )
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
    review_parser.add_argument("--provider", help="LLM provider (openai, anthropic, groq, ollama)")
    review_parser.add_argument("--model", help="Model name override")
    review_parser.add_argument("--api-key", help="API key (or use env var)")
    review_parser.add_argument("--post", action="store_true", help="Post review to platform")
    review_parser.add_argument("--bb-username", help="Bitbucket username")
    review_parser.add_argument("--bb-app-password", help="Bitbucket app password")

    args = parser.parse_args()

    if args.command == "review":
        asyncio.run(cmd_review(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
