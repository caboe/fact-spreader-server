"""add semantic claim cache

Revision ID: 7c1f2a9b4e66
Revises: 44dea1d3cccb
Create Date: 2026-11-17 11:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "7c1f2a9b4e66"
down_revision: str | None = "44dea1d3cccb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "claim_cache",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("result_id", sa.String(length=64), nullable=False),
        sa.Column("corpus_version", sa.String(length=80), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["result_id"],
            ["results.id"],
            name=op.f("fk_claim_cache_result_id_results"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim_cache")),
    )
    op.create_index(op.f("ix_claim_cache_result_id"), "claim_cache", ["result_id"], unique=False)
    op.create_index("ix_claim_cache_corpus", "claim_cache", ["corpus_version"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_claim_cache_corpus", table_name="claim_cache")
    op.drop_index(op.f("ix_claim_cache_result_id"), table_name="claim_cache")
    op.drop_table("claim_cache")
