import json
import re
import time
from typing import Any

import anthropic
import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.cost_tracker import calculate_cost
from app.db.models import LLMCall, Review, ReviewComment
from app.prompts.final_review_v1 import FINAL_REVIEW_PROMPT
from app.prompts.final_review_v1 import VERSION as FINAL_VERSION
from app.prompts.reviewer_system_v1 import REVIEWER_HUMAN_PROMPT, REVIEWER_SYSTEM_PROMPT
from app.prompts.reviewer_system_v1 import VERSION as REVIEWER_VERSION
from app.services.github_client import GitHubClient
from app.services.retrieval_service import RetrievalService
from app.services.reviewer.classifier import classify_pr
from app.services.reviewer.state import FinalReview, ReviewState
from app.services.reviewer.tools import TOOL_DEFINITIONS, ToolRegistry

logger = structlog.get_logger()

AGENT_MODEL = "claude-sonnet-4-20250514"


def _parse_diff_identifiers(diff: str) -> list[str]:
    """Extract added/removed identifiers from diff using regex."""
    identifiers: set[str] = set()
    # Match function/class definitions in added lines
    for line in diff.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            # Python: def/class
            match = re.match(r"\+\s*(?:async\s+)?(?:def|class)\s+(\w+)", line)
            if match:
                identifiers.add(match.group(1))
            # JS/TS: function/const/let/var
            match = re.match(r"\+\s*(?:export\s+)?(?:function|const|let|var)\s+(\w+)", line)
            if match:
                identifiers.add(match.group(1))
    return list(identifiers)


def _parse_diff_by_file(diff: str) -> dict[str, str]:
    """Split a unified diff into per-file diffs."""
    files: dict[str, str] = {}
    current_file = None
    current_lines: list[str] = []

    for line in diff.split("\n"):
        if line.startswith("diff --git"):
            if current_file and current_lines:
                files[current_file] = "\n".join(current_lines)
            current_lines = [line]
            match = re.search(r"b/(.+)$", line)
            current_file = match.group(1) if match else None
        else:
            current_lines.append(line)

    if current_file and current_lines:
        files[current_file] = "\n".join(current_lines)

    return files


