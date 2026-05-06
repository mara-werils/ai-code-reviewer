from decimal import Decimal

import structlog

logger = structlog.get_logger()

# Pricing per 1M tokens (as of 2025)
MODEL_PRICING: dict[str, dict[str, Decimal]] = {
    "claude-sonnet-4-20250514": {"input": Decimal("3.00"), "output": Decimal("15.00")},
    "claude-haiku-4-5-20251001": {"input": Decimal("0.80"), "output": Decimal("4.00")},
    "text-embedding-3-small": {"input": Decimal("0.02"), "output": Decimal("0")},
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        logger.warning("unknown_model_pricing", model=model)
        # Fallback to sonnet pricing
        pricing = MODEL_PRICING["claude-sonnet-4-20250514"]

    input_cost = (Decimal(input_tokens) / Decimal("1000000")) * pricing["input"]
    output_cost = (Decimal(output_tokens) / Decimal("1000000")) * pricing["output"]
    return input_cost + output_cost
