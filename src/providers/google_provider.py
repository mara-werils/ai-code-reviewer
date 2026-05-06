"""Google Gemini provider."""

from __future__ import annotations

from openai import AsyncOpenAI

from src.providers.base import LLMProvider, LLMResponse

PRICING = {
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash-preview-05-20": {"input": 0.15, "output": 0.60},
    "gemini-2.5-pro-preview-05-06": {"input": 1.25, "output": 10.00},
}


class GoogleProvider(LLMProvider):
    """Google Gemini via OpenAI-compatible API."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self._model = model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )

    @property
    def name(self) -> str:
        return f"google/{self._model}"

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
            cost_usd=self.estimate_cost(input_tokens, output_tokens),
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        pricing = PRICING.get(self._model, PRICING["gemini-2.0-flash"])
        return (input_tokens / 1_000_000) * pricing["input"] + \
               (output_tokens / 1_000_000) * pricing["output"]
