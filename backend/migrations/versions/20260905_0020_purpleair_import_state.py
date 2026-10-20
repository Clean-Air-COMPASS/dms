"""Persist PurpleAir metadata freshness and successful poll times.

Revision ID: 20260905_0020
Revises: 20260903_0019
"""

from alembic import op
import sqlalchemy as sa

revision = "20260905_0020"
down_revision = "20260903_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purpleair_import_state",
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("device.device_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("metadata_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("history_polled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("purpleair_import_state")
