"""Add explicit source measurement frequency and duration metadata.

Revision ID: 20260730_0004
Revises: 20260730_0003
Create Date: 2026-07-30
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260730_0004"
down_revision: str | None = "20260730_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PURPLEAIR_METADATA = {
    "expected_frequency_seconds": 120,
    "measurement_duration_seconds": 120,
    "source_aggregation_duration_seconds": 120,
    "measurement_timestamp_semantics": "provider_received_at",
    "measurement_metadata_status": "provider_documented",
    "measurement_metadata_managed_by": "purpleair_importer",
}


def _ensure_two_minute_aggregation_period(connection: sa.Connection) -> int:
    aggregation_period = sa.table(
        "aggregation_period",
        sa.column("aggregation_period_id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("duration_minutes", sa.Integer()),
        sa.column("is_rolling", sa.Boolean()),
        sa.column("expected_interval", sa.String()),
    )
    aggregation_period_id = connection.scalar(
        sa.select(aggregation_period.c.aggregation_period_id).where(
            aggregation_period.c.code == "2m"
        )
    )
    if aggregation_period_id is None:
        connection.execute(
            sa.insert(aggregation_period).values(
                code="2m",
                display_name="2 Minutes",
                duration_minutes=2,
                is_rolling=False,
                expected_interval="00:02:00",
            )
        )
        aggregation_period_id = connection.scalar(
            sa.select(aggregation_period.c.aggregation_period_id).where(
                aggregation_period.c.code == "2m"
            )
        )
    if aggregation_period_id is None:
        raise RuntimeError("Could not create the 2m aggregation period")
    return aggregation_period_id


def upgrade() -> None:
    op.add_column(
        "sensor",
        sa.Column("expected_frequency_seconds", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sensor",
        sa.Column("measurement_duration_seconds", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sensor",
        sa.Column(
            "source_aggregation_duration_seconds",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "sensor",
        sa.Column(
            "measurement_timestamp_semantics",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "sensor",
        sa.Column("measurement_metadata_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "sensor",
        sa.Column(
            "measurement_metadata_managed_by",
            sa.String(length=64),
            nullable=True,
        ),
    )

    # This narrow backfill identifies PurpleAir by its configured source
    # relationship and limits changes to the PM streams this importer owns.
    connection = op.get_bind()
    two_minute_aggregation_period_id = _ensure_two_minute_aggregation_period(
        connection
    )
    connection.execute(
        sa.text(
            "UPDATE sensor SET "
            "aggregation_period_id = :aggregation_period_id, "
            "expected_frequency_seconds = :expected_frequency_seconds, "
            "measurement_duration_seconds = :measurement_duration_seconds, "
            "source_aggregation_duration_seconds = "
            ":source_aggregation_duration_seconds, "
            "measurement_timestamp_semantics = :measurement_timestamp_semantics, "
            "measurement_metadata_status = :measurement_metadata_status, "
            "measurement_metadata_managed_by = :measurement_metadata_managed_by "
            "WHERE sensor_id IN ("
            "SELECT sensor.sensor_id FROM sensor "
            "JOIN device ON device.device_id = sensor.device_id "
            "JOIN external_api ON "
            "external_api.external_api_id = device.external_api_id "
            "JOIN parameter ON parameter.parameter_id = sensor.parameter_id "
            "WHERE lower(external_api.name) = 'purpleair' "
            "AND lower(parameter.code) IN ('pm25', 'pm10')"
            ")"
        ),
        {
            **PURPLEAIR_METADATA,
            "aggregation_period_id": two_minute_aggregation_period_id,
        },
    )


def downgrade() -> None:
    connection = op.get_bind()
    one_minute_aggregation_period_id = connection.scalar(
        sa.text(
            "SELECT aggregation_period_id FROM aggregation_period "
            "WHERE code = '1m'"
        )
    )
    if one_minute_aggregation_period_id is not None:
        connection.execute(
            sa.text(
                "UPDATE sensor SET aggregation_period_id = :aggregation_period_id "
                "WHERE measurement_metadata_managed_by = 'purpleair_importer' "
                "AND sensor_id IN ("
                "SELECT sensor.sensor_id FROM sensor "
                "JOIN device ON device.device_id = sensor.device_id "
                "JOIN external_api ON "
                "external_api.external_api_id = device.external_api_id "
                "JOIN parameter ON parameter.parameter_id = sensor.parameter_id "
                "WHERE lower(external_api.name) = 'purpleair' "
                "AND lower(parameter.code) IN ('pm25', 'pm10')"
                ")"
            ),
            {"aggregation_period_id": one_minute_aggregation_period_id},
        )

    op.drop_column("sensor", "measurement_metadata_managed_by")
    op.drop_column("sensor", "measurement_metadata_status")
    op.drop_column("sensor", "measurement_timestamp_semantics")
    op.drop_column("sensor", "source_aggregation_duration_seconds")
    op.drop_column("sensor", "measurement_duration_seconds")
    op.drop_column("sensor", "expected_frequency_seconds")
