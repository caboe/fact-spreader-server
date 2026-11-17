"""add roles and user limits

Revision ID: e5a9b3d8c214
Revises: d7f2a6c9b103
Create Date: 2026-11-17 15:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5a9b3d8c214"
down_revision: str | None = "d7f2a6c9b103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "roles", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "denied_permissions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    for column in ("requests_per_day", "text_chars", "max_file_bytes", "max_batch_files"):
        op.add_column("users", sa.Column(column, sa.Integer(), nullable=True))


def downgrade() -> None:
    for column in ("max_batch_files", "max_file_bytes", "text_chars", "requests_per_day"):
        op.drop_column("users", column)
    op.drop_column("users", "denied_permissions")
    op.drop_column("users", "roles")
