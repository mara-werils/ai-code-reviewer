from typing import Annotated, Literal
from uuid import UUID

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel
from typing_extensions import TypedDict

from app.services.github_client import FileChange


class ReviewCommentDraft(BaseModel):
    file_path: str
    line_number: int | None = None
    body: str
    severity: Literal["info", "suggestion", "warning", "critical"]
    category: Literal["correctness", "performance", "security", "style", "test_coverage", "design"]


class FinalReview(BaseModel):
    summary: str
    risk_level: Literal["low", "medium", "high"]
    comments: list[ReviewCommentDraft]


class PRClassification(BaseModel):
    category: Literal["bugfix", "feature", "refactor", "docs", "chore", "other"]
    risk_level: Literal["low", "medium", "high"]
    reasoning: str


class ReviewState(TypedDict):
    review_id: UUID
    repository_id: UUID
    pr_number: int
    pr_diff: str
    pr_title: str
    pr_body: str | None
    changed_files: list[FileChange]
    identifiers_in_diff: list[str]
    classification: PRClassification | None
    risk_level: str | None
    messages: Annotated[list[AnyMessage], add_messages]
    tool_calls_count: int
    cost_spent_usd: float
    final_summary: str | None
    final_comments: list[ReviewCommentDraft]
    status: str  # running, done, failed
    installation_id: int
    repo_full_name: str
