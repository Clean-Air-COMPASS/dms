"""add persisted system timezone and summary inheritance

Revision ID: 20260822_0012
Revises: 20260821_0011
Create Date: 2026-08-22

The previous administrator-summary column always contained an effective
timezone. It becomes a nullable explicit override so fresh installations can
inherit the platform timezone without copying it into email settings.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260822_0012"
down_revision: Union[str, None] = "20260821_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "system_timezone",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'UTC'"),
        ),
    )
    op.create_check_constraint(
        "ck_system_settings_timezone",
        "system_settings",
        "length(trim(system_timezone)) > 0",
    )

    op.drop_constraint(
        "ck_email_settings_administrator_summary_timezone",
        "email_settings",
        type_="check",
    )
    op.alter_column(
        "email_settings",
        "administrator_summary_reporting_timezone",
        new_column_name="administrator_summary_reporting_timezone_override",
        nullable=True,
        server_default=None,
    )
    op.create_check_constraint(
        "ck_email_settings_administrator_summary_timezone_override",
        "email_settings",
        "administrator_summary_reporting_timezone_override IS NULL OR "
        "length(trim(administrator_summary_reporting_timezone_override)) > 0",
    )

    # The 0010 migration creates the singleton email row before setup. A row
    # that still has the untouched UTC default is the fresh-install marker;
    # leave it NULL so the first completed setup inherits system timezone.
    # Existing configured values, including an explicit UTC value, remain
    # stored as overrides and therefore retain their prior schedule semantics.
    op.execute(
        sa.text(
            "UPDATE email_settings "
            "SET administrator_summary_reporting_timezone_override = NULL "
            "WHERE administrator_summary_reporting_timezone_override = 'UTC' "
            "AND administrator_summary_enabled = false "
            "AND NOT EXISTS (SELECT 1 FROM \"user\") "
            "AND EXISTS ("
            "SELECT 1 FROM system_settings WHERE is_system_setup_complete = false"
            ")"
        )
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_email_settings_administrator_summary_timezone_override",
        "email_settings",
        type_="check",
    )
    # The prior schema required an effective value. UTC is the only safe
    # downgrade value for a row that was inheriting from a later system setting.
    op.execute(
        sa.text(
            "UPDATE email_settings "
            "SET administrator_summary_reporting_timezone_override = 'UTC' "
            "WHERE administrator_summary_reporting_timezone_override IS NULL"
        )
    )
    op.alter_column(
        "email_settings",
        "administrator_summary_reporting_timezone_override",
        new_column_name="administrator_summary_reporting_timezone",
        nullable=False,
        server_default=sa.text("'UTC'"),
    )
    op.create_check_constraint(
        "ck_email_settings_administrator_summary_timezone",
        "email_settings",
        "length(trim(administrator_summary_reporting_timezone)) > 0",
    )

    op.drop_constraint("ck_system_settings_timezone", "system_settings", type_="check")
    op.drop_column("system_settings", "system_timezone")
