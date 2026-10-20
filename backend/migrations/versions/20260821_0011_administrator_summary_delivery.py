"""add administrator summary scheduling and delivery persistence

Revision ID: 20260821_0011
Revises: 20260820_0010
Create Date: 2026-08-21

Existing JobRun rows are backfilled as scheduled. Their historical origin
cannot be reconstructed reliably because Phase 1A did not persist a trigger.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260821_0011"
down_revision: Union[str, None] = "20260820_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "email_settings",
        sa.Column(
            "administrator_summary_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "email_settings",
        sa.Column(
            "administrator_summary_cadence",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'daily'"),
        ),
    )
    op.add_column(
        "email_settings",
        sa.Column(
            "administrator_summary_daily_send_time",
            sa.Time(timezone=False),
            nullable=False,
            server_default=sa.text("'07:00:00'"),
        ),
    )
    op.add_column(
        "email_settings",
        sa.Column(
            "administrator_summary_reporting_timezone",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'UTC'"),
        ),
    )
    op.add_column(
        "email_settings",
        sa.Column(
            "administrator_summary_effective_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_email_settings_administrator_summary_cadence",
        "email_settings",
        "administrator_summary_cadence IN "
        "('daily', 'hourly', 'every_15_minutes')",
    )
    op.create_check_constraint(
        "ck_email_settings_administrator_summary_timezone",
        "email_settings",
        "length(trim(administrator_summary_reporting_timezone)) > 0",
    )

    op.add_column(
        "job_run",
        sa.Column(
            "execution_trigger",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'scheduled'"),
        ),
    )
    op.create_check_constraint(
        "ck_job_run_execution_trigger",
        "job_run",
        "execution_trigger IN ('scheduled', 'manual')",
    )
    op.create_index("ix_job_run_started_at", "job_run", ["started_at"])
    op.create_index(
        "ix_measurement_qc_result_created_at",
        "measurement_qc_result",
        ["created_at"],
    )

    op.create_table(
        "administrator_summary_delivery",
        sa.Column(
            "administrator_summary_delivery_id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cadence", sa.String(length=32), nullable=False),
        sa.Column("reporting_timezone", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
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
            "period_start < period_end",
            name="ck_administrator_summary_delivery_period",
        ),
        sa.CheckConstraint(
            "cadence IN ('daily', 'hourly', 'every_15_minutes')",
            name="ck_administrator_summary_delivery_cadence",
        ),
        sa.CheckConstraint(
            "status IN ('sending', 'sent', 'failed', 'delivery_unknown')",
            name="ck_administrator_summary_delivery_status",
        ),
        sa.CheckConstraint(
            "attempt_count BETWEEN 0 AND 2",
            name="ck_administrator_summary_delivery_attempt_count",
        ),
        sa.PrimaryKeyConstraint("administrator_summary_delivery_id"),
        sa.UniqueConstraint(
            "period_start",
            "period_end",
            name="uq_administrator_summary_delivery_period",
        ),
    )


def downgrade() -> None:
    op.drop_table("administrator_summary_delivery")

    op.drop_index(
        "ix_measurement_qc_result_created_at",
        table_name="measurement_qc_result",
    )
    op.drop_index("ix_job_run_started_at", table_name="job_run")
    op.drop_constraint(
        "ck_job_run_execution_trigger",
        "job_run",
        type_="check",
    )
    op.drop_column("job_run", "execution_trigger")

    op.drop_constraint(
        "ck_email_settings_administrator_summary_timezone",
        "email_settings",
        type_="check",
    )
    op.drop_constraint(
        "ck_email_settings_administrator_summary_cadence",
        "email_settings",
        type_="check",
    )
    op.drop_column("email_settings", "administrator_summary_effective_at")
    op.drop_column("email_settings", "administrator_summary_reporting_timezone")
    op.drop_column("email_settings", "administrator_summary_daily_send_time")
    op.drop_column("email_settings", "administrator_summary_cadence")
    op.drop_column("email_settings", "administrator_summary_enabled")
