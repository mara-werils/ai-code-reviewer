import time
from uuid import UUID

import structlog
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.core.cost_tracker import calculate_cost
from app.db.models import LLMCall

logger = structlog.get_logger()

MODEL = "text-embedding-3-small"
BATCH_SIZE = 100
DIMENSIONS = 1536


class EmbeddingService:
    def __init__(self, session: AsyncSession | None = None) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._session = session

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=30),
    )
    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        resp = await self._client.embeddings.create(
            model=MODEL,
            input=texts,
            dimensions=DIMENSIONS,
        )
        return [item.embedding for item in resp.data]

    async def embed_texts(
        self,
        texts: list[str],
        review_id: UUID | None = None,
    ) -> list[list[float]]:
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            start = time.monotonic()

            try:
                embeddings = await self._embed_batch(batch)
                latency_ms = int((time.monotonic() - start) * 1000)
                all_embeddings.extend(embeddings)

                # Estimate tokens (~4 chars per token)
                input_tokens = sum(len(t) // 4 for t in batch)
                cost = calculate_cost(MODEL, input_tokens, 0)

                if self._session:
                    llm_call = LLMCall(
                        review_id=review_id,
                        purpose="embedding",
                        model=MODEL,
                        input_tokens=input_tokens,
                        output_tokens=0,
                        cost_usd=float(cost),
                        latency_ms=latency_ms,
                        success=True,
                    )
                    self._session.add(llm_call)

                logger.info(
                    "embedding_batch_complete",
                    batch_size=len(batch),
                    latency_ms=latency_ms,
                )
            except Exception as e:
                logger.error("embedding_batch_failed", error=str(e), batch_size=len(batch))
                raise

        return all_embeddings

    async def embed_single(self, text: str) -> list[float]:
        results = await self.embed_texts([text])
        return results[0]
