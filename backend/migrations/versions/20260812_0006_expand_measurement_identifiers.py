"""Expand ingestion-scale measurement identifiers to BIGINT.

Revision ID: 20260812_0006
Revises: 20260810_0005
Create Date: 2026-08-12
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260812_0006"
down_revision: str | None = "20260810_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INTEGER_MAX = 2_147_483_647
MEASUREMENT_SEQUENCE = "measurement_measurement_id_seq"
QC_RESULT_SEQUENCE = "measurement_qc_result_measurement_qc_result_id_seq"
MEASUREMENT_QC_FOREIGN_KEY = "measurement_qc_result_measurement_id_fkey"


def upgrade() -> None:
    """Widen fact-table identifiers without replacing or resetting sequences."""
    op.drop_constraint(
        MEASUREMENT_QC_FOREIGN_KEY,
        "measurement_qc_result",
        type_="foreignkey",
    )

    # Each index is covered by an existing unique index with the same leading
    # columns, so retaining it would only add write and storage overhead.
    op.drop_index("ix_measurement_sensor_observed_at", table_name="measurement")
    op.drop_index(
        "ix_measurement_qc_result_measurement_id",
        table_name="measurement_qc_result",
    )

    # A SERIAL-style column and its owned sequence are separate PostgreSQL
    # objects. Alter both sequences in place so their state, defaults, and
    # ownership remain unchanged while their range becomes 64-bit.
    op.execute(f"ALTER SEQUENCE {MEASUREMENT_SEQUENCE} AS BIGINT NO MAXVALUE")
    op.execute(f"ALTER SEQUENCE {QC_RESULT_SEQUENCE} AS BIGINT NO MAXVALUE")

    op.alter_column(
        "measurement",
        "measurement_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
        existing_server_default=sa.text(
            "nextval('measurement_measurement_id_seq'::regclass)"
        ),
    )
    op.alter_column(
        "measurement_qc_result",
        "measurement_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )
    op.alter_column(
        "measurement_qc_result",
        "measurement_qc_result_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
        existing_server_default=sa.text(
            "nextval('measurement_qc_result_measurement_qc_result_id_seq'::regclass)"
        ),
    )

    op.create_foreign_key(
        MEASUREMENT_QC_FOREIGN_KEY,
        "measurement_qc_result",
        "measurement",
        ["measurement_id"],
        ["measurement_id"],
        ondelete="CASCADE",
    )

    op.execute("ANALYZE measurement")
    op.execute("ANALYZE measurement_qc_result")


def _assert_integer_downgrade_is_safe() -> None:
    connection = op.get_bind()
    values = connection.execute(
        sa.text(
            """
            SELECT
                COALESCE((SELECT max(measurement_id) FROM measurement), 0),
                COALESCE((SELECT max(measurement_id) FROM measurement_qc_result), 0),
                COALESCE((SELECT max(measurement_qc_result_id) FROM measurement_qc_result), 0),
                (SELECT last_value FROM measurement_measurement_id_seq),
                (SELECT last_value FROM measurement_qc_result_measurement_qc_result_id_seq)
            """
        )
    ).one()
    if any(int(value) > INTEGER_MAX for value in values):
        raise RuntimeError(
            "Cannot downgrade measurement identifiers to INTEGER because a row "
            "or owned sequence has exceeded 2,147,483,647."
        )


def downgrade() -> None:
    """Narrow identifiers only while every stored and allocated ID still fits."""
    _assert_integer_downgrade_is_safe()

    op.drop_constraint(
        MEASUREMENT_QC_FOREIGN_KEY,
        "measurement_qc_result",
        type_="foreignkey",
    )

    op.alter_column(
        "measurement_qc_result",
        "measurement_qc_result_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
        existing_server_default=sa.text(
            "nextval('measurement_qc_result_measurement_qc_result_id_seq'::regclass)"
        ),
    )
    op.alter_column(
        "measurement_qc_result",
        "measurement_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
    op.alter_column(
        "measurement",
        "measurement_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
        existing_server_default=sa.text(
            "nextval('measurement_measurement_id_seq'::regclass)"
        ),
    )

    op.execute(f"ALTER SEQUENCE {MEASUREMENT_SEQUENCE} AS INTEGER NO MAXVALUE")
    op.execute(f"ALTER SEQUENCE {QC_RESULT_SEQUENCE} AS INTEGER NO MAXVALUE")

    op.create_foreign_key(
        MEASUREMENT_QC_FOREIGN_KEY,
        "measurement_qc_result",
        "measurement",
        ["measurement_id"],
        ["measurement_id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_measurement_sensor_observed_at",
        "measurement",
        ["sensor_id", "observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_measurement_qc_result_measurement_id",
        "measurement_qc_result",
        ["measurement_id"],
        unique=False,
    )

    op.execute("ANALYZE measurement")
    op.execute("ANALYZE measurement_qc_result")
