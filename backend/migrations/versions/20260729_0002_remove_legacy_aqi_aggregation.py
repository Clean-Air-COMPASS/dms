"""Remove the legacy numeric-only AQI aggregation lookup.

Revision ID: 20260729_0002
Revises: 20260520_0001
Create Date: 2026-07-29
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0002"
down_revision: str | None = "20260520_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Delete lookup data that represented the removed measurements AQI path."""
    connection = op.get_bind()
    legacy_period_id = connection.scalar(
        sa.text(
            "SELECT aggregation_period_id "
            "FROM aggregation_period WHERE code = 'aqi'"
        )
    )
    if legacy_period_id is None:
        return

    referenced_sensor_count = connection.scalar(
        sa.text(
            "SELECT count(*) FROM sensor "
            "WHERE aggregation_period_id = :aggregation_period_id"
        ),
        {"aggregation_period_id": legacy_period_id},
    )
    if referenced_sensor_count:
        raise RuntimeError(
            "Cannot remove the legacy AQI aggregation period while sensor "
            "streams still reference it. AQI values must not be stored as "
            "physical sensor measurements."
        )

    connection.execute(
        sa.text(
            "DELETE FROM parameter_aggregation_rule "
            "WHERE aggregation_period_id = :aggregation_period_id"
        ),
        {"aggregation_period_id": legacy_period_id},
    )
    connection.execute(
        sa.text(
            "DELETE FROM aggregation_period "
            "WHERE aggregation_period_id = :aggregation_period_id"
        ),
        {"aggregation_period_id": legacy_period_id},
    )


def downgrade() -> None:
    """Restore the development-era lookup for migration reversibility."""
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "INSERT INTO aggregation_period "
            "(code, display_name, duration_minutes, is_rolling, "
            "expected_interval) "
            "VALUES ('aqi', 'AQI', 60, false, '01:00:00')"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO parameter_aggregation_rule "
            "(parameter_id, aggregation_period_id, rounding_method, "
            "truncation_method) "
            "SELECT parameter.parameter_id, "
            "aggregation_period.aggregation_period_id, 'round', 'none' "
            "FROM parameter CROSS JOIN aggregation_period "
            "WHERE parameter.code IN "
            "('pm25', 'pm10', 'o3', 'co', 'no2', 'so2') "
            "AND aggregation_period.code = 'aqi'"
        )
    )
