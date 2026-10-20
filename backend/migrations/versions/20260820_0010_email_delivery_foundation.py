"""add encrypted email delivery settings foundation

Revision ID: 20260820_0010
Revises: 20260817_0009
Create Date: 2026-08-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260820_0010"
down_revision: Union[str, None] = "20260817_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    email_settings = op.create_table(
        "email_settings",
        sa.Column("email_settings_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("smtp_host", sa.String(length=253), nullable=True),
        sa.Column("smtp_port", sa.Integer(), nullable=True),
        sa.Column("smtp_security_mode", sa.String(length=16), nullable=True),
        sa.Column("smtp_username", sa.String(length=512), nullable=True),
        sa.Column("smtp_password_ciphertext", sa.Text(), nullable=True),
        sa.Column("from_email", sa.String(length=320), nullable=True),
        sa.Column("from_display_name", sa.String(length=200), nullable=True),
        sa.Column("reply_to_email", sa.String(length=320), nullable=True),
        sa.Column(
            "administrator_recipients",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "last_test_status",
            sa.String(length=16),
            nullable=True,
        ),
        sa.Column(
            "last_test_error_code",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "email_settings_id = 1",
            name="ck_email_settings_singleton",
        ),
        sa.CheckConstraint(
            "smtp_port IS NULL OR smtp_port BETWEEN 1 AND 65535",
            name="ck_email_settings_smtp_port",
        ),
        sa.CheckConstraint(
            "smtp_security_mode IS NULL OR "
            "smtp_security_mode IN ('starttls', 'ssl_tls', 'none')",
            name="ck_email_settings_security_mode",
        ),
        sa.CheckConstraint(
            "(last_test_status IS NULL "
            "AND last_test_error_code IS NULL "
            "AND last_tested_at IS NULL) "
            "OR (last_test_status = 'success' "
            "AND last_test_error_code IS NULL "
            "AND last_tested_at IS NOT NULL) "
            "OR (last_test_status = 'failed' "
            "AND last_test_error_code IS NOT NULL "
            "AND last_tested_at IS NOT NULL)",
            name="ck_email_settings_test_state",
        ),
        sa.PrimaryKeyConstraint("email_settings_id"),
    )
    op.bulk_insert(
        email_settings,
        [
            {
                "email_settings_id": 1,
                "enabled": False,
                "administrator_recipients": [],
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("email_settings")
