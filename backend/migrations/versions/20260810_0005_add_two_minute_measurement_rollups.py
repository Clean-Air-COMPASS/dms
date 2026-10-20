"""Add explicit two-minute PM measurement rollups.

Revision ID: 20260810_0005
Revises: 20260730_0004
Create Date: 2026-08-10
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260810_0005"
down_revision: str | None = "20260730_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ROLLUPS = (("pm25", "2m", "1h"), ("pm10", "2m", "1h"))


def upgrade() -> None:
    connection = op.get_bind()
    for parameter_code, from_code, to_code in ROLLUPS:
        connection.execute(
            sa.text(
                """
                INSERT INTO parameter_aggregation_rollup (
                    parameter_id,
                    from_aggregation_period_id,
                    to_aggregation_period_id
                )
                SELECT parameter.parameter_id, source.aggregation_period_id, target.aggregation_period_id
                FROM parameter
                JOIN aggregation_period AS source ON source.code = :from_code
                JOIN aggregation_period AS target ON target.code = :to_code
                WHERE parameter.code = :parameter_code
                  AND NOT EXISTS (
                    SELECT 1
                    FROM parameter_aggregation_rollup AS existing
                    WHERE existing.parameter_id = parameter.parameter_id
                      AND existing.from_aggregation_period_id = source.aggregation_period_id
                      AND existing.to_aggregation_period_id = target.aggregation_period_id
                  )
                """
            ),
            {
                "parameter_code": parameter_code,
                "from_code": from_code,
                "to_code": to_code,
            },
        )


def downgrade() -> None:
    connection = op.get_bind()
    for parameter_code, from_code, to_code in ROLLUPS:
        connection.execute(
            sa.text(
                """
                DELETE FROM parameter_aggregation_rollup
                WHERE parameter_id = (
                    SELECT parameter_id FROM parameter WHERE code = :parameter_code
                )
                  AND from_aggregation_period_id = (
                    SELECT aggregation_period_id FROM aggregation_period WHERE code = :from_code
                )
                  AND to_aggregation_period_id = (
                    SELECT aggregation_period_id FROM aggregation_period WHERE code = :to_code
                )
                """
            ),
            {
                "parameter_code": parameter_code,
                "from_code": from_code,
                "to_code": to_code,
            },
        )
