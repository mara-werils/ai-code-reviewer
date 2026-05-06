from collections import defaultdict
from uuid import UUID

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk
from app.services.embedding_service import EmbeddingService
from app.services.indexer.chunkers.base import CodeChunk

logger = structlog.get_logger()


class RetrievedChunk(CodeChunk):
    chunk_id: UUID
    relevance_score: float = 0.0


class RetrievalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._embedding_service = EmbeddingService(session=session)

    async def hybrid_search(
        self,
        repo_id: UUID,
        query: str,
        identifiers_in_diff: list[str] | None = None,
        file_paths_in_diff: list[str] | None = None,
        top_k: int = 10,
    ) -> list[RetrievedChunk]:
        ranked_lists: list[list[tuple[UUID, float]]] = []

        # 1. Vector search
        query_embedding = await self._embedding_service.embed_single(query)
        vector_results = await self._vector_search(repo_id, query_embedding, limit=20)
        ranked_lists.append(vector_results)

        # 2. Identifier search
        if identifiers_in_diff:
            for identifier in identifiers_in_diff[:10]:  # Limit to 10
                id_results = await self._identifier_search(repo_id, identifier, limit=5)
                if id_results:
                    ranked_lists.append(id_results)

        # 3. File neighborhood
        if file_paths_in_diff:
            neighbor_results = await self._file_neighborhood(repo_id, file_paths_in_diff)
            if neighbor_results:
                ranked_lists.append(neighbor_results)

        # 4. RRF fusion
        fused_scores = self._reciprocal_rank_fusion(ranked_lists, k=60)

        # 5. Deduplicate and sort
        top_ids = sorted(fused_scores.keys(), key=lambda x: fused_scores[x], reverse=True)[:top_k]

        # Fetch full chunks
        if not top_ids:
            return []

        result = await self._session.execute(select(Chunk).where(Chunk.id.in_(top_ids)))
        chunks_map = {c.id: c for c in result.scalars().all()}

        retrieved: list[RetrievedChunk] = []
        for chunk_id in top_ids:
            chunk = chunks_map.get(chunk_id)
            if chunk:
                retrieved.append(
                    RetrievedChunk(
                        chunk_id=chunk.id,
                        file_path=chunk.file_path,
                        chunk_type=chunk.chunk_type,
                        identifier=chunk.identifier,
                        language=chunk.language,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                        content=chunk.content,
                        metadata=chunk.metadata_,
                        relevance_score=fused_scores[chunk_id],
                    )
                )

        return retrieved

    async def _vector_search(
        self, repo_id: UUID, embedding: list[float], limit: int = 20
    ) -> list[tuple[UUID, float]]:
        result = await self._session.execute(
            text("""
                SELECT id, embedding <=> :embedding AS distance
                FROM chunks
                WHERE repository_id = :repo_id
                  AND embedding IS NOT NULL
                ORDER BY distance
                LIMIT :limit
            """),
            {"embedding": str(embedding), "repo_id": repo_id, "limit": limit},
        )
        return [(row[0], 1.0 - row[1]) for row in result.fetchall()]  # Convert distance to score

    async def _identifier_search(
        self, repo_id: UUID, identifier: str, limit: int = 5
    ) -> list[tuple[UUID, float]]:
        result = await self._session.execute(
            text("""
                SELECT id, similarity(identifier, :name) AS sim
                FROM chunks
                WHERE repository_id = :repo_id
                  AND (identifier %% :name OR content ILIKE '%%' || :name || '%%')
                ORDER BY sim DESC
                LIMIT :limit
            """),
            {"repo_id": repo_id, "name": identifier, "limit": limit},
        )
        return [(row[0], float(row[1])) for row in result.fetchall()]

    async def _file_neighborhood(
        self, repo_id: UUID, file_paths: list[str]
    ) -> list[tuple[UUID, float]]:
        # Get chunks from same files + same directories
        dirs = list({"/".join(fp.split("/")[:-1]) for fp in file_paths if "/" in fp})

        conditions = []
        params: dict[str, object] = {"repo_id": repo_id}

        for i, fp in enumerate(file_paths[:20]):
            conditions.append(f"file_path = :fp_{i}")
            params[f"fp_{i}"] = fp

        for i, d in enumerate(dirs[:10]):
            conditions.append(f"file_path LIKE :dir_{i}")
            params[f"dir_{i}"] = f"{d}/%"

        if not conditions:
            return []

        where_clause = " OR ".join(conditions)
        result = await self._session.execute(
            text(f"""
                SELECT id FROM chunks
                WHERE repository_id = :repo_id AND ({where_clause})
                LIMIT 30
            """),
            params,
        )
        return [(row[0], 0.5) for row in result.fetchall()]  # Fixed score for neighborhood

    @staticmethod
    def _reciprocal_rank_fusion(
        ranked_lists: list[list[tuple[UUID, float]]],
        k: int = 60,
    ) -> dict[UUID, float]:
        scores: dict[UUID, float] = defaultdict(float)

        for ranked_list in ranked_lists:
            for rank, (chunk_id, _) in enumerate(ranked_list):
                scores[chunk_id] += 1.0 / (k + rank + 1)

        return dict(scores)
