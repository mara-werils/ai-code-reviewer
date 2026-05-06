from decimal import Decimal

from app.core.cost_tracker import calculate_cost


class TestCostTracker:
    def test_sonnet_cost(self) -> None:
        cost = calculate_cost("claude-sonnet-4-20250514", 1000, 500)
        # input: 1000/1M * 3.00 = 0.003
        # output: 500/1M * 15.00 = 0.0075
        assert cost == Decimal("0.003") + Decimal("0.0075")

    def test_haiku_cost(self) -> None:
        cost = calculate_cost("claude-haiku-4-5-20251001", 10000, 1000)
        # input: 10000/1M * 0.80 = 0.008
        # output: 1000/1M * 4.00 = 0.004
        assert cost == Decimal("0.008") + Decimal("0.004")

    def test_embedding_cost(self) -> None:
        cost = calculate_cost("text-embedding-3-small", 100000, 0)
        # input: 100000/1M * 0.02 = 0.002
        assert cost == Decimal("0.002")

    def test_unknown_model_falls_back(self) -> None:
        cost = calculate_cost("unknown-model", 1000, 500)
        # Falls back to sonnet pricing
        expected = calculate_cost("claude-sonnet-4-20250514", 1000, 500)
        assert cost == expected
