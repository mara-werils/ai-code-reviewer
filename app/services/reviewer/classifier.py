import json
import re
import time

import anthropic
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.cost_tracker import calculate_cost
from app.db.models import LLMCall
from app.prompts.classification_v1 import CLASSIFICATION_PROMPT, VERSION
from app.services.github_client import FileChange
from app.services.reviewer.state import PRClassification

logger = structlog.get_logger()

CLASSIFICATION_MODEL = "claude-haiku-4-5-20251001"


async def classify_pr(
    pr_title: str,
    pr_body: str | None,
    changed_files: list[FileChange],
    diff: str,
    session: AsyncSession,
    review_id: object,
) -> PRClassification:
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    files_desc = "\n".join(
        f"- {f.filename} ({f.status}, +{f.additions}/-{f.deletions})" for f in changed_files
    )

    prompt = CLASSIFICATION_PROMPT.format(
        pr_title=pr_title,
        pr_body=pr_body or "No description provided",
        changed_files=files_desc,
        diff_summary=diff[:3000],
    )

    start = time.monotonic()
    try:
        response = await client.messages.create(
            model=CLASSIFICATION_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        text = response.content[0].text  # type: ignore[union-attr]

        # Extract JSON from response
        json_match = re.search(r"\{[^}]+\}", text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
        else:
            data = json.loads(text)

        classification = PRClassification(**data)

        # Log LLM call
        cost = calculate_cost(
            CLASSIFICATION_MODEL,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        llm_call = LLMCall(
            review_id=review_id,  # type: ignore[arg-type]
            purpose="classification",
            model=CLASSIFICATION_MODEL,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=float(cost),
            latency_ms=latency_ms,
            prompt_version=VERSION,
            success=True,
        )
        session.add(llm_call)

        logger.info(
            "pr_classified",
            category=classification.category,
            risk=classification.risk_level,
            latency_ms=latency_ms,
        )
        return classification

    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        llm_call = LLMCall(
            review_id=review_id,  # type: ignore[arg-type]
            purpose="classification",
            model=CLASSIFICATION_MODEL,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0,
            latency_ms=latency_ms,
            prompt_version=VERSION,
            success=False,
            error_message=str(e),
        )
        session.add(llm_call)
        logger.error("classification_failed", error=str(e))

        # Default classification on failure
        return PRClassification(
            category="other",
            risk_level="medium",
            reasoning=f"Classification failed: {e}",
        )
