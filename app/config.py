from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql+asyncpg://pr_reviewer:pr_reviewer@localhost:5432/pr_reviewer"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Anthropic
    anthropic_api_key: str = ""

    # OpenAI
    openai_api_key: str = ""

    # GitHub App
    github_app_id: int = 0
    github_private_key_path: Path = Path("./github-app-private-key.pem")
    github_webhook_secret: str = ""

    # Review limits
    review_cost_limit_usd: float = Field(default=0.50)
    monthly_cost_budget_usd: float = Field(default=50.00)
    max_tool_iterations: int = Field(default=8)

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000


def get_settings() -> Settings:
    return Settings()
