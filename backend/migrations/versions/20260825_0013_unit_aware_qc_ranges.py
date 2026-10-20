"""make QC ranges explicitly unit-aware

Revision ID: 20260825_0013
Revises: 20260822_0012
Create Date: 2026-08-25

Existing development QC overrides are removed because the previous sparse
rows treated unit as an overridable property. That meaning cannot be mapped
unambiguously to the new parameter + unit + threshold identity. Measurements
and historical QC results are intentionally preserved.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260825_0013"
down_revision: Union[str, None] = "20260822_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD_INDEXES = (
    "uq_qc_rule_parameter_generic",
    "uq_qc_rule_parameter_aggregate",
    "uq_qc_rule_source_generic",
    "uq_qc_rule_source_aggregate",
    "uq_qc_rule_sensor_generic",
    "uq_qc_rule_sensor_aggregate",
)


def _scope_where(scope: str, aggregate_specific: bool, range_check: bool) -> str:
    aggregation = "aggregate_code IS NOT NULL" if aggregate_specific else "aggregate_code IS NULL"
    check_kind = (
        "check_code IN ('min_value', 'max_value')"
        if range_check
        else "check_code NOT IN ('min_value', 'max_value')"
    )
    if scope == "parameter":
        scope_sql = "sensor_id IS NULL AND external_api_id IS NULL"
    elif scope == "source":
        scope_sql = "sensor_id IS NULL AND external_api_id IS NOT NULL"
    else:
        scope_sql = "sensor_id IS NOT NULL"
    return f"{scope_sql} AND {aggregation} AND {check_kind}"


def _create_rule_indexes() -> None:
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
        predicate = sa.text(_scope_where(scope, aggregate_specific, False))
        op.create_index(
            f"uq_qc_rule_{scope}_{suffix}",
            "qc_rule",
            columns,
            unique=True,
            postgresql_where=predicate,
            sqlite_where=predicate,
        )

        range_columns = list(columns)
        range_columns.insert(-1 if aggregate_specific else len(range_columns), "policy_unit_id")
        range_predicate = sa.text(_scope_where(scope, aggregate_specific, True))
        op.create_index(
            f"uq_qc_rule_{scope}_unit_{suffix}",
            "qc_rule",
            range_columns,
            unique=True,
            postgresql_where=range_predicate,
            sqlite_where=range_predicate,
        )


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO unit (code, symbol, name) "
            "SELECT 'index', 'index', 'Unitless index' "
            "WHERE NOT EXISTS (SELECT 1 FROM unit WHERE code = 'index')"
        )
    )

    op.create_table(
        "parameter_supported_unit",
        sa.Column("parameter_id", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["parameter_id"], ["parameter.parameter_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["unit_id"], ["unit.unit_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("parameter_id", "unit_id"),
    )

    # Every existing parameter supports its declared default and every unit
    # already used by one of its sensors. This preserves current stream facts.
    op.execute(
        sa.text(
            "INSERT INTO parameter_supported_unit (parameter_id, unit_id) "
            "SELECT parameter_id, default_unit_id FROM parameter"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO parameter_supported_unit (parameter_id, unit_id) "
            "SELECT DISTINCT sensor.parameter_id, sensor.unit_id FROM sensor "
            "WHERE sensor.parameter_id IS NOT NULL AND sensor.unit_id IS NOT NULL "
            "ON CONFLICT DO NOTHING"
        )
    )

    # Built-in parameter capabilities are product metadata, not QC limits.
    # Mass-unit gas rows are valid stream units but receive no default range.
    known_supported_units = (
        ("pm25", "ug_m3"),
        ("pm10", "ug_m3"),
        ("pm1", "ug_m3"),
        ("o3", "ppm"), ("o3", "ppb"), ("o3", "ug_m3"),
        ("no2", "ppm"), ("no2", "ppb"), ("no2", "ug_m3"),
        ("so2", "ppm"), ("so2", "ppb"), ("so2", "ug_m3"),
        ("co", "ppm"), ("co", "ppb"), ("co", "ug_m3"), ("co", "mg_m3"),
        ("temperature", "celsius"), ("temperature", "kelvin"),
        ("relative_humidity", "percent"),
        ("pressure", "hpa"),
        ("tvoc_index", "index"), ("nox_index", "index"),
    )
    connection = op.get_bind()
    for parameter_code, unit_code in known_supported_units:
        connection.execute(
            sa.text(
                "INSERT INTO parameter_supported_unit (parameter_id, unit_id) "
                "SELECT parameter.parameter_id, unit.unit_id "
                "FROM parameter JOIN unit ON unit.code = :unit_code "
                "WHERE parameter.code = :parameter_code "
                "ON CONFLICT DO NOTHING"
            ),
            {"parameter_code": parameter_code, "unit_code": unit_code},
        )

    op.execute(sa.text("DELETE FROM qc_rule"))
    for index_name in _OLD_INDEXES:
        op.drop_index(index_name, table_name="qc_rule")
    with op.batch_alter_table("qc_rule") as batch_op:
        batch_op.create_check_constraint(
            "ck_qc_rule_range_unit_required",
            "check_code NOT IN ('min_value', 'max_value') OR policy_unit_id IS NOT NULL",
        )
    _create_rule_indexes()


def downgrade() -> None:
    for scope in ("parameter", "source", "sensor"):
        for suffix in ("generic", "aggregate"):
            op.drop_index(f"uq_qc_rule_{scope}_unit_{suffix}", table_name="qc_rule")
            op.drop_index(f"uq_qc_rule_{scope}_{suffix}", table_name="qc_rule")
    with op.batch_alter_table("qc_rule") as batch_op:
        batch_op.drop_constraint("ck_qc_rule_range_unit_required", type_="check")

    # Restore the previous uniqueness shape. Override rows cannot be restored.
    old_specs = (
        ("uq_qc_rule_parameter_generic", ["check_code", "parameter_id"], "parameter", False),
        ("uq_qc_rule_parameter_aggregate", ["check_code", "parameter_id", "aggregate_code"], "parameter", True),
        ("uq_qc_rule_source_generic", ["check_code", "external_api_id", "parameter_id"], "source", False),
        ("uq_qc_rule_source_aggregate", ["check_code", "external_api_id", "parameter_id", "aggregate_code"], "source", True),
        ("uq_qc_rule_sensor_generic", ["check_code", "sensor_id"], "sensor", False),
        ("uq_qc_rule_sensor_aggregate", ["check_code", "sensor_id", "aggregate_code"], "sensor", True),
    )
    for name, columns, scope, aggregate_specific in old_specs:
        if scope == "parameter":
            scope_sql = "sensor_id IS NULL AND external_api_id IS NULL"
        elif scope == "source":
            scope_sql = "sensor_id IS NULL AND external_api_id IS NOT NULL"
        else:
            scope_sql = "sensor_id IS NOT NULL"
        aggregation = "aggregate_code IS NOT NULL" if aggregate_specific else "aggregate_code IS NULL"
        predicate = sa.text(f"{scope_sql} AND {aggregation}")
        op.create_index(
            name,
            "qc_rule",
            columns,
            unique=True,
            postgresql_where=predicate,
            sqlite_where=predicate,
        )
    op.drop_table("parameter_supported_unit")
