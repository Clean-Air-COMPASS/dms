"""Initial CompassAQ schema.

Revision ID: 20260520_0001
Revises:
Create Date: 2026-05-20
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260520_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    postgresql.ENUM("allow", "deny", "inherit", name="updatepolicy").create(op.get_bind(), checkfirst=True)
    update_policy_enum = postgresql.ENUM(
        "allow",
        "deny",
        "inherit",
        name="updatepolicy",
        create_type=False,
    )

    op.create_table(
        "aggregation_period",
        sa.Column("aggregation_period_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("is_rolling", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("expected_interval", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("aggregation_period_id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(
        "ix_aggregation_period_expected_interval",
        "aggregation_period",
        ["expected_interval"],
        unique=False,
    )

    op.create_table(
        "external_api",
        sa.Column("external_api_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider_code", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("api_key", sa.String(length=256), nullable=True),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("external_api_id"),
        sa.UniqueConstraint("provider_code"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "job_schedule",
        sa.Column("job_schedule_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task", sa.String(length=64), nullable=False),
        sa.Column("cron_expr", sa.String(length=64), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default=sa.text("'UTC'")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("allow_overlap", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("job_schedule_id"),
    )
    op.create_index("ix_job_schedule_enabled", "job_schedule", ["enabled"], unique=False)
    op.create_index("ix_job_schedule_task", "job_schedule", ["task"], unique=False)

    op.create_table(
        "role",
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("role_id"),
        sa.UniqueConstraint("name", name="uq_role_name"),
    )

    op.create_table(
        "system_settings",
        sa.Column("system_settings_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("is_system_setup_complete", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("geoapify_api_key", sa.String(length=256), nullable=True),
        sa.Column("default_reference_devices_version", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("system_settings_id"),
    )

    op.create_table(
        "unit",
        sa.Column("unit_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("unit_id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "user",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("email", name="uq_user_email"),
    )
    op.create_index("ix_user_org_id", "user", ["org_id"], unique=False)

    op.create_table(
        "auth_login_attempt",
        sa.Column("auth_login_attempt_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["user.user_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("auth_login_attempt_id"),
    )
    op.create_index("ix_auth_login_attempt_created_at", "auth_login_attempt", ["created_at"], unique=False)
    op.create_index("ix_auth_login_attempt_ip_address", "auth_login_attempt", ["ip_address"], unique=False)

    op.create_table(
        "device",
        sa.Column("device_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("friendly_name", sa.String(length=120), nullable=True),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("external_api_id", sa.Integer(), nullable=False),
        sa.Column("manual_data_source_name", sa.String(length=120), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column(
            "allow_updates",
            update_policy_enum,
            nullable=False,
            server_default=sa.text("'inherit'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["external_api_id"], ["external_api.external_api_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("device_id"),
        sa.UniqueConstraint(
            "external_api_id",
            "external_id",
            name="uq_device_external_api_external_id",
        ),
    )
    op.create_index("ix_device_external_api_id", "device", ["external_api_id"], unique=False)

    op.create_table(
        "job_run",
        sa.Column("job_run_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_schedule_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'running'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["job_schedule_id"], ["job_schedule.job_schedule_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_run_id"),
    )
    op.create_index("ix_job_run_job_schedule_id", "job_run", ["job_schedule_id"], unique=False)

    op.create_table(
        "parameter",
        sa.Column("parameter_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("default_unit_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["default_unit_id"], ["unit.unit_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("parameter_id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "refresh_token",
        sa.Column(
            "refresh_token_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_refresh_token_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["replaced_by_refresh_token_id"], ["refresh_token.refresh_token_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["user.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("refresh_token_id"),
    )
    op.create_index("ix_refresh_token_expires_at", "refresh_token", ["expires_at"], unique=False)
    op.create_index("ix_refresh_token_token_hash", "refresh_token", ["token_hash"], unique=False)
    op.create_index("ix_refresh_token_user_id", "refresh_token", ["user_id"], unique=False)

    op.create_table(
        "user_role",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["role.role_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )

    op.create_table(
        "device_location_history",
        sa.Column("device_location_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["device_id"], ["device.device_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_location_id"),
    )
    op.create_index("ix_device_location_history_device_id", "device_location_history", ["device_id"], unique=False)

    op.create_table(
        "parameter_aggregation_rollup",
        sa.Column("parameter_aggregation_rollup_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("parameter_id", sa.Integer(), nullable=False),
        sa.Column("from_aggregation_period_id", sa.Integer(), nullable=False),
        sa.Column("to_aggregation_period_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["from_aggregation_period_id"],
            ["aggregation_period.aggregation_period_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["parameter_id"], ["parameter.parameter_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["to_aggregation_period_id"],
            ["aggregation_period.aggregation_period_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("parameter_aggregation_rollup_id"),
        sa.UniqueConstraint(
            "parameter_id",
            "from_aggregation_period_id",
            "to_aggregation_period_id",
            name="uq_param_rollup_from_to",
        ),
    )
    op.create_index(
        "ix_parameter_aggregation_rollup_from_aggregation_period_id",
        "parameter_aggregation_rollup",
        ["from_aggregation_period_id"],
        unique=False,
    )
    op.create_index(
        "ix_parameter_aggregation_rollup_parameter_id",
        "parameter_aggregation_rollup",
        ["parameter_id"],
        unique=False,
    )
    op.create_index(
        "ix_parameter_aggregation_rollup_to_aggregation_period_id",
        "parameter_aggregation_rollup",
        ["to_aggregation_period_id"],
        unique=False,
    )

    op.create_table(
        "parameter_aggregation_rule",
        sa.Column("parameter_aggregation_rule_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("parameter_id", sa.Integer(), nullable=False),
        sa.Column("aggregation_period_id", sa.Integer(), nullable=False),
        sa.Column("rounding_method", sa.String(length=16), nullable=False, server_default=sa.text("'round'")),
        sa.Column("rounding_precision", sa.Integer(), nullable=True),
        sa.Column("truncation_method", sa.String(length=16), nullable=False, server_default=sa.text("'none'")),
        sa.Column("truncation_precision", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("thresholds", sa.JSON(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["aggregation_period_id"], ["aggregation_period.aggregation_period_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parameter_id"], ["parameter.parameter_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("parameter_aggregation_rule_id"),
        sa.UniqueConstraint("parameter_id", "aggregation_period_id", name="uq_parameter_agg_parameter_period"),
    )
    op.create_index(
        "ix_parameter_aggregation_rule_aggregation_period_id",
        "parameter_aggregation_rule",
        ["aggregation_period_id"],
        unique=False,
    )
    op.create_index(
        "ix_parameter_aggregation_rule_parameter_id",
        "parameter_aggregation_rule",
        ["parameter_id"],
        unique=False,
    )

    op.create_table(
        "sensor",
        sa.Column("sensor_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("parameter_id", sa.Integer(), nullable=True),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("aggregation_period_id", sa.Integer(), nullable=True),
        sa.Column("external_sensor_id", sa.String(length=128), nullable=True),
        sa.Column(
            "allow_updates",
            update_policy_enum,
            nullable=False,
            server_default=sa.text("'inherit'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["aggregation_period_id"], ["aggregation_period.aggregation_period_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["device_id"], ["device.device_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parameter_id"], ["parameter.parameter_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["unit_id"], ["unit.unit_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("sensor_id"),
        sa.UniqueConstraint(
            "device_id",
            "external_sensor_id",
            name="uq_sensor_device_external_sensor_id",
        ),
    )
    op.create_index("ix_sensor_aggregation_period_id", "sensor", ["aggregation_period_id"], unique=False)
    op.create_index("ix_sensor_parameter_id", "sensor", ["parameter_id"], unique=False)
    op.create_index("ix_sensor_unit_id", "sensor", ["unit_id"], unique=False)

    op.create_table(
        "event",
        sa.Column("event_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False, server_default=sa.text("'openaq_importer'")),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default=sa.text("'info'")),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_email", sa.String(length=320), nullable=True),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("sensor_id", sa.Integer(), nullable=True),
        sa.Column("external_sensor_id", sa.String(length=128), nullable=True),
        sa.Column("endpoint", sa.String(length=512), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("raw_snippet", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user.user_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["device_id"], ["device.device_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sensor_id"], ["sensor.sensor_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_event_actor_user_id", "event", ["actor_user_id"], unique=False)
    op.create_index("ix_event_created_at", "event", ["created_at"], unique=False)
    op.create_index("ix_event_device_id", "event", ["device_id"], unique=False)
    op.create_index("ix_event_event_type", "event", ["event_type"], unique=False)
    op.create_index("ix_event_external_sensor_id", "event", ["external_sensor_id"], unique=False)
    op.create_index("ix_event_sensor_id", "event", ["sensor_id"], unique=False)

    op.create_table(
        "measurement",
        sa.Column("measurement_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sensor_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_valid", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("qc_flags", sa.JSON(), nullable=True),
        sa.Column("qc_version", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["sensor_id"], ["sensor.sensor_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("measurement_id"),
        sa.UniqueConstraint("sensor_id", "observed_at", name="uq_measurement_sensor_observed"),
    )
    op.create_index("ix_measurement_is_valid", "measurement", ["is_valid"], unique=False)
    op.create_index("ix_measurement_sensor_observed_at", "measurement", ["sensor_id", "observed_at"], unique=False)

    op.create_table(
        "qc_rule",
        sa.Column("qc_rule_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("check_code", sa.String(length=64), nullable=False),
        sa.Column("sensor_id", sa.Integer(), nullable=True),
        sa.Column("parameter_id", sa.Integer(), nullable=True),
        sa.Column("aggregate_code", sa.String(length=32), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("state", sa.String(length=16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("draft_params", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["parameter_id"], ["parameter.parameter_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sensor_id"], ["sensor.sensor_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("qc_rule_id"),
    )
    op.create_index("ix_qc_rule_aggregate_code", "qc_rule", ["aggregate_code"], unique=False)
    op.create_index("ix_qc_rule_check_code", "qc_rule", ["check_code"], unique=False)
    op.create_index("ix_qc_rule_parameter_id", "qc_rule", ["parameter_id"], unique=False)
    op.create_index("ix_qc_rule_sensor_id", "qc_rule", ["sensor_id"], unique=False)

    op.create_table(
        "measurement_qc_result",
        sa.Column("measurement_qc_result_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("measurement_id", sa.Integer(), nullable=False),
        sa.Column("parameter_id", sa.Integer(), nullable=True),
        sa.Column("aggregate_code", sa.String(length=32), nullable=False),
        sa.Column("check_code", sa.String(length=64), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default=sa.text("'info'")),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("rule_source", sa.String(length=16), nullable=True),
        sa.Column("params_snapshot", sa.JSON(), nullable=True),
        sa.Column("plugin_version", sa.String(length=16), nullable=True),
        sa.Column("stage", sa.String(length=32), nullable=False, server_default=sa.text("'ingest'")),
        sa.Column("qc_version", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["measurement_id"], ["measurement.measurement_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parameter_id"], ["parameter.parameter_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("measurement_qc_result_id"),
        sa.UniqueConstraint("measurement_id", "check_code", name="uq_mqc_result_measurement_check"),
    )
    op.create_index("ix_measurement_qc_result_measurement_id", "measurement_qc_result", ["measurement_id"], unique=False)
    op.create_index("ix_measurement_qc_result_parameter_id", "measurement_qc_result", ["parameter_id"], unique=False)

    seed_lookup_data()


def downgrade() -> None:
    op.drop_index("ix_measurement_qc_result_parameter_id", table_name="measurement_qc_result")
    op.drop_index("ix_measurement_qc_result_measurement_id", table_name="measurement_qc_result")
    op.drop_table("measurement_qc_result")
    op.drop_index("ix_qc_rule_sensor_id", table_name="qc_rule")
    op.drop_index("ix_qc_rule_parameter_id", table_name="qc_rule")
    op.drop_index("ix_qc_rule_check_code", table_name="qc_rule")
    op.drop_index("ix_qc_rule_aggregate_code", table_name="qc_rule")
    op.drop_table("qc_rule")
    op.drop_index("ix_measurement_sensor_observed_at", table_name="measurement")
    op.drop_index("ix_measurement_is_valid", table_name="measurement")
    op.drop_table("measurement")
    op.drop_index("ix_event_sensor_id", table_name="event")
    op.drop_index("ix_event_external_sensor_id", table_name="event")
    op.drop_index("ix_event_event_type", table_name="event")
    op.drop_index("ix_event_device_id", table_name="event")
    op.drop_index("ix_event_created_at", table_name="event")
    op.drop_index("ix_event_actor_user_id", table_name="event")
    op.drop_table("event")
    op.drop_index("ix_sensor_unit_id", table_name="sensor")
    op.drop_index("ix_sensor_parameter_id", table_name="sensor")
    op.drop_index("ix_sensor_aggregation_period_id", table_name="sensor")
    op.drop_table("sensor")
    op.drop_index("ix_parameter_aggregation_rule_parameter_id", table_name="parameter_aggregation_rule")
    op.drop_index("ix_parameter_aggregation_rule_aggregation_period_id", table_name="parameter_aggregation_rule")
    op.drop_table("parameter_aggregation_rule")
    op.drop_index("ix_parameter_aggregation_rollup_to_aggregation_period_id", table_name="parameter_aggregation_rollup")
    op.drop_index("ix_parameter_aggregation_rollup_parameter_id", table_name="parameter_aggregation_rollup")
    op.drop_index("ix_parameter_aggregation_rollup_from_aggregation_period_id", table_name="parameter_aggregation_rollup")
    op.drop_table("parameter_aggregation_rollup")
    op.drop_index("ix_device_location_history_device_id", table_name="device_location_history")
    op.drop_table("device_location_history")
    op.drop_table("user_role")
    op.drop_index("ix_refresh_token_user_id", table_name="refresh_token")
    op.drop_index("ix_refresh_token_token_hash", table_name="refresh_token")
    op.drop_index("ix_refresh_token_expires_at", table_name="refresh_token")
    op.drop_table("refresh_token")
    op.drop_table("parameter")
    op.drop_index("ix_job_run_job_schedule_id", table_name="job_run")
    op.drop_table("job_run")
    op.drop_index("ix_device_external_api_id", table_name="device")
    op.drop_table("device")
    op.drop_index("ix_auth_login_attempt_ip_address", table_name="auth_login_attempt")
    op.drop_index("ix_auth_login_attempt_created_at", table_name="auth_login_attempt")
    op.drop_table("auth_login_attempt")
    op.drop_index("ix_user_org_id", table_name="user")
    op.drop_table("user")
    op.drop_table("unit")
    op.drop_table("system_settings")
    op.drop_table("role")
    op.drop_index("ix_job_schedule_task", table_name="job_schedule")
    op.drop_index("ix_job_schedule_enabled", table_name="job_schedule")
    op.drop_table("job_schedule")
    op.drop_table("external_api")
    op.drop_index("ix_aggregation_period_expected_interval", table_name="aggregation_period")
    op.drop_table("aggregation_period")

    update_policy_enum = postgresql.ENUM("allow", "deny", "inherit", name="updatepolicy")
    update_policy_enum.drop(op.get_bind(), checkfirst=True)
    op.execute('DROP EXTENSION IF EXISTS "pgcrypto"')


def seed_lookup_data() -> None:
    connection = op.get_bind()

    units_table = sa.table(
        "unit",
        sa.column("code", sa.String(length=32)),
        sa.column("symbol", sa.String(length=32)),
        sa.column("name", sa.String(length=120)),
    )
    op.bulk_insert(
        units_table,
        [
            {"code": "ug_m3", "symbol": "µg/m³", "name": "Micrograms per cubic meter"},
            {"code": "mg_m3", "symbol": "mg/m³", "name": "Milligrams per cubic meter"},
            {"code": "ppm", "symbol": "ppm", "name": "Parts per million"},
            {"code": "ppb", "symbol": "ppb", "name": "Parts per billion"},
            {"code": "celsius", "symbol": "°C", "name": "Degrees Celsius"},
            {"code": "kelvin", "symbol": "K", "name": "Kelvin"},
            {"code": "hpa", "symbol": "hPa", "name": "Hectopascal"},
            {"code": "m_s", "symbol": "m/s", "name": "Meters per second"},
            {"code": "percent", "symbol": "%", "name": "Percent"},
        ],
    )

    connection.execute(
        sa.text(
            """
            INSERT INTO parameter (code, display_name, default_unit_id)
            SELECT parameter_seed.code, parameter_seed.display_name, unit.unit_id
            FROM (
                VALUES
                    ('pm25', 'PM2.5', 'ug_m3'),
                    ('pm10', 'PM10', 'ug_m3'),
                    ('o3', 'O₃', 'ppm'),
                    ('no2', 'NO₂', 'ppm'),
                    ('nox', 'NOx', 'ppm'),
                    ('co', 'CO', 'ppm'),
                    ('no', 'NO', 'ppb'),
                    ('so2', 'SO₂', 'ppm')
            ) AS parameter_seed(code, display_name, unit_code)
            JOIN unit ON unit.code = parameter_seed.unit_code
            """
        )
    )

    aggregation_periods_table = sa.table(
        "aggregation_period",
        sa.column("code", sa.String(length=32)),
        sa.column("display_name", sa.String(length=64)),
        sa.column("duration_minutes", sa.Integer()),
        sa.column("is_rolling", sa.Boolean()),
        sa.column("expected_interval", sa.String(length=16)),
    )
    op.bulk_insert(
        aggregation_periods_table,
        [
            {
                "code": "1m",
                "display_name": "1 Minute",
                "duration_minutes": 1,
                "is_rolling": False,
                "expected_interval": "00:01:00",
            },
            {
                "code": "1h",
                "display_name": "1-hour average",
                "duration_minutes": 60,
                "is_rolling": False,
                "expected_interval": "01:00:00",
            },
            {
                "code": "8h",
                "display_name": "8-hour average",
                "duration_minutes": 480,
                "is_rolling": False,
                "expected_interval": "08:00:00",
            },
            {
                "code": "24h",
                "display_name": "24-hour average",
                "duration_minutes": 1440,
                "is_rolling": False,
                "expected_interval": "24:00:00",
            },
            {
                "code": "rolling_24h",
                "display_name": "Rolling 24-hour",
                "duration_minutes": 1440,
                "is_rolling": True,
                "expected_interval": "01:00:00",
            },
            {
                "code": "aqi",
                "display_name": "AQI",
                "duration_minutes": 60,
                "is_rolling": False,
                "expected_interval": "01:00:00",
            },
        ],
    )

    roles_table = sa.table(
        "role",
        sa.column("name", sa.Text()),
        sa.column("description", sa.Text()),
    )
    op.bulk_insert(
        roles_table,
        [
            {"name": "viewer", "description": "Read-only access"},
            {"name": "analyst", "description": "Data analysis privileges"},
            {"name": "admin", "description": "Administrative access"},
        ],
    )

    connection.execute(sa.text("INSERT INTO system_settings (geoapify_api_key) VALUES (NULL)"))

    connection.execute(
        sa.text(
            """
            INSERT INTO external_api (provider_code, name, base_url, description, params, enabled)
            VALUES
                ('openaq', 'OpenAQ', 'https://api.openaq.org', 'Built-in source: OpenAQ', '{}'::json, false),
                (
                    'purpleair',
                    'PurpleAir',
                    'https://api.purpleair.com/v1/sensors',
                    'Built-in source: PurpleAir',
                    '{"max_lookback_hours": 24}'::json,
                    false
                ),
                (
                    'airgradient',
                    'AirGradient',
                    'https://api.airgradient.com/public/api',
                    'Built-in source: AirGradient',
                    '{}'::json,
                    false
                )
            """
        )
    )

    schedules_table = sa.table(
        "job_schedule",
        sa.column("task", sa.String(length=64)),
        sa.column("cron_expr", sa.String(length=64)),
        sa.column("timezone", sa.String(length=64)),
        sa.column("enabled", sa.Boolean()),
        sa.column("params", sa.JSON()),
        sa.column("allow_overlap", sa.Boolean()),
    )
    op.bulk_insert(
        schedules_table,
        [
            {
                "task": "openaq_import",
                "cron_expr": "*/15 * * * *",
                "timezone": "UTC",
                "enabled": True,
                "params": None,
                "allow_overlap": False,
            },
            {
                "task": "purpleair_import",
                "cron_expr": "0 * * * *",
                "timezone": "UTC",
                "enabled": True,
                "params": None,
                "allow_overlap": False,
            },
            {
                "task": "airgradient_import",
                "cron_expr": "0 * * * *",
                "timezone": "UTC",
                "enabled": True,
                "params": None,
                "allow_overlap": False,
            },
        ],
    )

    connection.execute(
        sa.text(
            """
            INSERT INTO qc_rule (check_code, parameter_id, aggregate_code, enabled, params)
            VALUES ('min_value', NULL, NULL, true, '{"min": 0.0}'::json)
            """
        )
    )

    seed_parameter_aggregation_rules(connection)
    seed_parameter_aggregation_rollups(connection)


def seed_parameter_aggregation_rules(connection: sa.engine.Connection) -> None:
    rule_rows = [
        ("pm25", "1m", "round", 1, "none", None, None),
        ("pm25", "1h", "round", None, "truncate", 1, "Auto-generated rule"),
        ("pm25", "24h", "round", 1, "none", None, "Auto-generated rule"),
        ("pm25", "rolling_24h", "round", None, "none", None, None),
        ("pm25", "aqi", "round", None, "none", None, None),
        ("pm10", "1m", "round", 0, "none", None, None),
        ("pm10", "1h", "round", None, "truncate", 0, "Auto-generated rule"),
        ("pm10", "24h", "round", 0, "none", None, "Auto-generated rule"),
        ("pm10", "rolling_24h", "round", None, "none", None, None),
        ("pm10", "aqi", "round", None, "none", None, None),
        ("o3", "1h", "round", 3, "none", None, "Auto-generated rule"),
        ("o3", "8h", "round", 3, "none", None, "Auto-generated rule"),
        ("o3", "aqi", "round", None, "none", None, None),
        ("co", "1h", "round", 1, "none", None, "Auto-generated rule (migrated from instant to 1h)"),
        ("co", "8h", "round", None, "none", None, None),
        ("co", "aqi", "round", None, "none", None, None),
        ("no2", "1h", "round", 1, "none", None, "Auto-generated rule (migrated from instant to 1h)"),
        ("no2", "aqi", "round", None, "none", None, None),
        ("so2", "1h", "round", 1, "none", None, "Auto-generated rule (migrated from instant to 1h)"),
        ("so2", "aqi", "round", None, "none", None, None),
        ("no", "1h", "round", 1, "none", None, "Auto-generated NO hourly rounding rule"),
    ]

    insert_rule = sa.text(
        """
        INSERT INTO parameter_aggregation_rule (
            parameter_id,
            aggregation_period_id,
            rounding_method,
            rounding_precision,
            truncation_method,
            truncation_precision,
            notes,
            active,
            valid_from
        )
        SELECT
            parameter.parameter_id,
            aggregation_period.aggregation_period_id,
            :rounding_method,
            :rounding_precision,
            :truncation_method,
            :truncation_precision,
            :notes,
            true,
            now()
        FROM parameter
        JOIN aggregation_period ON aggregation_period.code = :aggregation_code
        WHERE parameter.code = :parameter_code
        """
    )

    for (
        parameter_code,
        aggregation_code,
        rounding_method,
        rounding_precision,
        truncation_method,
        truncation_precision,
        notes,
    ) in rule_rows:
        connection.execute(
            insert_rule,
            {
                "parameter_code": parameter_code,
                "aggregation_code": aggregation_code,
                "rounding_method": rounding_method,
                "rounding_precision": rounding_precision,
                "truncation_method": truncation_method,
                "truncation_precision": truncation_precision,
                "notes": notes,
            },
        )


def seed_parameter_aggregation_rollups(connection: sa.engine.Connection) -> None:
    rollup_rows = [
        ("pm25", "1m", "1h"),
        ("pm25", "1h", "24h"),
        ("pm25", "1h", "rolling_24h"),
        ("pm10", "1m", "1h"),
        ("pm10", "1h", "24h"),
        ("pm10", "1h", "rolling_24h"),
        ("o3", "1h", "8h"),
    ]

    insert_rollup = sa.text(
        """
        INSERT INTO parameter_aggregation_rollup (
            parameter_id,
            from_aggregation_period_id,
            to_aggregation_period_id
        )
        SELECT
            parameter.parameter_id,
            from_period.aggregation_period_id,
            to_period.aggregation_period_id
        FROM parameter
        JOIN aggregation_period AS from_period ON from_period.code = :from_code
        JOIN aggregation_period AS to_period ON to_period.code = :to_code
        WHERE parameter.code = :parameter_code
        """
    )

    for parameter_code, from_code, to_code in rollup_rows:
        connection.execute(
            insert_rollup,
            {
                "parameter_code": parameter_code,
                "from_code": from_code,
                "to_code": to_code,
            },
        )
