"""Webhook retry queue — reliable webhook delivery with retry logic.

Ensures notification webhooks (Slack, Discord, Teams) are delivered
reliably with exponential backoff, dead letter queue, and deduplication.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class WebhookStatus(Enum):
    PENDING = "pending"
    SENDING = "sending"
    DELIVERED = "delivered"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


@dataclass
class WebhookMessage:
    """A webhook message to deliver."""

    id: str
    url: str
    payload: dict
    created_at: float = field(default_factory=time.time)
    attempts: int = 0
    max_attempts: int = 5
    status: WebhookStatus = WebhookStatus.PENDING
    last_error: str = ""
    next_retry_at: float = 0.0


class WebhookQueue:
    """Reliable webhook delivery queue with retry logic."""

    def __init__(
        self,
        max_concurrent: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 300.0,
    ) -> None:
        self._queue: deque[WebhookMessage] = deque()
        self._dead_letters: list[WebhookMessage] = []
        self._delivered: list[str] = []  # Recent delivered IDs for dedup
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._seen_ids: set[str] = set()

    def _make_id(self, url: str, payload: dict) -> str:
        """Generate unique ID for deduplication."""
        content = json.dumps({"url": url, "payload": payload}, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def enqueue(self, url: str, payload: dict, max_attempts: int = 5) -> str:
        """Add a webhook to the delivery queue."""
        msg_id = self._make_id(url, payload)

        # Deduplicate
        if msg_id in self._seen_ids:
            logger.debug(f"Webhook {msg_id} already queued, skipping")
            return msg_id

        self._seen_ids.add(msg_id)

        msg = WebhookMessage(
            id=msg_id,
            url=url,
            payload=payload,
            max_attempts=max_attempts,
        )
        self._queue.append(msg)
        logger.debug(f"Webhook {msg_id} enqueued for {url}")
        return msg_id

    async def process(self) -> list[WebhookMessage]:
        """Process all pending webhooks."""
        results: list[WebhookMessage] = []

        while self._queue:
            msg = self._queue.popleft()

            # Check if it's too early to retry
            if msg.next_retry_at > time.time():
                self._queue.append(msg)  # Put back
                await asyncio.sleep(0.1)
                continue

            result = await self._send(msg)
            results.append(result)

        return results

    async def _send(self, msg: WebhookMessage) -> WebhookMessage:
        """Send a single webhook with retry logic."""
        async with self._semaphore:
            msg.attempts += 1
            msg.status = WebhookStatus.SENDING

            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        msg.url,
                        json=msg.payload,
                        headers={"Content-Type": "application/json"},
                    )
                    resp.raise_for_status()

                msg.status = WebhookStatus.DELIVERED
                self._delivered.append(msg.id)
                logger.info(f"Webhook {msg.id} delivered to {msg.url}")

            except httpx.HTTPError as e:
                msg.last_error = str(e)

                if msg.attempts >= msg.max_attempts:
                    msg.status = WebhookStatus.DEAD_LETTER
                    self._dead_letters.append(msg)
                    logger.warning(
                        f"Webhook {msg.id} moved to dead letter after "
                        f"{msg.attempts} attempts: {e}"
                    )
                else:
                    msg.status = WebhookStatus.FAILED
                    delay = min(
                        self._base_delay * (2 ** (msg.attempts - 1)),
                        self._max_delay,
                    )
                    msg.next_retry_at = time.time() + delay
                    self._queue.append(msg)
                    logger.info(
                        f"Webhook {msg.id} failed (attempt {msg.attempts}), "
                        f"retrying in {delay:.1f}s: {e}"
                    )

            return msg

    @property
    def pending_count(self) -> int:
        return len(self._queue)

    @property
    def dead_letter_count(self) -> int:
        return len(self._dead_letters)

    @property
    def delivered_count(self) -> int:
        return len(self._delivered)

    def get_dead_letters(self) -> list[WebhookMessage]:
        """Get messages that failed all retry attempts."""
        return list(self._dead_letters)

    def retry_dead_letters(self) -> int:
        """Move dead letters back to the queue for retry."""
        count = len(self._dead_letters)
        for msg in self._dead_letters:
            msg.status = WebhookStatus.PENDING
            msg.attempts = 0
            self._queue.append(msg)
        self._dead_letters.clear()
        return count

    def get_stats(self) -> dict:
        """Get queue statistics."""
        return {
            "pending": self.pending_count,
            "delivered": self.delivered_count,
            "dead_letter": self.dead_letter_count,
            "total_seen": len(self._seen_ids),
        }
