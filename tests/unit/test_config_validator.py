"""Tests for config validator."""

from src.review.config_validator import validate_config, format_validation_result


class TestConfigValidator:
    def test_valid_config(self):
        config = {"provider": "openai", "review_style": "concise", "max_comments": 10}
        result = validate_config(config_dict=config)
        assert result.valid

    def test_invalid_provider(self):
        config = {"provider": "invalid_provider"}
        result = validate_config(config_dict=config)
        assert not result.valid
        assert any(e.field == "provider" for e in result.errors)

    def test_invalid_style(self):
        config = {"review_style": "ultra_detailed"}
        result = validate_config(config_dict=config)
        assert not result.valid

    def test_invalid_max_comments(self):
        config = {"max_comments": 100}
        result = validate_config(config_dict=config)
        assert not result.valid

    def test_unknown_field_warning(self):
        config = {"unknown_field_xyz": "value"}
        result = validate_config(config_dict=config)
        assert len(result.warnings) > 0

    def test_empty_config_valid(self):
        result = validate_config(config_dict={})
        assert result.valid

    def test_format_valid(self):
        result = validate_config(config_dict={})
        formatted = format_validation_result(result)
        assert "valid" in formatted.lower()

    def test_format_errors(self):
        result = validate_config(config_dict={"provider": "bad"})
        formatted = format_validation_result(result)
        assert "error" in formatted.lower()
