"""make QC rule unit scoping independent of check code

Revision ID: 20260827_0016
Revises: 20260827_0015
Create Date: 2026-08-27

Installed plugins declare unit-aware numeric settings through ``unit_settings``.
The database therefore distinguishes unitless and unit-scoped rows by the
presence of ``policy_unit_id`` instead of a core-maintained check-code list.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260827_0016"
down_revision: Union[str, None] = "20260827_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX_SPECS = (
    ("parameter", False, ["check_code", "parameter_id"]),
    ("parameter", True, ["check_code", "parameter_id", "aggregate_code"]),
    ("source", False, ["check_code", "external_api_id", "parameter_id"]),
    ("source", True, ["check_code", "external_api_id", "parameter_id", "aggregate_code"]),
    ("sensor", False, ["check_code", "sensor_id"]),
    ("sensor", True, ["check_code", "sensor_id", "aggregate_code"]),
)


def _scope_predicate(scope: str, aggregate_specific: bool) -> str:
    aggregation = "aggregate_code IS NOT NULL" if aggregate_specific else "aggregate_code IS NULL"
    if scope == "parameter":
        scope_sql = "sensor_id IS NULL AND external_api_id IS NULL"
    elif scope == "source":
        scope_sql = "sensor_id IS NULL AND external_api_id IS NOT NULL"
    else:
        scope_sql = "sensor_id IS NOT NULL"
    return f"{scope_sql} AND {aggregation}"


def _drop_rule_indexes() -> None:
    for scope, aggregate_specific, _columns in _INDEX_SPECS:
        suffix = "aggregate" if aggregate_specific else "generic"
        op.drop_index(f"uq_qc_rule_{scope}_{suffix}", table_name="qc_rule")
        op.drop_index(f"uq_qc_rule_{scope}_unit_{suffix}", table_name="qc_rule")


def _create_plugin_driven_indexes() -> None:
    for scope, aggregate_specific, columns in _INDEX_SPECS:
        suffix = "aggregate" if aggregate_specific else "generic"
        scope_sql = _scope_predicate(scope, aggregate_specific)
        op.create_index(
            f"uq_qc_rule_{scope}_{suffix}",
            "qc_rule",
            columns,
            unique=True,
            postgresql_where=sa.text(f"{scope_sql} AND policy_unit_id IS NULL"),
            sqlite_where=sa.text(f"{scope_sql} AND policy_unit_id IS NULL"),
        )
        unit_columns = list(columns)
        unit_columns.insert(-1 if aggregate_specific else len(unit_columns), "policy_unit_id")
        op.create_index(
            f"uq_qc_rule_{scope}_unit_{suffix}",
            "qc_rule",
            unit_columns,
            unique=True,
            postgresql_where=sa.text(f"{scope_sql} AND policy_unit_id IS NOT NULL"),
            sqlite_where=sa.text(f"{scope_sql} AND policy_unit_id IS NOT NULL"),
        )


def _create_previous_indexes() -> None:
    unit_check_codes = "'min_value', 'max_value', 'baseline_drift'"
    for scope, aggregate_specific, columns in _INDEX_SPECS:
        suffix = "aggregate" if aggregate_specific else "generic"
        scope_sql = _scope_predicate(scope, aggregate_specific)
        op.create_index(
            f"uq_qc_rule_{scope}_{suffix}",
            "qc_rule",
            columns,
            unique=True,
            postgresql_where=sa.text(f"{scope_sql} AND check_code NOT IN ({unit_check_codes})"),
            sqlite_where=sa.text(f"{scope_sql} AND check_code NOT IN ({unit_check_codes})"),
        )
        unit_columns = list(columns)
        unit_columns.insert(-1 if aggregate_specific else len(unit_columns), "policy_unit_id")
        op.create_index(
            f"uq_qc_rule_{scope}_unit_{suffix}",
            "qc_rule",
            unit_columns,
            unique=True,
            postgresql_where=sa.text(f"{scope_sql} AND check_code IN ({unit_check_codes})"),
            sqlite_where=sa.text(f"{scope_sql} AND check_code IN ({unit_check_codes})"),
        )


def upgrade() -> None:
    _drop_rule_indexes()
    with op.batch_alter_table("qc_rule") as batch_op:
        batch_op.drop_constraint(
            "ck_qc_rule_unit_scoped_check_requires_unit",
            type_="check",
        )
    _create_plugin_driven_indexes()


def downgrade() -> None:
    connection = op.get_bind()
    incompatible_count = int(
        connection.scalar(
            sa.text(
                "SELECT count(*) FROM qc_rule "
                "WHERE policy_unit_id IS NOT NULL "
                "AND check_code NOT IN ('min_value', 'max_value', 'baseline_drift')"
            )
        )
        or 0
    )
    if incompatible_count:
        raise RuntimeError(
            "Cannot downgrade while independently installed plugins have unit-scoped QC rules"
        )
    _drop_rule_indexes()
    with op.batch_alter_table("qc_rule") as batch_op:
        batch_op.create_check_constraint(
            "ck_qc_rule_unit_scoped_check_requires_unit",
            "check_code NOT IN ('min_value', 'max_value', 'baseline_drift') "
            "OR policy_unit_id IS NOT NULL",
        )
    _create_previous_indexes()
