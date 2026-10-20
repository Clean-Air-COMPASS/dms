"""add deterministic QC policy overrides and result provenance

Revision ID: 20260817_0009
Revises: 20260812_0008
Create Date: 2026-08-17

Existing QC rows are intentionally removed. CompassAQ has no production QC
policy installations to preserve, and legacy global/enabled-row semantics
cannot be mapped safely to sparse property overrides.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260817_0009"
down_revision: Union[str, None] = "20260812_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _scope_where(scope: str, aggregate_specific: bool) -> str:
    aggregation = "aggregate_code IS NOT NULL" if aggregate_specific else "aggregate_code IS NULL"
    if scope == "parameter":
        return f"sensor_id IS NULL AND external_api_id IS NULL AND {aggregation}"
    if scope == "source":
        return f"sensor_id IS NULL AND external_api_id IS NOT NULL AND {aggregation}"
    return f"sensor_id IS NOT NULL AND {aggregation}"


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM qc_rule"))

    with op.batch_alter_table("qc_rule") as batch_op:
        batch_op.alter_column(
            "enabled",
            new_column_name="enabled_override",
            nullable=True,
            server_default=None,
        )
        batch_op.alter_column("params", new_column_name="settings")
        batch_op.alter_column("draft_params", new_column_name="draft_settings")
        batch_op.add_column(sa.Column("external_api_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("failure_action_override", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("policy_unit_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_qc_rule_external_api_id",
            "external_api",
            ["external_api_id"],
            ["external_api_id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_qc_rule_policy_unit_id",
            "unit",
            ["policy_unit_id"],
            ["unit_id"],
            ondelete="RESTRICT",
        )
        batch_op.create_check_constraint(
            "ck_qc_rule_valid_scope",
            "(sensor_id IS NOT NULL AND parameter_id IS NULL AND external_api_id IS NULL) OR "
            "(sensor_id IS NULL AND parameter_id IS NOT NULL AND external_api_id IS NULL) OR "
            "(sensor_id IS NULL AND parameter_id IS NOT NULL AND external_api_id IS NOT NULL)",
        )
        batch_op.create_check_constraint(
            "ck_qc_rule_failure_action",
            "failure_action_override IS NULL OR "
            "failure_action_override IN ('flag_for_review', 'mark_invalid')",
        )
        batch_op.create_index("ix_qc_rule_external_api_id", ["external_api_id"])

    index_specs = (
        ("uq_qc_rule_parameter_generic", ["check_code", "parameter_id"], "parameter", False),
        (
            "uq_qc_rule_parameter_aggregate",
            ["check_code", "parameter_id", "aggregate_code"],
            "parameter",
            True,
        ),
        (
            "uq_qc_rule_source_generic",
            ["check_code", "external_api_id", "parameter_id"],
            "source",
            False,
        ),
        (
            "uq_qc_rule_source_aggregate",
            ["check_code", "external_api_id", "parameter_id", "aggregate_code"],
            "source",
            True,
        ),
        ("uq_qc_rule_sensor_generic", ["check_code", "sensor_id"], "sensor", False),
        (
            "uq_qc_rule_sensor_aggregate",
            ["check_code", "sensor_id", "aggregate_code"],
            "sensor",
            True,
        ),
    )
    for name, columns, scope, aggregate_specific in index_specs:
        predicate = sa.text(_scope_where(scope, aggregate_specific))
        op.create_index(
            name,
            "qc_rule",
            columns,
            unique=True,
            postgresql_where=predicate,
            sqlite_where=predicate,
        )

    with op.batch_alter_table("measurement_qc_result") as batch_op:
        batch_op.alter_column("passed", nullable=True)
        batch_op.alter_column("rule_source", type_=sa.String(length=32))
        batch_op.add_column(
            sa.Column(
                "evaluation_status",
                sa.String(length=16),
                nullable=False,
                server_default="failed",
            )
        )
        batch_op.add_column(sa.Column("failure_action", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("reason_code", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("policy_snapshot", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("policy_provenance", sa.JSON(), nullable=True))
        batch_op.create_check_constraint(
            "ck_mqc_result_evaluation_status",
            "evaluation_status IN ('failed', 'indeterminate')",
        )
        batch_op.create_check_constraint(
            "ck_mqc_result_failure_action",
            "failure_action IS NULL OR failure_action IN ('flag_for_review', 'mark_invalid')",
        )


def downgrade() -> None:
    with op.batch_alter_table("measurement_qc_result") as batch_op:
        batch_op.drop_constraint("ck_mqc_result_failure_action", type_="check")
        batch_op.drop_constraint("ck_mqc_result_evaluation_status", type_="check")
        batch_op.drop_column("policy_provenance")
        batch_op.drop_column("policy_snapshot")
        batch_op.drop_column("reason_code")
        batch_op.drop_column("failure_action")
        batch_op.drop_column("evaluation_status")
        batch_op.alter_column("rule_source", type_=sa.String(length=16))
        batch_op.alter_column("passed", nullable=False)

    for name in (
        "uq_qc_rule_sensor_aggregate",
        "uq_qc_rule_sensor_generic",
        "uq_qc_rule_source_aggregate",
        "uq_qc_rule_source_generic",
        "uq_qc_rule_parameter_aggregate",
        "uq_qc_rule_parameter_generic",
    ):
        op.drop_index(name, table_name="qc_rule")

    with op.batch_alter_table("qc_rule") as batch_op:
        batch_op.drop_index("ix_qc_rule_external_api_id")
        batch_op.drop_constraint("ck_qc_rule_failure_action", type_="check")
        batch_op.drop_constraint("ck_qc_rule_valid_scope", type_="check")
        batch_op.drop_constraint("fk_qc_rule_policy_unit_id", type_="foreignkey")
        batch_op.drop_constraint("fk_qc_rule_external_api_id", type_="foreignkey")
        batch_op.drop_column("policy_unit_id")
        batch_op.drop_column("failure_action_override")
        batch_op.drop_column("external_api_id")
        batch_op.alter_column("draft_settings", new_column_name="draft_params")
        batch_op.alter_column("settings", new_column_name="params")
        batch_op.alter_column(
            "enabled_override",
            new_column_name="enabled",
            nullable=False,
            server_default=sa.text("true"),
        )
