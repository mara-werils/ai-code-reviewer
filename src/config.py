"""Configuration management — supports env vars, action inputs, and .pr-reviewer.yml."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Provider-specific diff size limits (conservative, for free tiers)
_PROVIDER_MAX_DIFF: dict[str, int] = {
    "groq": 10000,  # Groq free tier: 12k TPM, leave room for system prompt + output
    "ollama": 12000,  # Local models often have smaller context
}

VALID_PROVIDERS = {"openai", "anthropic", "groq", "ollama", "google"}

MODEL_DEFAULTS: dict[str, str] = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-20250514",
    "groq": "llama-3.3-70b-versatile",
    "ollama": "llama3.1:8b",
    "google": "gemini-2.0-flash",
}


@dataclass
class ReviewConfig:
    """Configuration for a review run."""

    # LLM Provider
    provider: str = "openai"  # openai, anthropic, groq, ollama, google
    model: str = ""  # auto-selected per provider if empty
    api_key: str = ""
    api_base_url: str = ""

    # Review behavior
    review_language: str = "en"
    max_files: int = 50
    max_diff_size: int = 30000  # chars
    ignore_paths: list[str] = field(
        default_factory=lambda: [
            "*.lock",
            "*.min.js",
            "*.min.css",
            "*.map",
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "poetry.lock",
            "Cargo.lock",
            "go.sum",
            "*.pb.go",
            "*.generated.*",
            "*_generated.*",
            "vendor/**",
            "node_modules/**",
            "dist/**",
            "build/**",
        ]
    )
    ignore_titles: list[str] = field(
        default_factory=lambda: [
            "WIP",
            "DO NOT MERGE",
            "DRAFT",
        ]
    )

    # Review style
    review_style: str = "concise"  # concise, thorough, minimal
    severity_threshold: str = "info"  # info, suggestion, warning, critical
    max_comments: int = 15
    collapse_below: str = "info"
    custom_instructions: str = ""

    # Persona
    persona: str = ""  # default, security-hawk, mentor, nitpicker, quick-scan, dora

    # Features
    auto_summarize: bool = True
    check_security: bool = True
    check_performance: bool = True
    check_correctness: bool = True
    check_best_practices: bool = True
    suggest_tests: bool = True
    label_pr: bool = False

    # Self-hosted features
    enable_rag: bool = False
    database_url: str = ""
    redis_url: str = ""

    # GitHub
    github_token: str = ""

    # GitLab
    gitlab_token: str = ""
    gitlab_url: str = "https://gitlab.com"

    # Cost
    cost_limit_usd: float = 1.00

    def __post_init__(self) -> None:
        # Validate provider name
        if self.provider not in VALID_PROVIDERS:
            logger.warning(
                "Unknown provider '%s', falling back to openai. "
                "Valid providers: %s",
                self.provider,
                ", ".join(sorted(VALID_PROVIDERS)),
            )
            self.provider = "openai"

        if not self.model:
            self.model = MODEL_DEFAULTS.get(self.provider, "gpt-4o")

        # Auto-reduce diff size for providers with tight token limits
        provider_limit = _PROVIDER_MAX_DIFF.get(self.provider)
        if provider_limit and self.max_diff_size > provider_limit:
            self.max_diff_size = provider_limit

    @classmethod
    def from_env(cls) -> ReviewConfig:
        """Load config from environment variables (GitHub Action inputs)."""
        provider = os.getenv("INPUT_PROVIDER", os.getenv("PROVIDER", "openai"))

        # Auto-detect provider from available API keys
        if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
            if os.getenv("ANTHROPIC_API_KEY"):
                provider = "anthropic"
            elif os.getenv("GROQ_API_KEY"):
                provider = "groq"
            elif os.getenv("GOOGLE_API_KEY"):
                provider = "google"

        api_key_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "groq": "GROQ_API_KEY",
            "google": "GOOGLE_API_KEY",
            "ollama": "",
        }
        api_key_env = api_key_map.get(provider, "OPENAI_API_KEY")
        api_key = os.getenv(api_key_env, "")

        # Safe int parsing
        try:
            max_comments = int(os.getenv("INPUT_MAX_COMMENTS", os.getenv("MAX_COMMENTS", "15")))
        except ValueError:
            max_comments = 15

        config = cls(
            provider=provider,
            model=os.getenv("INPUT_MODEL", os.getenv("MODEL", "")),
            api_key=api_key,
            api_base_url=os.getenv("INPUT_API_BASE_URL", os.getenv("API_BASE_URL", "")),
            github_token=os.getenv("GITHUB_TOKEN", ""),
            gitlab_token=os.getenv("GITLAB_TOKEN", ""),
            gitlab_url=os.getenv("GITLAB_URL", os.getenv("CI_SERVER_URL", "https://gitlab.com")),
            review_language=os.getenv("INPUT_LANGUAGE", os.getenv("LANGUAGE", "en")),
            review_style=os.getenv("INPUT_REVIEW_STYLE", os.getenv("REVIEW_STYLE", "concise")),
            max_comments=max_comments,
            custom_instructions=os.getenv("INPUT_CUSTOM_INSTRUCTIONS", ""),
            auto_summarize=os.getenv("INPUT_AUTO_SUMMARIZE", "true").lower() == "true",
            suggest_tests=os.getenv("INPUT_SUGGEST_TESTS", "true").lower() == "true",
            label_pr=os.getenv("INPUT_LABEL_PR", "false").lower() == "true",
        )

        return config

    @classmethod
    def from_yaml(cls, path: Path, base: ReviewConfig | None = None) -> ReviewConfig:
        """Load config from .pr-reviewer.yml, merging with base config."""
        config = base or cls.from_env()

        if not path.exists():
            return config

        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse {path}: {e}")
            return config

        field_types = {
            "max_comments": int,
            "max_files": int,
            "max_diff_size": int,
            "cost_limit_usd": float,
            "auto_summarize": bool,
            "suggest_tests": bool,
            "label_pr": bool,
            "check_security": bool,
            "check_performance": bool,
            "check_correctness": bool,
            "check_best_practices": bool,
            "enable_rag": bool,
        }

        for key, value in data.items():
            if not hasattr(config, key) or key.startswith("_"):
                continue
            expected = field_types.get(key)
            if expected and not isinstance(value, expected):
                try:
                    value = expected(value)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid type for config key '{key}': {value}")
                    continue
            setattr(config, key, value)

        return config
