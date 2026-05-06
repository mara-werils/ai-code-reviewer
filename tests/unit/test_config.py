import os
from unittest.mock import patch

from src.config import ReviewConfig


class TestReviewConfig:
    def test_defaults(self) -> None:
        config = ReviewConfig()
        assert config.provider == "openai"
        assert config.model == "gpt-4o"
        assert config.max_comments == 15

    def test_model_auto_select(self) -> None:
        config = ReviewConfig(provider="anthropic")
        assert "claude" in config.model

        config = ReviewConfig(provider="groq")
        assert "llama" in config.model

    def test_from_env(self) -> None:
        env = {
            "INPUT_PROVIDER": "groq",
            "GROQ_API_KEY": "test-key",
            "GITHUB_TOKEN": "gh-token",
            "INPUT_MAX_COMMENTS": "5",
        }
        with patch.dict(os.environ, env, clear=False):
            config = ReviewConfig.from_env()
            assert config.provider == "groq"
            assert config.api_key == "test-key"
            assert config.github_token == "gh-token"
            assert config.max_comments == 5

    def test_auto_detect_provider(self) -> None:
        env = {
            "ANTHROPIC_API_KEY": "ant-key",
        }
        with patch.dict(os.environ, env, clear=False):
            cleaned = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
            with patch.dict(os.environ, cleaned, clear=True):
                os.environ["ANTHROPIC_API_KEY"] = "ant-key"
                config = ReviewConfig.from_env()
                assert config.provider == "anthropic"

    def test_bad_max_comments_falls_back(self) -> None:
        env = {"INPUT_MAX_COMMENTS": "not-a-number"}
        with patch.dict(os.environ, env, clear=False):
            config = ReviewConfig.from_env()
            assert config.max_comments == 15


class TestReviewConfigYaml:
    def test_from_yaml(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        yml = tmp_path / ".pr-reviewer.yml"
        yml.write_text("max_comments: 5\nreview_style: thorough\n")

        config = ReviewConfig.from_yaml(yml)
        assert config.max_comments == 5
        assert config.review_style == "thorough"

    def test_missing_yaml(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        yml = tmp_path / ".pr-reviewer.yml"
        config = ReviewConfig.from_yaml(yml)
        assert config.max_comments == 15

    def test_bad_yaml_type_coerced(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        yml = tmp_path / ".pr-reviewer.yml"
        yml.write_text('max_comments: "10"\n')

        config = ReviewConfig.from_yaml(yml)
        assert config.max_comments == 10

    def test_unknown_keys_ignored(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        yml = tmp_path / ".pr-reviewer.yml"
        yml.write_text("nonexistent_key: value\nmax_comments: 3\n")

        config = ReviewConfig.from_yaml(yml)
        assert config.max_comments == 3

    def test_invalid_yaml(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        yml = tmp_path / ".pr-reviewer.yml"
        yml.write_text(": invalid: yaml: [")

        config = ReviewConfig.from_yaml(yml)
        assert config.max_comments == 15  # falls back to default
