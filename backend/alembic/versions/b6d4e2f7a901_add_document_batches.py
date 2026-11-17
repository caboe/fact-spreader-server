"""add document batches

Revision ID: b6d4e2f7a901
Revises: 9a2b7c41d5e0
Create Date: 2026-11-17 13:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b6d4e2f7a901"
down_revision: str | None = "9a2b7c41d5e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("batch_id", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_documents_batch_id"), "documents", ["batch_id"], unique=False)
    op.create_table(
        "document_batches",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("estimated_usd", sa.String(length=30), nullable=False),
        sa.Column("submitted_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["submitted_by"],
            ["users.id"],
            name=op.f("fk_document_batches_submitted_by_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_batches")),
    )
    op.create_index(op.f("ix_document_batches_state"), "document_batches", ["state"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_document_batches_state"), table_name="document_batches")
    op.drop_table("document_batches")
    op.drop_index(op.f("ix_documents_batch_id"), table_name="documents")
    op.drop_column("documents", "batch_id")
