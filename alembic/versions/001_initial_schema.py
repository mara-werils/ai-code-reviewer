"""Initial schema with all tables

Revision ID: 001
Revises: None
Create Date: 2026-05-06

"""
from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # repositories
    op.create_table(
        "repositories",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("github_full_name", sa.Text, nullable=False, unique=True),
        sa.Column("default_branch", sa.Text, nullable=False, server_default="main"),
        sa.Column("installation_id", sa.BigInteger, nullable=False),
        sa.Column("last_indexed_sha", sa.Text, nullable=True),
        sa.Column("indexing_status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("cost_budget_usd_monthly", sa.Numeric(10, 4), nullable=False,
                  server_default="50.00"),
        sa.Column("cost_spent_usd_current_month", sa.Numeric(10, 4), nullable=False,
                  server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    # chunks
    op.create_table(
        "chunks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("repository_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("chunk_type", sa.Text, nullable=False),
        sa.Column("identifier", sa.Text, nullable=True),
        sa.Column("identifier_coalesce", sa.Text, nullable=False, server_default=""),
        sa.Column("language", sa.Text, nullable=False),
        sa.Column("start_line", sa.Integer, nullable=False),
        sa.Column("end_line", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("metadata", sa.dialects.postgresql.JSONB, nullable=False,
                  server_default="{}"),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    op.create_index("idx_chunks_repo", "chunks", ["repository_id"])
    op.create_index("idx_chunks_file_path", "chunks", ["repository_id", "file_path"])
    op.create_index(
        "idx_chunks_identifier_trgm", "chunks", ["identifier"],
        postgresql_using="gin",
        postgresql_ops={"identifier": "gin_trgm_ops"},
    )
    op.create_index(
        "idx_chunks_embedding", "chunks", ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_unique_constraint(
        "uq_chunks_location", "chunks",
        ["repository_id", "file_path", "identifier_coalesce", "start_line"],
    )

    # reviews
    op.create_table(
        "reviews",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("repository_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("pr_number", sa.Integer, nullable=False),
        sa.Column("pr_head_sha", sa.Text, nullable=False),
        sa.Column("pr_title", sa.Text, nullable=True),
        sa.Column("pr_classification", sa.Text, nullable=True),
        sa.Column("risk_level", sa.Text, nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("total_input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_cost_usd", sa.Numeric(10, 6), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_unique_constraint(
        "uq_reviews_pr", "reviews",
        ["repository_id", "pr_number", "pr_head_sha"],
    )

    # review_comments
    op.create_table(
        "review_comments",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("review_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("line_number", sa.Integer, nullable=True),
        sa.Column("comment_body", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=True),
        sa.Column("github_comment_id", sa.BigInteger, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    # llm_calls
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("review_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("reviews.id", ondelete="CASCADE"), nullable=True),
        sa.Column("purpose", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=True),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    # agent_tool_calls
    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("review_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_name", sa.Text, nullable=False),
        sa.Column("tool_input", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column("tool_output_summary", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    # feedback
    op.create_table(
        "feedback",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("review_comment_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("review_comments.id", ondelete="CASCADE"), nullable=True),
        sa.Column("feedback_type", sa.Text, nullable=False),
        sa.Column("reply_text", sa.Text, nullable=True),
        sa.Column("github_user_login", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_table("agent_tool_calls")
    op.drop_table("llm_calls")
    op.drop_table("review_comments")
    op.drop_table("reviews")
    op.drop_table("chunks")
    op.drop_table("repositories")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS vector")
