"""add totp recovery codes

Revision ID: d7f2a6c9b103
Revises: c3e8f1a2d4b5
Create Date: 2026-11-17 15:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d7f2a6c9b103"
down_revision: str | None = "c3e8f1a2d4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "totp_recovery_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "totp_recovery_codes")
