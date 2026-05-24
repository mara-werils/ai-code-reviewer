"""Custom OpenAI-compatible provider for any LLM endpoint.

Supports vLLM, LiteLLM, LocalAI, Together AI, Fireworks AI,
Anyscale, Deepseek, Mistral, and any OpenAI-compatible API.

Configuration via environment variables:
  CUSTOM_API_KEY, CUSTOM_API_BASE, CUSTOM_MODEL,
  CUSTOM_PRICING_INPUT, CUSTOM_PRICING_OUTPUT (per 1M tokens)
"""

from __future__ import annotations

import os

from openai import AsyncOpenAI

from src.providers.base import LLMProvider, LLMResponse
from src.providers.retry import with_retry

# Well-known OpenAI-compatible providers and their defaults
KNOWN_PROVIDERS: dict[str, dict] = {
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "env_key": "TOGETHER_API_KEY",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "pricing": {"input": 0.88, "output": 0.88},
    },
    "fireworks": {
        "base_url": "https://api.fireworks.ai/inference/v1",
        "env_key": "FIREWORKS_API_KEY",
        "default_model": "accounts/fireworks/models/llama-v3p3-70b-instruct",
        "pricing": {"input": 0.90, "output": 0.90},
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "env_key": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "pricing": {"input": 0.14, "output": 0.28},
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "env_key": "MISTRAL_API_KEY",
        "default_model": "mistral-large-latest",
        "pricing": {"input": 2.00, "output": 6.00},
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "env_key": "OPENROUTER_API_KEY",
        "default_model": "anthropic/claude-sonnet-4",
        "pricing": {"input": 3.00, "output": 15.00},
    },
    "anyscale": {
        "base_url": "https://api.endpoints.anyscale.com/v1",
        "env_key": "ANYSCALE_API_KEY",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct",
        "pricing": {"input": 1.00, "output": 1.00},
    },
    "lmstudio": {
        "base_url": "http://localhost:1234/v1",
        "env_key": "",
        "default_model": "local-model",
        "pricing": {"input": 0, "output": 0},
    },
}


class CustomProvider(LLMProvider):
    """Generic OpenAI-compatible provider for any LLM endpoint."""

    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        base_url: str = "",
        provider_name: str = "custom",
        pricing_input: float = 0.0,
        pricing_output: float = 0.0,
    ) -> None:
        known = KNOWN_PROVIDERS.get(provider_name, {})

        self._provider_name = provider_name
        self._model = model or known.get("default_model", "gpt-4o")
        self._pricing_input = pricing_input or known.get("pricing", {}).get("input", 0)
        self._pricing_output = pricing_output or known.get("pricing", {}).get("output", 0)

        effective_key = api_key or os.getenv(known.get("env_key", ""), "")
        effective_base = base_url or known.get("base_url", "")

        kwargs: dict = {}
        if effective_key:
            kwargs["api_key"] = effective_key
        else:
            kwargs["api_key"] = "not-needed"

        if effective_base:
            kwargs["base_url"] = effective_base

        self._client = AsyncOpenAI(**kwargs)

    @property
    def name(self) -> str:
        return f"{self._provider_name}/{self._model}"

    @with_retry(max_retries=3, base_delay=1.0)
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
        return (input_tokens / 1_000_000) * self._pricing_input + (
            output_tokens / 1_000_000
        ) * self._pricing_output
