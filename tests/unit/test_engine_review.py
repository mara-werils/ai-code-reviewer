"""Tests for the review engine — response parsing and review flow."""

from __future__ import annotations

from src.providers.base import LLMResponse
from src.review.engine import ReviewEngine


class TestResponseParsing:
    """Test LLM response parsing into structured review."""

    def setup_method(self):
        # Create a minimal config
        from src.config import ReviewConfig
        self.config = ReviewConfig(provider="openai", api_key="test", model="gpt-4o")
        self.engine = ReviewEngine(self.config)

    def test_valid_json_response(self):
        response = LLMResponse(
            content='{"summary":"Good PR","risk_level":"low","category":"feature","comments":[{"path":"src/main.py","line":10,"body":"Nice code","severity":"info","side":"RIGHT"}],"labels":[]}',
            input_tokens=100,
            output_tokens=50,
            model="gpt-4o",
        )
        valid_lines = {"src/main.py": {10, 11, 12}}
        result = self.engine._parse_response(response, valid_lines)

        assert result.summary == "Good PR"
        assert result.risk_level == "low"
        assert result.category == "feature"
        assert len(result.comments) == 1
        assert result.comments[0].path == "src/main.py"
        assert result.comments[0].line == 10

    def test_json_wrapped_in_text(self):
        response = LLMResponse(
            content='Here is my review:\n{"summary":"Looks good","risk_level":"low","category":"chore","comments":[],"labels":[]}\nEnd.',
        )
        valid_lines = {}
        result = self.engine._parse_response(response, valid_lines)
        assert result.summary == "Looks good"

    def test_invalid_json_fallback(self):
        response = LLMResponse(content="This is not JSON at all")
        result = self.engine._parse_response(response, {})
        assert result.summary == "This is not JSON at all"
        assert result.risk_level == "medium"
        assert len(result.comments) == 0

    def test_line_correction(self):
        """If LLM outputs a line not in diff, snap to nearest valid line."""
        response = LLMResponse(
            content='{"summary":"test","risk_level":"low","category":"bugfix","comments":[{"path":"a.py","line":15,"body":"bug","severity":"warning","side":"RIGHT"}],"labels":[]}',
        )
        # Line 15 not in valid lines, nearest is 12
        valid_lines = {"a.py": {10, 12, 20}}
        result = self.engine._parse_response(response, valid_lines)
        assert result.comments[0].line == 12  # Snapped to nearest

    def test_unknown_path_skipped(self):
        """Comments for files not in the diff should be skipped."""
        response = LLMResponse(
            content='{"summary":"test","risk_level":"low","category":"bugfix","comments":[{"path":"nonexistent.py","line":1,"body":"bug","severity":"warning"}],"labels":[]}',
        )
        valid_lines = {"a.py": {1, 2, 3}}
        result = self.engine._parse_response(response, valid_lines)
        assert len(result.comments) == 0

    def test_partial_path_matching(self):
        """LLM might return partial paths — should match against valid paths."""
        response = LLMResponse(
            content='{"summary":"test","risk_level":"low","category":"bugfix","comments":[{"path":"main.py","line":5,"body":"issue","severity":"warning"}],"labels":[]}',
        )
        valid_lines = {"src/app/main.py": {5, 6, 7}}
        result = self.engine._parse_response(response, valid_lines)
        assert len(result.comments) == 1
        assert result.comments[0].path == "src/app/main.py"

    def test_position_map_applied(self):
        """Diff position should be assigned from position map."""
        response = LLMResponse(
            content='{"summary":"test","risk_level":"low","category":"bugfix","comments":[{"path":"a.py","line":10,"body":"fix","severity":"critical"}],"labels":[]}',
        )
        valid_lines = {"a.py": {10}}
        position_maps = {"a.py": {10: 42}}
        result = self.engine._parse_response(response, valid_lines, position_maps)
        assert result.comments[0].position == 42

    def test_empty_comments_body_skipped(self):
        response = LLMResponse(
            content='{"summary":"test","risk_level":"low","category":"bugfix","comments":[{"path":"a.py","line":1,"body":"","severity":"info"}],"labels":[]}',
        )
        valid_lines = {"a.py": {1}}
        result = self.engine._parse_response(response, valid_lines)
        assert len(result.comments) == 0

    def test_labels_disabled(self):
        self.config.label_pr = False
        response = LLMResponse(
            content='{"summary":"test","risk_level":"low","category":"bugfix","comments":[],"labels":["bug","needs-review"]}',
        )
        result = self.engine._parse_response(response, {})
        assert result.labels == []

    def test_labels_enabled(self):
        self.config.label_pr = True
        response = LLMResponse(
            content='{"summary":"test","risk_level":"low","category":"bugfix","comments":[],"labels":["bug","needs-review"]}',
        )
        result = self.engine._parse_response(response, {})
        assert result.labels == ["bug", "needs-review"]
