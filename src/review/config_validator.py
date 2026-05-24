"""Configuration validator — validates .pr-reviewer.yml files.

Provides helpful error messages for misconfiguration, validates
provider settings, checks API key availability, and suggests fixes.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.config import MODEL_DEFAULTS, VALID_PROVIDERS

logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    """A config validation error."""

    field: str
    message: str
    severity: str = "error"  # error, warning, info
    suggestion: str = ""


@dataclass
class ValidationResult:
    """Result of config validation."""

    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)
    info: list[ValidationError] = field(default_factory=list)


VALID_STYLES = {"concise", "thorough", "minimal"}
VALID_SEVERITIES = {"info", "suggestion", "warning", "critical"}
VALID_PERSONAS = {"default", "security-hawk", "mentor", "nitpicker", "quick-scan", "dora", ""}
VALID_LANGUAGES = {
    "en", "zh", "zh-tw", "ja", "ko", "es", "pt", "de", "fr",
    "ru", "it", "tr", "pl", "nl", "ar",
}

# Known fields in .pr-reviewer.yml
KNOWN_FIELDS = {
    "provider", "model", "api_key", "api_base_url",
    "review_language", "max_files", "max_diff_size",
    "ignore_paths", "ignore_titles",
    "review_style", "severity_threshold", "max_comments",
    "collapse_below", "custom_instructions", "persona",
    "auto_summarize", "check_security", "check_performance",
    "check_correctness", "check_best_practices", "suggest_tests",
    "label_pr", "enable_rag", "cost_limit_usd",
    "max_retries", "retry_base_delay",
    "notifications", "rules",
    # New features
    "auto_approve", "ensemble", "policies", "integrations",
    "check_dependencies", "check_licenses", "check_migrations",
    "check_breaking_changes", "check_performance_patterns",
    "check_dead_code", "check_duplication", "check_metrics",
    "export_format", "batch",
}


def validate_config(config_path: Path | None = None, config_dict: dict | None = None) -> ValidationResult:
    """Validate a .pr-reviewer.yml configuration."""
    result = ValidationResult(valid=True)

    if config_path:
        if not config_path.exists():
            result.errors.append(
                ValidationError(
                    field="file",
                    message=f"Config file not found: {config_path}",
                    suggestion="Create a .pr-reviewer.yml in your repo root.",
                )
            )
            result.valid = False
            return result

        try:
            with open(config_path) as f:
                config_dict = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            result.errors.append(
                ValidationError(
                    field="file",
                    message=f"Invalid YAML syntax: {e}",
                    suggestion="Check YAML syntax at https://yaml-online-parser.appspot.com/",
                )
            )
            result.valid = False
            return result

    if not config_dict:
        config_dict = {}

    # Check for unknown fields
    for key in config_dict:
        if key not in KNOWN_FIELDS:
            result.warnings.append(
                ValidationError(
                    field=key,
                    message=f"Unknown config field: '{key}'",
                    severity="warning",
                    suggestion=f"Did you mean one of: {', '.join(sorted(KNOWN_FIELDS)[:5])}?",
                )
            )

    # Validate provider
    provider = config_dict.get("provider", "openai")
    if provider not in VALID_PROVIDERS:
        result.errors.append(
            ValidationError(
                field="provider",
                message=f"Invalid provider: '{provider}'",
                suggestion=f"Valid providers: {', '.join(sorted(VALID_PROVIDERS))}",
            )
        )
        result.valid = False

    # Check API key availability
    api_key_env = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "groq": "GROQ_API_KEY",
        "google": "GOOGLE_API_KEY",
    }
    if provider in api_key_env:
        env_var = api_key_env[provider]
        if not os.getenv(env_var) and not config_dict.get("api_key"):
            result.warnings.append(
                ValidationError(
                    field="api_key",
                    message=f"No API key found for {provider}",
                    severity="warning",
                    suggestion=f"Set {env_var} environment variable or add api_key to config.",
                )
            )

    # Validate review_style
    style = config_dict.get("review_style")
    if style and style not in VALID_STYLES:
        result.errors.append(
            ValidationError(
                field="review_style",
                message=f"Invalid review_style: '{style}'",
                suggestion=f"Valid styles: {', '.join(VALID_STYLES)}",
            )
        )
        result.valid = False

    # Validate severity_threshold
    sev = config_dict.get("severity_threshold")
    if sev and sev not in VALID_SEVERITIES:
        result.errors.append(
            ValidationError(
                field="severity_threshold",
                message=f"Invalid severity_threshold: '{sev}'",
                suggestion=f"Valid: {', '.join(VALID_SEVERITIES)}",
            )
        )
        result.valid = False

    # Validate persona
    persona = config_dict.get("persona")
    if persona and persona not in VALID_PERSONAS:
        result.warnings.append(
            ValidationError(
                field="persona",
                message=f"Unknown persona: '{persona}'",
                severity="warning",
                suggestion=f"Built-in personas: {', '.join(p for p in VALID_PERSONAS if p)}",
            )
        )

    # Validate language
    lang = config_dict.get("review_language")
    if lang and lang not in VALID_LANGUAGES:
        result.warnings.append(
            ValidationError(
                field="review_language",
                message=f"Unknown language: '{lang}'",
                severity="warning",
                suggestion=f"Supported: {', '.join(sorted(VALID_LANGUAGES))}",
            )
        )

    # Validate numeric ranges
    max_comments = config_dict.get("max_comments")
    if max_comments is not None:
        if not isinstance(max_comments, int) or max_comments < 1 or max_comments > 50:
            result.errors.append(
                ValidationError(
                    field="max_comments",
                    message=f"max_comments must be 1-50, got: {max_comments}",
                )
            )
            result.valid = False

    cost_limit = config_dict.get("cost_limit_usd")
    if cost_limit is not None:
        if not isinstance(cost_limit, (int, float)) or cost_limit < 0:
            result.errors.append(
                ValidationError(
                    field="cost_limit_usd",
                    message=f"cost_limit_usd must be >= 0, got: {cost_limit}",
                )
            )
            result.valid = False

    # Validate ignore_paths is a list
    ignore_paths = config_dict.get("ignore_paths")
    if ignore_paths is not None and not isinstance(ignore_paths, list):
        result.errors.append(
            ValidationError(
                field="ignore_paths",
                message="ignore_paths must be a list of glob patterns",
                suggestion='ignore_paths:\n  - "*.lock"\n  - "vendor/**"',
            )
        )
        result.valid = False

    return result


def format_validation_result(result: ValidationResult) -> str:
    """Format validation result as readable output."""
    parts: list[str] = []

    if result.valid and not result.warnings:
        parts.append("✅ Configuration is valid!")
        return "\n".join(parts)

    if result.errors:
        parts.append(f"❌ {len(result.errors)} error(s):")
        for e in result.errors:
            parts.append(f"  - [{e.field}] {e.message}")
            if e.suggestion:
                parts.append(f"    💡 {e.suggestion}")

    if result.warnings:
        parts.append(f"⚠️ {len(result.warnings)} warning(s):")
        for w in result.warnings:
            parts.append(f"  - [{w.field}] {w.message}")
            if w.suggestion:
                parts.append(f"    💡 {w.suggestion}")

    if result.info:
        for i in result.info:
            parts.append(f"  ℹ️ [{i.field}] {i.message}")

    return "\n".join(parts)
