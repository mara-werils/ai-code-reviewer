"""Provider factory — create the right LLM provider from config."""

from __future__ import annotations

from src.config import ReviewConfig
from src.providers.base import LLMProvider


def create_provider(config: ReviewConfig) -> LLMProvider:
    """Create an LLM provider based on configuration."""
    if config.provider == "openai":
        from src.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=config.api_key,
            model=config.model,
            base_url=config.api_base_url,
        )

    if config.provider == "anthropic":
        from src.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            api_key=config.api_key,
            model=config.model,
        )

    if config.provider == "groq":
        from src.providers.groq_provider import GroqProvider

        return GroqProvider(
            api_key=config.api_key,
            model=config.model,
        )

    if config.provider == "ollama":
        from src.providers.ollama_provider import OllamaProvider

        return OllamaProvider(
            model=config.model,
            base_url=config.api_base_url or "http://localhost:11434/v1",
        )

    if config.provider == "google":
        from src.providers.google_provider import GoogleProvider

        return GoogleProvider(
            api_key=config.api_key,
            model=config.model,
        )

    # Default: try OpenAI-compatible with base_url
    from src.providers.openai_provider import OpenAIProvider

    return OpenAIProvider(
        api_key=config.api_key,
        model=config.model,
        base_url=config.api_base_url,
    )
