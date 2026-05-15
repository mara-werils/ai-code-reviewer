"""Tests for i18n language support."""

from src.review.i18n import get_language_name, get_language_prompt, list_languages


class TestI18n:
    def test_english_returns_english(self) -> None:
        assert get_language_name("en") == "English"

    def test_chinese_simplified(self) -> None:
        assert get_language_name("zh") == "Chinese (Simplified)"

    def test_chinese_traditional(self) -> None:
        assert get_language_name("zh-tw") == "Chinese (Traditional)"

    def test_unknown_returns_english(self) -> None:
        assert get_language_name("xx") == "English"

    def test_english_prompt_is_empty(self) -> None:
        assert get_language_prompt("en") == ""

    def test_empty_code_prompt_is_empty(self) -> None:
        assert get_language_prompt("") == ""

    def test_japanese_prompt_contains_language(self) -> None:
        prompt = get_language_prompt("ja")
        assert "Japanese" in prompt
        assert "IMPORTANT" in prompt

    def test_arabic_prompt(self) -> None:
        prompt = get_language_prompt("ar")
        assert "Arabic" in prompt

    def test_case_insensitive(self) -> None:
        assert get_language_name("EN") == "English"
        assert get_language_prompt("JA") != ""

    def test_list_languages_has_15(self) -> None:
        langs = list_languages()
        assert len(langs) == 15
        codes = [code for code, _ in langs]
        assert "en" in codes
        assert "ar" in codes
        assert "zh-tw" in codes
