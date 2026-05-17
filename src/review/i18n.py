"""Internationalization — review language support.

Injects language instructions into the system prompt so LLM
outputs review comments in the team's preferred language.

Supports 15 languages covering the major developer populations.
"""

from __future__ import annotations

SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "zh": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)",
    "ja": "Japanese",
    "ko": "Korean",
    "es": "Spanish",
    "pt": "Portuguese (Brazilian)",
    "de": "German",
    "fr": "French",
    "ru": "Russian",
    "it": "Italian",
    "tr": "Turkish",
    "pl": "Polish",
    "nl": "Dutch",
    "ar": "Arabic",
    "hi": "Hindi",
    "vi": "Vietnamese",
    "th": "Thai",
    "uk": "Ukrainian",
    "cs": "Czech",
    "sv": "Swedish",
}

# Language-specific prompt addendum
_LANGUAGE_PROMPT = """
## Language Requirement

IMPORTANT: Write ALL review comments, summaries, and suggestions in **{language_name}**.
- The JSON keys (path, line, severity, etc.) stay in English
- The "body" and "summary" values MUST be in {language_name}
- Code suggestions inside ```suggestion blocks stay in the original code language
- Technical terms (variable names, function names, library names) stay as-is
"""


def get_language_name(code: str) -> str:
    """Get full language name from ISO code."""
    return SUPPORTED_LANGUAGES.get(code.lower().strip(), "English")


def get_language_prompt(language_code: str) -> str:
    """Get the language instruction to inject into the system prompt.

    Returns empty string for English (default, no injection needed).
    """
    code = language_code.lower().strip()
    if code in ("en", ""):
        return ""

    name = SUPPORTED_LANGUAGES.get(code)
    if not name:
        return ""

    return _LANGUAGE_PROMPT.format(language_name=name)


def list_languages() -> list[tuple[str, str]]:
    """Return list of (code, name) tuples."""
    return list(SUPPORTED_LANGUAGES.items())
