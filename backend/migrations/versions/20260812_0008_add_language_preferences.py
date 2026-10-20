"""add language preferences

Revision ID: 20260812_0008
Revises: 20260812_0007
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260812_0008"
down_revision: Union[str, None] = "20260812_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user", sa.Column("preferred_language_code", sa.String(length=2), nullable=True))
    op.create_check_constraint(
        "ck_user_preferred_language_code",
        "user",
        "preferred_language_code IS NULL OR preferred_language_code IN ('en', 'es')",
    )
    op.add_column(
        "system_settings",
        sa.Column("default_language_code", sa.String(length=2), nullable=True),
    )
    op.create_check_constraint(
        "ck_system_settings_default_language_code",
        "system_settings",
        "default_language_code IS NULL OR default_language_code IN ('en', 'es')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_system_settings_default_language_code",
        "system_settings",
        type_="check",
    )
    op.drop_column("system_settings", "default_language_code")
    op.drop_constraint("ck_user_preferred_language_code", "user", type_="check")
    op.drop_column("user", "preferred_language_code")
