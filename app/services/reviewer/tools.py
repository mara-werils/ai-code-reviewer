import asyncio
import time
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentToolCall, Chunk
from app.services.embedding_service import EmbeddingService
from app.services.retrieval_service import RetrievalService

logger = structlog.get_logger()

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "search_codebase",
        "description": "Search the indexed codebase using semantic search and identifier matching. Use this to find relevant code related to the changes being reviewed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query describing what you're looking for",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a specific file or portion of a file from the codebase. Use this when you need to see the full context of a specific file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file"},
                "start_line": {
                    "type": "integer",
                    "description": "Start line (optional, includes 10 lines of context above)",
                },
                "end_line": {
                    "type": "integer",
                    "description": "End line (optional, includes 10 lines of context below)",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "find_similar_functions",
        "description": "Find functions/methods semantically similar to a given signature. Use to check for code duplication.",
        "input_schema": {
            "type": "object",
            "properties": {
                "function_signature": {
                    "type": "string",
                    "description": "Function signature or description to search for",
                },
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["function_signature"],
        },
    },
    {
        "name": "find_usages",
        "description": "Find all usages of a specific identifier (function, class, variable) across the codebase.",
        "input_schema": {
            "type": "object",
            "properties": {
                "identifier": {
                    "type": "string",
                    "description": "Name of the function, class, or variable",
                },
            },
            "required": ["identifier"],
        },
    },
    {
        "name": "check_test_coverage",
        "description": "Check if a file has associated tests. Returns test file content and tested function names.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the source file to check tests for",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "lookup_past_discussions",
        "description": "Search documentation (README, ADR, etc.) for relevant architectural decisions or conventions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for in project documentation",
                },
                "top_k": {"type": "integer", "default": 3},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_file_diff_context",
        "description": "Get the structured diff for a specific file in the current PR.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the changed file"},
            },
            "required": ["file_path"],
        },
    },
]


