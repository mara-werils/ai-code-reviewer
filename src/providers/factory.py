"""Provider factory — create the right LLM provider from config."""

from __future__ import annotations

import logging

from src.config import ReviewConfig
from src.providers.base import LLMProvider

logger = logging.getLogger(__name__)

_API_KEY_ENVS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "groq": "GROQ_API_KEY",
    "google": "GOOGLE_API_KEY",
}


def _check_api_key(config: ReviewConfig) -> None:
    """Warn if API key is missing for a provider that requires one."""
    if config.provider == "ollama":
        return
    if not config.api_key:
        env_var = _API_KEY_ENVS.get(config.provider, f"{config.provider.upper()}_API_KEY")
        logger.warning(
            "No API key for provider '%s'. Set %s or pass --api-key.",
            config.provider,
            env_var,
        )


def create_provider(config: ReviewConfig) -> LLMProvider:
    """Create an LLM provider based on configuration."""
    _check_api_key(config)

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

    # Check for known custom providers (together, fireworks, deepseek, mistral, openrouter, etc.)
    from src.providers.custom_provider import KNOWN_PROVIDERS, CustomProvider

    if config.provider in KNOWN_PROVIDERS:
        return CustomProvider(
            api_key=config.api_key,
            model=config.model,
            base_url=config.api_base_url,
            provider_name=config.provider,
        )

    # Default: try as custom OpenAI-compatible provider with base_url
    if config.api_base_url:
        return CustomProvider(
            api_key=config.api_key,
            model=config.model,
            base_url=config.api_base_url,
            provider_name=config.provider or "custom",
        )

    # Fallback to OpenAI
    from src.providers.openai_provider import OpenAIProvider

    return OpenAIProvider(
        api_key=config.api_key,
        model=config.model,
        base_url=config.api_base_url,
    )
