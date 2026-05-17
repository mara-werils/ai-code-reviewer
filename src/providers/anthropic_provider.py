"""Anthropic provider (Claude Sonnet, Haiku, Opus)."""

from __future__ import annotations

import anthropic

from src.providers.base import LLMProvider, LLMResponse
from src.providers.retry import with_retry

PRICING = {
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-6-20260517": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
    "claude-opus-4-6-20260517": {"input": 15.00, "output": 75.00},
}

JSON_SUFFIX = (
    "\n\nIMPORTANT: You MUST respond with ONLY a valid JSON object. No text before or after."
)


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514") -> None:
        self._model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    @property
    def name(self) -> str:
        return f"anthropic/{self._model}"

    @with_retry(max_retries=3, base_delay=1.0)
    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> LLMResponse:
        system = ""
        api_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                api_messages.append(msg)

        # Anthropic doesn't have a native json_mode flag —
        # enforce JSON output via system prompt + prefill.
        if json_mode:
            system += JSON_SUFFIX
            # Prefill assistant response with "{" to force JSON
            api_messages.append({"role": "assistant", "content": "{"})

        kwargs: dict = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system

        resp = await self._client.messages.create(**kwargs)

        content = resp.content[0].text if resp.content else ""
        # If we prefilled with "{", prepend it back
        if json_mode:
            content = "{" + content

        return LLMResponse(
            content=content,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            model=self._model,
            cost_usd=self.estimate_cost(resp.usage.input_tokens, resp.usage.output_tokens),
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        pricing = PRICING.get(self._model, PRICING["claude-sonnet-4-20250514"])
        return (input_tokens / 1_000_000) * pricing["input"] + (
            output_tokens / 1_000_000
        ) * pricing["output"]
