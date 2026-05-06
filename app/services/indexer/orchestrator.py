import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import UUID

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, Repository
from app.services.embedding_service import EmbeddingService
from app.services.indexer.chunkers.base import CodeChunk
from app.services.indexer.chunkers.markdown import MarkdownChunker
from app.services.indexer.chunkers.python_ast import PythonChunker
from app.services.indexer.chunkers.tree_sitter import TreeSitterChunker
from app.services.indexer.walker import walk_repository

logger = structlog.get_logger()

CHUNKER_MAP = {
    "python": PythonChunker(),
    "javascript": TreeSitterChunker("javascript"),
    "typescript": TreeSitterChunker("typescript"),
    "go": TreeSitterChunker("go"),
    "markdown": MarkdownChunker(),
}

EMBEDDING_BATCH_SIZE = 100


async def index_repository(
    session: AsyncSession,
    repo_id: UUID,
    github_full_name: str,
    sha: str | None = None,
    clone_url: str | None = None,
    local_path: str | None = None,
) -> int:
    """Index a repository: clone, chunk, embed, store. Returns number of chunks."""
    logger.info("indexing_start", repo=github_full_name, sha=sha)

    # Update status
    result = await session.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one()
    repo.indexing_status = "indexing"
    await session.flush()

    tmp_dir = None
    try:
        if local_path:
            repo_path = local_path
        else:
            # Clone repository
            tmp_dir = tempfile.mkdtemp(prefix="pr-reviewer-")
            url = clone_url or f"https://github.com/{github_full_name}.git"
            clone_args = ["git", "clone", "--depth=1"]
            if sha:
                clone_args = ["git", "clone"]
            clone_args.extend([url, tmp_dir])

            subprocess.run(clone_args, check=True, capture_output=True, timeout=120)

            if sha:
                subprocess.run(
                    ["git", "checkout", sha],
                    cwd=tmp_dir,
                    check=True,
                    capture_output=True,
                )
            repo_path = tmp_dir

        # Walk and chunk
        files = walk_repository(repo_path)
        all_chunks: list[CodeChunk] = []

        for rel_path, content, language in files:
            chunker = CHUNKER_MAP.get(language)
            if not chunker:
                continue
            try:
                file_chunks = chunker.chunk(rel_path, content)  # type: ignore[attr-defined]
                all_chunks.extend(file_chunks)
            except Exception as e:
                logger.warning("chunk_failed", file=rel_path, error=str(e))
                continue

        logger.info("chunking_complete", total_chunks=len(all_chunks))

        # Compute content hashes
        chunk_hashes: list[tuple[CodeChunk, str]] = []
        for chunk in all_chunks:
            content_hash = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
            chunk_hashes.append((chunk, content_hash))

        # Get existing chunk hashes
        existing_result = await session.execute(
            select(
                Chunk.file_path, Chunk.identifier_coalesce, Chunk.start_line, Chunk.content_hash
            ).where(Chunk.repository_id == repo_id)
        )
        existing_map = {(row[0], row[1], row[2]): row[3] for row in existing_result.fetchall()}

        # Find new/changed chunks that need embedding
        to_embed: list[tuple[CodeChunk, str]] = []
        unchanged: list[tuple[CodeChunk, str]] = []

        for chunk, content_hash in chunk_hashes:
            key = (chunk.file_path, chunk.identifier or "", chunk.start_line)
            if existing_map.get(key) == content_hash:
                unchanged.append((chunk, content_hash))
            else:
                to_embed.append((chunk, content_hash))

        logger.info(
            "diff_computed",
            new_or_changed=len(to_embed),
            unchanged=len(unchanged),
        )

        # Compute embeddings in batches
        embedding_service = EmbeddingService(session=session)
        embeddings: list[list[float]] = []

        if to_embed:
            texts = [c.content[:8000] for c, _ in to_embed]  # Truncate long chunks
            embeddings = await embedding_service.embed_texts(texts, review_id=None)

        # Upsert chunks
        for i, (chunk, content_hash) in enumerate(to_embed):
            embedding = embeddings[i] if i < len(embeddings) else None

            # Check if exists for upsert
            existing = await session.execute(
                select(Chunk).where(
                    Chunk.repository_id == repo_id,
                    Chunk.file_path == chunk.file_path,
                    Chunk.identifier_coalesce == (chunk.identifier or ""),
                    Chunk.start_line == chunk.start_line,
                )
            )
            existing_chunk = existing.scalar_one_or_none()

            if existing_chunk:
                existing_chunk.content = chunk.content
                existing_chunk.content_hash = content_hash
                existing_chunk.chunk_type = chunk.chunk_type
                existing_chunk.end_line = chunk.end_line
                existing_chunk.language = chunk.language
                existing_chunk.metadata_ = chunk.metadata
                if embedding:
                    existing_chunk.embedding = embedding
            else:
                new_chunk = Chunk(
                    repository_id=repo_id,
                    file_path=chunk.file_path,
                    chunk_type=chunk.chunk_type,
                    identifier=chunk.identifier,
                    identifier_coalesce=chunk.identifier or "",
                    language=chunk.language,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    content=chunk.content,
                    content_hash=content_hash,
                    embedding=embedding,
                    metadata_=chunk.metadata,
                )
                session.add(new_chunk)

        # Delete chunks that no longer exist in repo
        current_keys = {(c.file_path, c.identifier or "", c.start_line) for c, _ in chunk_hashes}
        for key in existing_map:
            if key not in current_keys:
                await session.execute(
                    delete(Chunk).where(
                        Chunk.repository_id == repo_id,
                        Chunk.file_path == key[0],
                        Chunk.identifier_coalesce == key[1],
                        Chunk.start_line == key[2],
                    )
                )

        # Update repository status
        repo.indexing_status = "ready"
        repo.last_indexed_sha = sha
        await session.flush()

        total = len(chunk_hashes)
        logger.info("indexing_complete", repo=github_full_name, total_chunks=total)
        return total

    except Exception as e:
        logger.error("indexing_failed", repo=github_full_name, error=str(e))
        repo.indexing_status = "failed"
        await session.flush()
        raise
    finally:
        if tmp_dir and Path(tmp_dir).exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
