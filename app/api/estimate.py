"""Cost estimation endpoint — estimate review cost before running."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["estimate"])

# Approximate tokens per character (conservative estimate)
_CHARS_PER_TOKEN = 4
# Prompt overhead (system prompt + formatting)
_PROMPT_OVERHEAD_TOKENS = 1500
# Average output tokens per review
_AVG_OUTPUT_TOKENS = 2000

# Pricing per 1M tokens (input, output)
_PRICING = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-opus-4-20250514": (15.00, 75.00),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "gemini-2.0-flash": (0.10, 0.40),
}

# Agent mode multiplier (multiple LLM calls + tool calls)
_AGENT_MODE_MULTIPLIER = 3.5


class EstimateRequest(BaseModel):
    diff_size_chars: int
    num_files: int
    model: str = "claude-sonnet-4-20250514"
    agent_mode: bool = False


class EstimateResponse(BaseModel):
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float
    model: str
    agent_mode: bool
    breakdown: dict[str, float]


@router.post("/estimate")
async def estimate_review_cost(req: EstimateRequest) -> EstimateResponse:
    """Estimate the cost of reviewing a PR before running it.

    This helps users set appropriate cost limits and choose the right model.
    """
    # Estimate input tokens
    diff_tokens = req.diff_size_chars // _CHARS_PER_TOKEN
    input_tokens = diff_tokens + _PROMPT_OVERHEAD_TOKENS

    # Estimate output tokens based on file count
    output_tokens = min(_AVG_OUTPUT_TOKENS, 500 + req.num_files * 150)

    # Agent mode: multiple LLM calls for tool use loop
    multiplier = _AGENT_MODE_MULTIPLIER if req.agent_mode else 1.0

    total_input = int(input_tokens * multiplier)
    total_output = int(output_tokens * multiplier)

    # Calculate cost
    pricing = _PRICING.get(req.model, (3.00, 15.00))
    cost = (total_input / 1_000_000) * pricing[0] + (total_output / 1_000_000) * pricing[1]

    return EstimateResponse(
        estimated_input_tokens=total_input,
        estimated_output_tokens=total_output,
        estimated_cost_usd=round(cost, 6),
        model=req.model,
        agent_mode=req.agent_mode,
        breakdown={
            "diff_tokens": diff_tokens,
            "prompt_overhead": _PROMPT_OVERHEAD_TOKENS,
            "multiplier": multiplier,
            "input_price_per_1m": pricing[0],
            "output_price_per_1m": pricing[1],
        },
    )
