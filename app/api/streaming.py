import asyncio
import json

import structlog
from fastapi import APIRouter
from redis.asyncio import Redis
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings

logger = structlog.get_logger()
router = APIRouter(tags=["streaming"])


@router.get("/reviews/{review_id}/stream")
async def stream_review_progress(review_id: str) -> EventSourceResponse:
    settings = get_settings()

    async def event_generator():  # type: ignore[no-untyped-def]
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        pubsub = redis.pubsub()
        channel = f"review:{review_id}"
        await pubsub.subscribe(channel)

        try:
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message["type"] == "message":
                    data = json.loads(message["data"])
                    event_type = data.get("event", "progress")

                    yield {
                        "event": event_type,
                        "data": json.dumps(data),
                    }

                    if event_type == "done":
                        break
                else:
                    # Send keepalive
                    yield {"event": "ping", "data": ""}
                    await asyncio.sleep(1)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            await redis.aclose()

    return EventSourceResponse(event_generator())
