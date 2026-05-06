"""Ollama provider — 100% local, 100% free, 100% private."""

from __future__ import annotations

from openai import AsyncOpenAI

from src.providers.base import LLMProvider, LLMResponse


class OllamaProvider(LLMProvider):
    """Ollama — run models locally. Zero cost, full privacy."""

    def __init__(
        self,
        model: str = "llama3.1:8b",
        base_url: str = "http://localhost:11434/v1",
    ) -> None:
        self._model = model
        self._client = AsyncOpenAI(
            api_key="ollama",  # Ollama doesn't need a key
            base_url=base_url,
        )

    @property
    def name(self) -> str:
        return f"ollama/{self._model}"

    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> LLMResponse:
        kwargs: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        resp = await self._client.chat.completions.create(**kwargs)

        content = resp.choices[0].message.content or ""
        input_tokens = resp.usage.prompt_tokens if resp.usage else 0
        output_tokens = resp.usage.completion_tokens if resp.usage else 0

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self._model,
            cost_usd=0.0,  # Free!
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0
