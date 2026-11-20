"""add chunk embeddings for the retrieval relevance cut

Revision ID: b8d4e2f6a913
Revises: a1c9e4f7b206
Create Date: 2026-11-20 13:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "b8d4e2f6a913"
down_revision: str | None = "a1c9e4f7b206"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "chunk_embeddings",
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.Column("model_key", sa.String(length=80), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("content_hash", "model_key", name=op.f("pk_chunk_embeddings")),
    )


def downgrade() -> None:
    op.drop_table("chunk_embeddings")
