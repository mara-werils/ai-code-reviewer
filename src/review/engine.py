"""Core review engine — the brain of the system."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

from src.config import ReviewConfig
from src.github.client import PRFile, PRInfo
from src.providers import LLMProvider, LLMResponse, create_provider
from src.review.analyzer import (
    build_diff_text,
    build_files_summary,
    compute_stats,
    extract_diff_line_map,
    extract_diff_position_map,
    filter_files,
)
from src.review.prompts import REVIEW_PROMPT, SUMMARY_PROMPT, SYSTEM_PROMPT

logger = logging.getLogger(__name__)


@dataclass
class ReviewComment:
    path: str
    line: int
    side: str
    body: str
    severity: str
    position: int = 0  # 1-indexed position in the unified diff


@dataclass
class ReviewResult:
    summary: str
    risk_level: str
    category: str
    comments: list[ReviewComment]
    labels: list[str]
    cost_usd: float
    duration_ms: int
    model: str
    input_tokens: int
    output_tokens: int


class ReviewEngine:
    """Main review engine — takes a PR and produces a review."""

    def __init__(self, config: ReviewConfig) -> None:
        self.config = config
        self.provider: LLMProvider = create_provider(config)

    async def review_pr(
        self,
        pr: PRInfo,
        files: list[PRFile],
        diff: str | None = None,
    ) -> ReviewResult:
        """Run a full review on a PR."""
        start_time = time.monotonic()

        # Filter files
        filtered = filter_files(files, self.config.ignore_paths)
        if not filtered:
            return ReviewResult(
                summary="No reviewable files in this PR (all files match ignore patterns).",
                risk_level="low",
                category="chore",
                comments=[],
                labels=[],
                cost_usd=0,
                duration_ms=0,
                model=self.provider.name,
                input_tokens=0,
                output_tokens=0,
            )

        compute_stats(files, filtered)

        # Limit files if too many
        if len(filtered) > self.config.max_files:
            filtered = filtered[: self.config.max_files]

        # Build diff
        if not diff:
            diff = build_diff_text(filtered, max_size=self.config.max_diff_size)
        else:
            diff = diff[: self.config.max_diff_size]

        files_summary = build_files_summary(filtered)

        # Build valid line numbers and diff positions per file
        valid_lines: dict[str, set[int]] = {}
        position_maps: dict[str, dict[int, int]] = {}
        for f in filtered:
            if f.patch:
                line_map = extract_diff_line_map(f.patch)
                valid_lines[f.filename] = set(line_map.keys())
                position_maps[f.filename] = extract_diff_position_map(f.patch)

        # Build prompts
        custom = ""
        if self.config.custom_instructions:
            custom = f"\n## Additional Instructions\n{self.config.custom_instructions}"

        # Inject learned feedback patterns
        from src.review.feedback import build_learning_prompt, load_feedback

        feedback_store = load_feedback()
        learning_context = build_learning_prompt(feedback_store)
        if learning_context:
            custom += learning_context

        # Apply persona if configured
        from src.review.personas import apply_persona, get_persona

        persona_name = getattr(self.config, "persona", "")
        review_style = self.config.review_style
        base_system = SYSTEM_PROMPT.format(custom_instructions=custom)
        if persona_name:
            persona = get_persona(persona_name)
            if persona:
                base_system, review_style = apply_persona(persona, base_system, review_style)
                if persona.max_comments:
                    self.config.max_comments = persona.max_comments
                logger.info(f"Using persona: {persona.name} ({persona.description})")

        system = base_system
        user = REVIEW_PROMPT.format(
            title=pr.title,
            author=pr.author,
            body=(pr.body or "No description")[:2000],
            files_summary=files_summary,
            diff=diff,
            max_comments=self.config.max_comments,
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        # Call LLM
        logger.info(f"Reviewing PR #{pr.number} with {self.provider.name}")
        response = await self.provider.complete(
            messages=messages,
            temperature=0.1,
            max_tokens=4096,
            json_mode=True,
        )

        # Parse response
        result = self._parse_response(response, valid_lines, position_maps)

        duration_ms = int((time.monotonic() - start_time) * 1000)
        result.duration_ms = duration_ms
        result.cost_usd = response.cost_usd
        result.model = response.model
        result.input_tokens = response.input_tokens
        result.output_tokens = response.output_tokens

        logger.info(
            f"Review complete: {len(result.comments)} comments, "
            f"risk={result.risk_level}, cost=${result.cost_usd:.4f}, "
            f"duration={duration_ms}ms"
        )

        return result

    def _parse_response(
        self,
        response: LLMResponse,
        valid_lines: dict[str, set[int]],
        position_maps: dict[str, dict[int, int]] | None = None,
    ) -> ReviewResult:
        """Parse LLM response into structured review."""
        try:
            # Try to extract JSON from response
            text = response.content.strip()
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse review response as JSON: {e}")
            return ReviewResult(
                summary=response.content[:500],
                risk_level="medium",
                category="other",
                comments=[],
                labels=[],
                cost_usd=0,
                duration_ms=0,
                model="",
                input_tokens=0,
                output_tokens=0,
            )

        comments = []
        for c in data.get("comments", []):
            path = c.get("path", "")
            line = c.get("line", 0)
            body = c.get("body", "")

            if not path or not body:
                continue

            # Try to match path if LLM returned a partial/wrong path
            if path not in valid_lines:
                matched = False
                for valid_path in valid_lines:
                    if valid_path.endswith(path) or path.endswith(valid_path):
                        path = valid_path
                        matched = True
                        break
                if not matched:
                    # Skip comments for files not in the diff
                    logger.debug(f"Skipping comment for unknown path: {path}")
                    continue

            # Validate line exists in diff
            file_lines = valid_lines.get(path, set())
            if line not in file_lines:
                if file_lines:
                    line = min(file_lines, key=lambda x: abs(x - line))
                else:
                    continue

            # Look up diff position for this line
            position = 0
            if position_maps and path in position_maps:
                position = position_maps[path].get(line, 0)

            comments.append(
                ReviewComment(
                    path=path,
                    line=line,
                    side=c.get("side", "RIGHT"),
                    body=body,
                    severity=c.get("severity", "info"),
                    position=position,
                )
            )

        return ReviewResult(
            summary=data.get("summary", ""),
            risk_level=data.get("risk_level", "medium"),
            category=data.get("category", "other"),
            comments=comments,
            labels=data.get("labels", []) if self.config.label_pr else [],
            cost_usd=0,
            duration_ms=0,
            model="",
            input_tokens=0,
            output_tokens=0,
        )

    async def generate_summary(self, pr: PRInfo, files: list[PRFile]) -> str:
        """Generate a PR summary."""
        filtered = filter_files(files, self.config.ignore_paths)
        diff = build_diff_text(filtered, max_size=15000)
        files_summary = build_files_summary(filtered)

        prompt = SUMMARY_PROMPT.format(
            title=pr.title,
            files_summary=files_summary,
            diff=diff,
        )

        response = await self.provider.complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1024,
        )
        return response.content