class ToolRegistry:
    def __init__(
        self,
        session: AsyncSession,
        repo_id: UUID,
        review_id: UUID,
        diff_by_file: dict[str, str],
    ) -> None:
        self._session = session
        self._repo_id = repo_id
        self._review_id = review_id
        self._diff_by_file = diff_by_file
        self._retrieval = RetrievalService(session)
        self._embedding = EmbeddingService(session)

    @property
    def tool_definitions(self) -> list[dict[str, Any]]:
        return TOOL_DEFINITIONS

    async def dispatch(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        start = time.monotonic()
        success = True
        result = ""

        try:
            handler = getattr(self, f"_tool_{tool_name}", None)
            if not handler:
                return f"Unknown tool: {tool_name}"

            result = await asyncio.wait_for(handler(**tool_input), timeout=15.0)
            return result
        except TimeoutError:
            success = False
            result = f"Tool {tool_name} timed out after 15 seconds"
            return result
        except Exception as e:
            success = False
            result = f"Tool error: {str(e)}"
            logger.error("tool_error", tool=tool_name, error=str(e))
            return result
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            tool_call = AgentToolCall(
                review_id=self._review_id,
                tool_name=tool_name,
                tool_input=tool_input,
                tool_output_summary=result[:500] if result else None,
                duration_ms=duration_ms,
                success=success,
            )
            self._session.add(tool_call)

    async def _tool_search_codebase(self, query: str, top_k: int = 5) -> str:
        results = await self._retrieval.hybrid_search(
            repo_id=self._repo_id,
            query=query,
            top_k=top_k,
        )
        if not results:
            return "No results found."

        output_parts = []
        for r in results:
            output_parts.append(
                f"### {r.file_path} ({r.chunk_type}: {r.identifier or 'N/A'}) "
                f"[lines {r.start_line}-{r.end_line}] score={r.relevance_score:.3f}\n"
                f"```{r.language}\n{r.content[:2000]}\n```"
            )
        return "\n\n".join(output_parts)

    async def _tool_read_file(
        self, file_path: str, start_line: int | None = None, end_line: int | None = None
    ) -> str:
        result = await self._session.execute(
            select(Chunk)
            .where(Chunk.repository_id == self._repo_id, Chunk.file_path == file_path)
            .order_by(Chunk.start_line)
        )
        chunks = result.scalars().all()

        if not chunks:
            return f"File not found in index: {file_path}"

        # Reconstruct file content from chunks
        all_content = "\n".join(c.content for c in chunks)
        lines = all_content.split("\n")

        if start_line is not None and end_line is not None:
            ctx_start = max(0, start_line - 11)
            ctx_end = min(len(lines), end_line + 10)
            lines = lines[ctx_start:ctx_end]
            header = f"File: {file_path} (lines {ctx_start + 1}-{ctx_end})"
        else:
            header = f"File: {file_path} ({len(lines)} lines)"

        # Truncate if too long
        content = "\n".join(lines[:300])
        return f"{header}\n```\n{content}\n```"

    async def _tool_find_similar_functions(self, function_signature: str, top_k: int = 5) -> str:
        embedding = await self._embedding.embed_single(function_signature)

        result = await self._session.execute(
            text("""
                SELECT id, file_path, identifier, content, start_line, end_line,
                       embedding <=> :embedding AS distance
                FROM chunks
                WHERE repository_id = :repo_id
                  AND chunk_type IN ('function', 'method')
                  AND embedding IS NOT NULL
                ORDER BY distance
                LIMIT :limit
            """),
            {
                "embedding": str(embedding),
                "repo_id": self._repo_id,
                "limit": top_k,
            },
        )

        rows = result.fetchall()
        if not rows:
            return "No similar functions found."

        parts = []
        for row in rows:
            parts.append(
                f"### {row[1]} :: {row[2] or 'anonymous'} "
                f"(lines {row[4]}-{row[5]}, distance={row[6]:.3f})\n"
                f"```\n{row[3][:1500]}\n```"
            )
        return "\n\n".join(parts)

    async def _tool_find_usages(self, identifier: str) -> str:
        result = await self._session.execute(
            text("""
                SELECT file_path, start_line, end_line,
                       LEFT(content, 200) as snippet
                FROM chunks
                WHERE repository_id = :repo_id
                  AND (identifier = :name
                       OR content ILIKE '%%' || :name || '%%')
                LIMIT 20
            """),
            {"repo_id": self._repo_id, "name": identifier},
        )

        rows = result.fetchall()
        if not rows:
            return f"No usages of '{identifier}' found."

        parts = [f"Found {len(rows)} usages of '{identifier}':"]
        for row in rows:
            parts.append(f"- **{row[0]}** (lines {row[1]}-{row[2]}): `{row[3][:100]}...`")
        return "\n".join(parts)

    async def _tool_check_test_coverage(self, file_path: str) -> str:
        # Heuristic: look for test files
        name = file_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        patterns = [
            f"test_{name}",
            f"{name}_test",
            f"{name}.test",
            f"{name}.spec",
        ]

        results = []
        for pattern in patterns:
            result = await self._session.execute(
                select(Chunk)
                .where(
                    Chunk.repository_id == self._repo_id,
                    Chunk.file_path.ilike(f"%{pattern}%"),
                )
                .limit(10)
            )
            results.extend(result.scalars().all())

        if not results:
            return f"No test files found for {file_path}. This file may lack test coverage."

        parts = [f"Test coverage for {file_path}:"]
        test_functions = set()
        for chunk in results:
            if chunk.chunk_type in ("function", "method") and chunk.identifier:
                test_functions.add(chunk.identifier)
            parts.append(
                f"\n### {chunk.file_path} ({chunk.chunk_type}: {chunk.identifier or 'N/A'})\n"
                f"```\n{chunk.content[:1000]}\n```"
            )

        if test_functions:
            parts.insert(1, f"\nTest functions found: {', '.join(sorted(test_functions))}")

        return "\n".join(parts)

    async def _tool_lookup_past_discussions(self, query: str, top_k: int = 3) -> str:
        embedding = await self._embedding.embed_single(query)

        result = await self._session.execute(
            text("""
                SELECT file_path, identifier, content, start_line, end_line,
                       embedding <=> :embedding AS distance
                FROM chunks
                WHERE repository_id = :repo_id
                  AND chunk_type = 'markdown_section'
                  AND embedding IS NOT NULL
                ORDER BY distance
                LIMIT :limit
            """),
            {
                "embedding": str(embedding),
                "repo_id": self._repo_id,
                "limit": top_k,
            },
        )

        rows = result.fetchall()
        if not rows:
            return "No relevant documentation found."

        parts = []
        for row in rows:
            parts.append(f"### {row[0]} — {row[1] or 'Section'}\n{row[2][:2000]}")
        return "\n\n".join(parts)

    async def _tool_get_file_diff_context(self, file_path: str) -> str:
        diff = self._diff_by_file.get(file_path)
        if diff:
            return f"Diff for {file_path}:\n```diff\n{diff}\n```"
        return f"No diff found for {file_path} in this PR."
