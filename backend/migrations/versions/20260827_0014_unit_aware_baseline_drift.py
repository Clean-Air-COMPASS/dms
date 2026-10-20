"""make baseline-drift QC rules explicitly unit-aware

Revision ID: 20260827_0014
Revises: 20260825_0013
Create Date: 2026-08-27

Baseline drift's ``max_drift_per_day`` carries the measurement unit. Existing
rules are retained and assigned the sensor unit (sensor scope) or parameter
default unit (parameter/source scope). No gas mass-to-mixing-ratio conversion
is performed.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260827_0014"
down_revision: Union[str, None] = "20260825_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _drop_rule_indexes() -> None:
    for scope in ("parameter", "source", "sensor"):
        for suffix in ("generic", "aggregate"):
            op.drop_index(f"uq_qc_rule_{scope}_{suffix}", table_name="qc_rule")
            op.drop_index(f"uq_qc_rule_{scope}_unit_{suffix}", table_name="qc_rule")


def _create_rule_indexes(*, baseline_is_unit_scoped: bool) -> None:
    specs = (
        ("parameter", False, ["check_code", "parameter_id"]),
        ("parameter", True, ["check_code", "parameter_id", "aggregate_code"]),
        ("source", False, ["check_code", "external_api_id", "parameter_id"]),
        ("source", True, ["check_code", "external_api_id", "parameter_id", "aggregate_code"]),
        ("sensor", False, ["check_code", "sensor_id"]),
        ("sensor", True, ["check_code", "sensor_id", "aggregate_code"]),
    )
    for scope, aggregate_specific, columns in specs:
        suffix = "aggregate" if aggregate_specific else "generic"
        if baseline_is_unit_scoped:
            generic_checks = "check_code NOT IN ('min_value', 'max_value', 'baseline_drift')"
            unit_checks = "check_code IN ('min_value', 'max_value', 'baseline_drift')"
        else:
            generic_checks = "check_code NOT IN ('min_value', 'max_value')"
            unit_checks = "check_code IN ('min_value', 'max_value')"

        if scope == "parameter":
            scope_sql = "sensor_id IS NULL AND external_api_id IS NULL"
        elif scope == "source":
            scope_sql = "sensor_id IS NULL AND external_api_id IS NOT NULL"
        else:
            scope_sql = "sensor_id IS NOT NULL"
        aggregation = "aggregate_code IS NOT NULL" if aggregate_specific else "aggregate_code IS NULL"

        generic_predicate = sa.text(f"{scope_sql} AND {aggregation} AND {generic_checks}")
        op.create_index(
            f"uq_qc_rule_{scope}_{suffix}",
            "qc_rule",
            columns,
            unique=True,
            postgresql_where=generic_predicate,
            sqlite_where=generic_predicate,
        )

        unit_columns = list(columns)
        unit_columns.insert(-1 if aggregate_specific else len(unit_columns), "policy_unit_id")
        unit_predicate = sa.text(f"{scope_sql} AND {aggregation} AND {unit_checks}")
        op.create_index(
            f"uq_qc_rule_{scope}_unit_{suffix}",
            "qc_rule",
            unit_columns,
            unique=True,
            postgresql_where=unit_predicate,
            sqlite_where=unit_predicate,
        )


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE qc_rule SET policy_unit_id = sensor.unit_id "
            "FROM sensor WHERE qc_rule.sensor_id = sensor.sensor_id "
            "AND qc_rule.check_code = 'baseline_drift' "
            "AND qc_rule.policy_unit_id IS NULL"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE qc_rule SET policy_unit_id = parameter.default_unit_id "
            "FROM parameter WHERE qc_rule.parameter_id = parameter.parameter_id "
            "AND qc_rule.check_code = 'baseline_drift' "
            "AND qc_rule.policy_unit_id IS NULL"
        )
    )
    unresolved = int(
        connection.scalar(
            sa.text(
                "SELECT count(*) FROM qc_rule "
                "WHERE check_code = 'baseline_drift' AND policy_unit_id IS NULL"
            )
        )
        or 0
    )
    if unresolved:
        raise RuntimeError(
            "Baseline-drift rules without a resolvable sensor or parameter unit "
            "must be repaired before applying migration 20260827_0014"
        )

    _drop_rule_indexes()
    with op.batch_alter_table("qc_rule") as batch_op:
        batch_op.drop_constraint("ck_qc_rule_range_unit_required", type_="check")
        batch_op.create_check_constraint(
            "ck_qc_rule_unit_scoped_check_requires_unit",
            "check_code NOT IN ('min_value', 'max_value', 'baseline_drift') "
            "OR policy_unit_id IS NOT NULL",
        )
    _create_rule_indexes(baseline_is_unit_scoped=True)
    op.create_index(
        "ix_mqc_result_baseline_warmup_measurement",
        "measurement_qc_result",
        ["measurement_id"],
        unique=False,
        postgresql_where=sa.text(
            "check_code = 'baseline_drift' "
            "AND evaluation_status = 'indeterminate' "
            "AND reason_code = 'insufficient_history'"
        ),
        sqlite_where=sa.text(
            "check_code = 'baseline_drift' "
            "AND evaluation_status = 'indeterminate' "
            "AND reason_code = 'insufficient_history'"
        ),
    )


def downgrade() -> None:
    connection = op.get_bind()
    duplicate_scope_count = int(
        connection.scalar(
            sa.text(
                "SELECT count(*) FROM ("
                "SELECT sensor_id, parameter_id, external_api_id, aggregate_code "
                "FROM qc_rule WHERE check_code = 'baseline_drift' "
                "GROUP BY sensor_id, parameter_id, external_api_id, aggregate_code "
                "HAVING count(*) > 1"
                ") duplicates"
            )
        )
        or 0
    )
    if duplicate_scope_count:
        raise RuntimeError(
            "Cannot downgrade while a QC scope has baseline-drift overrides for multiple units"
        )

    op.drop_index(
        "ix_mqc_result_baseline_warmup_measurement",
        table_name="measurement_qc_result",
    )
    _drop_rule_indexes()
    with op.batch_alter_table("qc_rule") as batch_op:
        batch_op.drop_constraint(
            "ck_qc_rule_unit_scoped_check_requires_unit", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_qc_rule_range_unit_required",
            "check_code NOT IN ('min_value', 'max_value') OR policy_unit_id IS NOT NULL",
        )
    connection.execute(
        sa.text(
            "UPDATE qc_rule SET policy_unit_id = NULL "
            "WHERE check_code = 'baseline_drift'"
        )
    )
    _create_rule_indexes(baseline_is_unit_scoped=False)
