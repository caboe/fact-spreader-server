"""add model registry source and capability tests

Revision ID: a1c9e4f7b206
Revises: f3b1c07d5e88
Create Date: 2026-11-17 18:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c9e4f7b206"
down_revision: str | None = "f3b1c07d5e88"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("models", "gateway_alias", existing_type=sa.String(length=80), nullable=True)
    op.add_column("models", sa.Column("source_model_id", sa.String(length=64), nullable=True))
    op.create_foreign_key(
        "fk_models_source_model",
        "models",
        "models",
        ["source_model_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_models_source_model_id", "models", ["source_model_id"])
    op.create_table(
        "model_capability_tests",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("capability", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("detail", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("dimension", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tested_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["model_id"], ["models.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("model_id", "capability", name="uq_model_capability"),
    )
    op.create_index("ix_model_capability_tests_model_id", "model_capability_tests", ["model_id"])


def downgrade() -> None:
    op.drop_index("ix_model_capability_tests_model_id", table_name="model_capability_tests")
    op.drop_table("model_capability_tests")
    op.drop_index("ix_models_source_model_id", table_name="models")
    op.drop_constraint("fk_models_source_model", "models", type_="foreignkey")
    op.drop_column("models", "source_model_id")
    op.alter_column("models", "gateway_alias", existing_type=sa.String(length=80), nullable=False)
