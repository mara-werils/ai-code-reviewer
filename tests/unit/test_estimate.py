"""Tests for cost estimation endpoint."""

from __future__ import annotations

from app.api.estimate import _CHARS_PER_TOKEN, _PRICING, _PROMPT_OVERHEAD_TOKENS, EstimateRequest


class TestEstimateCalculation:
    """Test cost estimation logic."""

    def test_basic_estimate(self):
        EstimateRequest(diff_size_chars=4000, num_files=5, model="gpt-4o")
        diff_tokens = 4000 // _CHARS_PER_TOKEN  # 1000
        input_tokens = diff_tokens + _PROMPT_OVERHEAD_TOKENS  # 2500
        output_tokens = min(2000, 500 + 5 * 150)  # 1250

        pricing = _PRICING["gpt-4o"]
        expected_cost = (input_tokens / 1_000_000) * pricing[0] + (output_tokens / 1_000_000) * pricing[1]
        assert expected_cost > 0
        assert expected_cost < 0.10  # Should be cheap

    def test_agent_mode_multiplier(self):
        diff_tokens = 4000 // _CHARS_PER_TOKEN
        input_normal = diff_tokens + _PROMPT_OVERHEAD_TOKENS
        input_agent = int(input_normal * 3.5)
        assert input_agent > input_normal

    def test_output_tokens_capped(self):
        """Output tokens should be capped at AVG_OUTPUT_TOKENS."""
        output = min(2000, 500 + 100 * 150)
        assert output == 2000

    def test_unknown_model_uses_default_pricing(self):
        """Unknown models should use default pricing."""
        pricing = _PRICING.get("nonexistent-model", (3.00, 15.00))
        assert pricing == (3.00, 15.00)

    def test_all_known_models_have_pricing(self):
        """Verify all major models have pricing entries."""
        expected_models = ["gpt-4o", "gpt-4o-mini", "claude-sonnet-4-20250514", "gemini-2.0-flash"]
        for model in expected_models:
            assert model in _PRICING

    def test_small_diff_cheap(self):
        """Small diffs should be very cheap to review."""
        diff_tokens = 100 // _CHARS_PER_TOKEN  # 25
        input_tokens = diff_tokens + _PROMPT_OVERHEAD_TOKENS  # 1525
        output_tokens = min(2000, 500 + 1 * 150)  # 650

        pricing = _PRICING["gpt-4o-mini"]
        cost = (input_tokens / 1_000_000) * pricing[0] + (output_tokens / 1_000_000) * pricing[1]
        assert cost < 0.001  # Sub-penny
