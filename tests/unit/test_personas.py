"""Tests for review personas."""

from src.review.personas import (
    apply_persona,
    get_persona,
    list_personas,
)


class TestPersonas:
    def test_default_persona_exists(self) -> None:
        p = get_persona("default")
        assert p is not None
        assert p.review_style == "concise"

    def test_security_hawk(self) -> None:
        p = get_persona("security-hawk")
        assert p is not None
        assert "SECURITY-HAWK" in p.system_addendum
        assert p.review_style == "thorough"
        assert p.max_comments == 25

    def test_mentor_persona(self) -> None:
        p = get_persona("mentor")
        assert p is not None
        assert "TEACH" in p.system_addendum
        assert p.review_style == "thorough"

    def test_quick_scan(self) -> None:
        p = get_persona("quick-scan")
        assert p is not None
        assert p.max_comments == 5
        assert p.review_style == "minimal"

    def test_nitpicker(self) -> None:
        p = get_persona("nitpicker")
        assert p is not None
        assert "EVERYTHING" in p.system_addendum

    def test_dora_persona(self) -> None:
        p = get_persona("dora")
        assert p is not None
        assert "DORA" in p.system_addendum

    def test_unknown_returns_none(self) -> None:
        assert get_persona("nonexistent") is None

    def test_case_insensitive_lookup(self) -> None:
        p = get_persona("Security-Hawk")
        assert p is not None
        assert p.name == "security-hawk"

    def test_list_personas_returns_all(self) -> None:
        personas = list_personas()
        assert len(personas) >= 6
        names = {p.name for p in personas}
        assert "security-hawk" in names
        assert "mentor" in names

    def test_apply_persona_modifies_prompt(self) -> None:
        p = get_persona("security-hawk")
        assert p is not None
        original = "You are an expert code reviewer."
        modified, style = apply_persona(p, original, "concise")
        assert "SECURITY-HAWK" in modified
        assert style == "thorough"

    def test_apply_default_no_modification(self) -> None:
        p = get_persona("default")
        assert p is not None
        original = "You are an expert code reviewer."
        modified, style = apply_persona(p, original, "concise")
        assert modified == original
        assert style == "concise"
