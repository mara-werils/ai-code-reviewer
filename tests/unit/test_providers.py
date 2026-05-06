from src.config import ReviewConfig
from src.providers.anthropic_provider import AnthropicProvider
from src.providers.factory import create_provider
from src.providers.google_provider import GoogleProvider
from src.providers.groq_provider import GroqProvider
from src.providers.ollama_provider import OllamaProvider
from src.providers.openai_provider import OpenAIProvider


class TestProviderFactory:
    def test_creates_openai(self) -> None:
        config = ReviewConfig(provider="openai", api_key="test")
        provider = create_provider(config)
        assert isinstance(provider, OpenAIProvider)
        assert "openai" in provider.name

    def test_creates_anthropic(self) -> None:
        config = ReviewConfig(provider="anthropic", api_key="test")
        provider = create_provider(config)
        assert isinstance(provider, AnthropicProvider)
        assert "anthropic" in provider.name

    def test_creates_groq(self) -> None:
        config = ReviewConfig(provider="groq", api_key="test")
        provider = create_provider(config)
        assert isinstance(provider, GroqProvider)
        assert "groq" in provider.name

    def test_creates_ollama(self) -> None:
        config = ReviewConfig(provider="ollama")
        provider = create_provider(config)
        assert isinstance(provider, OllamaProvider)
        assert "ollama" in provider.name

    def test_creates_google(self) -> None:
        config = ReviewConfig(provider="google", api_key="test")
        provider = create_provider(config)
        assert isinstance(provider, GoogleProvider)


class TestCostEstimation:
    def test_openai_cost(self) -> None:
        p = OpenAIProvider(api_key="test", model="gpt-4o")
        cost = p.estimate_cost(1_000_000, 1_000_000)
        assert cost == 2.50 + 10.00

    def test_groq_cost(self) -> None:
        p = GroqProvider(api_key="test")
        cost = p.estimate_cost(1_000_000, 1_000_000)
        assert cost > 0
        assert cost < 5  # Groq is cheap

    def test_ollama_free(self) -> None:
        p = OllamaProvider()
        cost = p.estimate_cost(1_000_000, 1_000_000)
        assert cost == 0.0
