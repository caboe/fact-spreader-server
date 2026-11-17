"""add api key limits and usage rollups

Revision ID: f3b1c07d5e88
Revises: e5a9b3d8c214
Create Date: 2026-11-17 18:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3b1c07d5e88"
down_revision: str | None = "e5a9b3d8c214"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in ("requests_per_day", "text_chars", "max_file_bytes", "max_batch_files"):
        op.add_column("api_keys", sa.Column(column, sa.Integer(), nullable=True))
    op.create_table(
        "usage_rollups",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("consumer", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "month", "user_id", "consumer", "provider", "model", name="uq_usage_rollup"
        ),
    )
    op.create_index("ix_usage_rollups_month", "usage_rollups", ["month"])


def downgrade() -> None:
    op.drop_index("ix_usage_rollups_month", table_name="usage_rollups")
    op.drop_table("usage_rollups")
    for column in ("max_batch_files", "max_file_bytes", "text_chars", "requests_per_day"):
        op.drop_column("api_keys", column)