def build_review_graph(session: AsyncSession) -> StateGraph:  # type: ignore[type-arg]
    settings = get_settings()

    async def extract_diff_context(state: ReviewState) -> dict[str, Any]:
        diff = state["pr_diff"]
        identifiers = _parse_diff_identifiers(diff)
        return {
            "identifiers_in_diff": identifiers,
            "status": "running",
        }

    async def classify_pr_node(state: ReviewState) -> dict[str, Any]:
        classification = await classify_pr(
            pr_title=state["pr_title"],
            pr_body=state.get("pr_body"),
            changed_files=state["changed_files"],
            diff=state["pr_diff"],
            session=session,
            review_id=state["review_id"],
        )
        return {
            "classification": classification,
            "risk_level": classification.risk_level,
        }

    async def prepare_initial_context(state: ReviewState) -> dict[str, Any]:
        retrieval = RetrievalService(session)

        # Build query from PR title + identifiers
        query_parts = [state["pr_title"]]
        pr_body = state.get("pr_body")
        if pr_body:
            query_parts.append(pr_body[:500])

        query = " ".join(query_parts)
        file_paths = [f.filename for f in state["changed_files"]]

        retrieved = await retrieval.hybrid_search(
            repo_id=state["repository_id"],
            query=query,
            identifiers_in_diff=state.get("identifiers_in_diff", []),
            file_paths_in_diff=file_paths,
            top_k=5,
        )

        # Format context
        context_parts = []
        for chunk in retrieved:
            context_parts.append(
                f"**{chunk.file_path}** ({chunk.chunk_type}: {chunk.identifier or 'N/A'}, "
                f"lines {chunk.start_line}-{chunk.end_line}):\n"
                f"```{chunk.language}\n{chunk.content[:2000]}\n```"
            )
        retrieved_context = (
            "\n\n".join(context_parts) if context_parts else "No relevant context found."
        )

        classification = state.get("classification")
        cat = classification.category if classification else "unknown"
        risk = classification.risk_level if classification else "unknown"

        system_prompt = REVIEWER_SYSTEM_PROMPT.format(
            repo_name=state["repo_full_name"],
            pr_number=state["pr_number"],
            pr_title=state["pr_title"],
            classification=cat,
            risk_level=risk,
            changed_files_list=", ".join(f.filename for f in state["changed_files"]),
            max_tool_iterations=settings.max_tool_iterations,
            retrieved_context=retrieved_context,
            diff=state["pr_diff"][:15000],  # Truncate diff
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=REVIEWER_HUMAN_PROMPT),
        ]

        return {"messages": messages}

    async def agent_step(state: ReviewState) -> dict[str, Any]:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

        # Convert LangChain messages to Anthropic format
        anthropic_messages = []
        system_content = ""

        for msg in state["messages"]:
            if isinstance(msg, SystemMessage):
                system_content = msg.content  # type: ignore[assignment]
            elif isinstance(msg, HumanMessage):
                anthropic_messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                content_blocks: list[Any] = []
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        content_blocks.append(
                            {
                                "type": "tool_use",
                                "id": tc["id"],
                                "name": tc["name"],
                                "input": tc["args"],
                            }
                        )
                anthropic_messages.append({"role": "assistant", "content": content_blocks})
            elif isinstance(msg, ToolMessage):
                anthropic_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.tool_call_id,
                                "content": msg.content,
                            }
                        ],
                    }
                )

        start = time.monotonic()
        try:
            response = await client.messages.create(
                model=AGENT_MODEL,
                max_tokens=4096,
                system=system_content,
                messages=anthropic_messages,  # type: ignore[arg-type]
                tools=TOOL_DEFINITIONS,  # type: ignore[arg-type]
            )

            latency_ms = int((time.monotonic() - start) * 1000)
            cost = calculate_cost(
                AGENT_MODEL,
                response.usage.input_tokens,
                response.usage.output_tokens,
            )

            llm_call = LLMCall(
                review_id=state["review_id"],
                purpose="tool_call",
                model=AGENT_MODEL,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cost_usd=float(cost),
                latency_ms=latency_ms,
                prompt_version=REVIEWER_VERSION,
                success=True,
            )
            session.add(llm_call)

            # Parse response into LangChain message
            text_content = ""
            tool_calls = []
            for block in response.content:
                if block.type == "text":
                    text_content = block.text
                elif block.type == "tool_use":
                    tool_calls.append(
                        {
                            "id": block.id,
                            "name": block.name,
                            "args": block.input,
                        }
                    )

            ai_message = AIMessage(content=text_content, tool_calls=tool_calls)

            return {
                "messages": [ai_message],
                "tool_calls_count": state.get("tool_calls_count", 0) + len(tool_calls),
                "cost_spent_usd": state.get("cost_spent_usd", 0.0) + float(cost),
            }

        except Exception as e:
            logger.error("agent_step_failed", error=str(e))
            return {
                "messages": [AIMessage(content=f"Error in agent step: {e}")],
                "status": "failed",
            }

    async def execute_tools(state: ReviewState) -> dict[str, Any]:
        last_message = state["messages"][-1]
        if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
            return {}

        diff_by_file = _parse_diff_by_file(state["pr_diff"])
        registry = ToolRegistry(
            session=session,
            repo_id=state["repository_id"],
            review_id=state["review_id"],
            diff_by_file=diff_by_file,
        )

        tool_messages = []
        for tc in last_message.tool_calls:
            result = await registry.dispatch(tc["name"], tc["args"])
            tool_messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))

        return {"messages": tool_messages}

    async def produce_final_review(state: ReviewState) -> dict[str, Any]:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

        # Collect all text from agent's messages
        agent_analysis = []
        for msg in state["messages"]:
            if isinstance(msg, AIMessage) and msg.content:
                agent_analysis.append(str(msg.content))

        analysis_text = "\n\n".join(agent_analysis[-3:])  # Last 3 messages

        prompt = (
            f"You've analyzed this PR. Here's your analysis:\n\n{analysis_text}\n\n"
            + FINAL_REVIEW_PROMPT
        )

        start = time.monotonic()
        response = await client.messages.create(
            model=AGENT_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        cost = calculate_cost(
            AGENT_MODEL,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )

        llm_call = LLMCall(
            review_id=state["review_id"],
            purpose="final_review",
            model=AGENT_MODEL,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=float(cost),
            latency_ms=latency_ms,
            prompt_version=FINAL_VERSION,
            success=True,
        )
        session.add(llm_call)

        text = response.content[0].text  # type: ignore[union-attr]

        try:
            # Extract JSON
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(text)
            review = FinalReview(**data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("final_review_parse_failed", error=str(e))
            review = FinalReview(
                summary=text[:500],
                risk_level=state.get("risk_level", "medium"),
                comments=[],
            )

        return {
            "final_summary": review.summary,
            "final_comments": review.comments,
            "risk_level": review.risk_level,
            "cost_spent_usd": state.get("cost_spent_usd", 0.0) + float(cost),
        }

    async def cost_check_node(state: ReviewState) -> dict[str, Any]:
        if state.get("cost_spent_usd", 0.0) > settings.review_cost_limit_usd:
            logger.warning(
                "cost_limit_approaching",
                cost=state["cost_spent_usd"],
                limit=settings.review_cost_limit_usd,
            )
        return {}

    async def post_review_node(state: ReviewState) -> dict[str, Any]:
        github = GitHubClient()
        installation_id = state["installation_id"]

        try:
            # Format review body
            classification = state.get("classification")
            cat = classification.category if classification else "unknown"

            body_parts = [
                "## AI Review Summary",
                "",
                f"**Classification:** {cat} | **Risk:** {state.get('risk_level', 'unknown')}",
                "",
                state.get("final_summary", "Review completed."),
                "",
            ]

            comments = state.get("final_comments", [])
            if comments:
                body_parts.append(f"**{len(comments)} comment(s) below.**")
            else:
                body_parts.append("No issues found. LGTM!")

            body_parts.extend(
                [
                    "",
                    "---",
                    f"*Cost: ${state.get('cost_spent_usd', 0):.4f} | "
                    f"Tool calls: {state.get('tool_calls_count', 0)}*",
                ]
            )

            body = "\n".join(p for p in body_parts if p is not None)

            # Format inline comments
            gh_comments = []
            for c in comments:
                if c.line_number:
                    gh_comments.append(
                        {
                            "path": c.file_path,
                            "line": c.line_number,
                            "body": f"**[{c.severity.upper()}]** ({c.category})\n\n{c.body}",
                        }
                    )

            await github.post_review(
                repo=state["repo_full_name"],
                pr_number=state["pr_number"],
                body=body,
                comments=gh_comments,
                installation_id=installation_id,
            )

            # Save to DB
            await session.execute(
                update(Review)
                .where(Review.id == state["review_id"])
                .values(
                    status="posted",
                    summary=state.get("final_summary"),
                    pr_classification=cat,
                    risk_level=state.get("risk_level"),
                    total_cost_usd=state.get("cost_spent_usd", 0),
                )
            )

            for c in comments:
                comment = ReviewComment(
                    review_id=state["review_id"],
                    file_path=c.file_path,
                    line_number=c.line_number,
                    comment_body=c.body,
                    severity=c.severity,
                    category=c.category,
                )
                session.add(comment)

            logger.info("review_posted", pr=state["pr_number"], comments=len(comments))
            return {"status": "done"}

        except Exception as e:
            logger.error("post_review_failed", error=str(e))
            await session.execute(
                update(Review)
                .where(Review.id == state["review_id"])
                .values(status="failed", error_message=str(e)[:500])
            )
            return {"status": "failed"}
        finally:
            await github.close()

    def should_continue(state: ReviewState) -> str:
        """Decide whether to continue tool calls or produce final review."""
        last_message = state["messages"][-1]
        tool_count = state.get("tool_calls_count", 0)
        cost = state.get("cost_spent_usd", 0.0)

        # Check limits
        if tool_count >= settings.max_tool_iterations:
            logger.info("max_tool_iterations_reached", count=tool_count)
            return "produce_final_review"

        if cost >= settings.review_cost_limit_usd:
            logger.info("cost_limit_reached", cost=cost)
            return "produce_final_review"

        # Check if agent wants to use tools
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "execute_tools"

        return "produce_final_review"

    # Build graph
    graph = StateGraph(ReviewState)

    graph.add_node("extract_diff_context", extract_diff_context)
    graph.add_node("classify_pr", classify_pr_node)
    graph.add_node("prepare_initial_context", prepare_initial_context)
    graph.add_node("agent_step", agent_step)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("produce_final_review", produce_final_review)
    graph.add_node("cost_check", cost_check_node)
    graph.add_node("post_review", post_review_node)

    graph.set_entry_point("extract_diff_context")
    graph.add_edge("extract_diff_context", "classify_pr")
    graph.add_edge("classify_pr", "prepare_initial_context")
    graph.add_edge("prepare_initial_context", "agent_step")

    graph.add_conditional_edges(
        "agent_step",
        should_continue,
        {
            "execute_tools": "execute_tools",
            "produce_final_review": "produce_final_review",
        },
    )
    graph.add_edge("execute_tools", "agent_step")
    graph.add_edge("produce_final_review", "cost_check")
    graph.add_edge("cost_check", "post_review")
    graph.add_edge("post_review", END)

    return graph
