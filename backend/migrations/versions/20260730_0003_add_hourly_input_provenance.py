"""Add explicit provenance for stored hourly concentration streams.

Revision ID: 20260730_0003
Revises: 20260729_0002
Create Date: 2026-07-30
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260730_0003"
down_revision: str | None = "20260729_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sensor",
        sa.Column(
            "hourly_concentration_provenance",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.add_column(
        "sensor",
        sa.Column(
            "hourly_timestamp_semantics",
            sa.String(length=32),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("sensor", "hourly_timestamp_semantics")
    op.drop_column("sensor", "hourly_concentration_provenance")
