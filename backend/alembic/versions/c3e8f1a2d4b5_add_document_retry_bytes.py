"""add document retry bytes

Revision ID: c3e8f1a2d4b5
Revises: b6d4e2f7a901
Create Date: 2026-11-17 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3e8f1a2d4b5"
down_revision: str | None = "b6d4e2f7a901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document_versions", sa.Column("raw_bytes", sa.LargeBinary(), nullable=True))
    op.add_column(
        "document_versions", sa.Column("raw_media_type", sa.String(length=100), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("document_versions", "raw_media_type")
    op.drop_column("document_versions", "raw_bytes")
