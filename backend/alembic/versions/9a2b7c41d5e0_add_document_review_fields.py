"""add document review fields

Revision ID: 9a2b7c41d5e0
Revises: 7c1f2a9b4e66
Create Date: 2026-11-17 12:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9a2b7c41d5e0"
down_revision: str | None = "7c1f2a9b4e66"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "content_type", sa.String(length=40), nullable=False, server_default="text/markdown"
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "figures", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"
        ),
    )
    op.add_column("documents", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("duplicate_of", sa.String(length=64), nullable=True))
    op.add_column(
        "documents", sa.Column("curator_organization", sa.String(length=200), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("documents", "curator_organization")
    op.drop_column("documents", "duplicate_of")
    op.drop_column("documents", "notes")
    op.drop_column("documents", "figures")
    op.drop_column("documents", "warnings")
    op.drop_column("documents", "content_type")
