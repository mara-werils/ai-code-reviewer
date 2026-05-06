"""Sample main module for testing."""

import os
from pathlib import Path


class AppConfig:
    """Application configuration."""

    def __init__(self, env: str = "development"):
        self.env = env
        self.debug = env == "development"
        self.base_dir = Path(__file__).parent

    def get_database_url(self) -> str:
        return os.environ.get("DATABASE_URL", "sqlite:///app.db")

    def is_production(self) -> bool:
        return self.env == "production"


def create_app(config: AppConfig | None = None) -> dict:
    """Create and configure the application."""
    if config is None:
        config = AppConfig()

    return {
        "config": config,
        "version": "1.0.0",
    }


async def health_check() -> dict:
    """Check application health."""
    return {"status": "ok", "version": "1.0.0"}


if __name__ == "__main__":
    app = create_app()
    print(f"App created: {app}")
