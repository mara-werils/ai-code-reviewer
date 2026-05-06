"""CLI script to manually index a repository.

Usage:
    python -m scripts.index_repo --repo owner/name [--local-path /path/to/repo]
"""

import argparse
import asyncio

from app.db.models import Repository
from app.db.session import async_session_factory
from app.services.indexer.orchestrator import index_repository


async def main(repo_name: str, local_path: str | None = None) -> None:
    async with async_session_factory() as session:
        # Find or create repository
        from sqlalchemy import select

        result = await session.execute(
            select(Repository).where(Repository.github_full_name == repo_name)
        )
        repo = result.scalar_one_or_none()

        if not repo:
            repo = Repository(
                github_full_name=repo_name,
                installation_id=0,
            )
            session.add(repo)
            await session.flush()
            print(f"Created repository record: {repo.id}")

        print(f"Indexing {repo_name}...")
        total = await index_repository(
            session=session,
            repo_id=repo.id,
            github_full_name=repo_name,
            local_path=local_path,
        )
        await session.commit()
        print(f"Done! Indexed {total} chunks.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index a repository")
    parser.add_argument("--repo", required=True, help="Repository full name (owner/name)")
    parser.add_argument("--local-path", help="Local path to repo (skip cloning)")
    args = parser.parse_args()

    asyncio.run(main(args.repo, args.local_path))
