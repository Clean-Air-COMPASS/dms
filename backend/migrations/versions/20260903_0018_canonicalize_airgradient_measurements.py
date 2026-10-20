"""canonicalize AirGradient measurement parameters and units

Revision ID: 20260903_0018
Revises: 20260902_0017
Create Date: 2026-09-03

AirGradient wire names such as ``atmp`` and ``rhum`` are provider provenance,
not CompassAQ scientific identities. This migration installs the missing
canonical catalog rows, re-points any pre-release ``temp``/``rh`` and ``c``/``%``
rows without moving measurements, and removes those duplicate catalog aliases.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260903_0018"
down_revision: Union[str, None] = "20260902_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CANONICAL_UNITS = (
    ("ug_m3", "µg/m³", "Micrograms per cubic meter"),
    ("ppm", "ppm", "Parts per million"),
    ("ppb", "ppb", "Parts per billion"),
    ("celsius", "°C", "Degrees Celsius"),
    ("hpa", "hPa", "Hectopascal"),
    ("percent", "%", "Percent"),
    ("index", "index", "Unitless index"),
)

CANONICAL_PARAMETERS = (
    ("pm1", "PM1", "ug_m3"),
    ("co2", "CO₂", "ppm"),
    ("temperature", "Temperature", "celsius"),
    ("relative_humidity", "Relative humidity", "percent"),
    ("pressure", "Pressure", "hpa"),
    ("tvoc", "TVOC", "ppb"),
    ("tvoc_index", "VOC Index", "index"),
    ("nox_index", "NOx Index", "index"),
)

SUPPORTED_PARAMETER_UNITS = (
    ("pm1", "ug_m3"),
    ("pm25", "ug_m3"),
    ("pm10", "ug_m3"),
    ("co2", "ppm"),
    ("temperature", "celsius"),
    ("relative_humidity", "percent"),
    ("pressure", "hpa"),
    ("tvoc", "ppb"),
    ("tvoc_index", "index"),
    ("nox_index", "index"),
)


def _catalog_id(connection, table_name: str, code: str) -> int | None:
    return connection.scalar(
        sa.text(f"SELECT {table_name}_id FROM {table_name} WHERE code = :code"),
        {"code": code},
    )


def _merge_parameter_alias(connection, alias_code: str, canonical_code: str) -> None:
    alias_id = _catalog_id(connection, "parameter", alias_code)
    canonical_id = _catalog_id(connection, "parameter", canonical_code)
    if alias_id is None or canonical_id is None or alias_id == canonical_id:
        return

    # Migration 0016 defines a QC rule's unit scope by policy_unit_id, not by
    # plugin-owned check codes. Canonical rows therefore win only when every
    # database-owned identity field matches, including a nullable policy unit.
    # Non-conflicting rules remain attached after the identifier update;
    # measurement QC history is always preserved.
    connection.execute(
        sa.text(
            "DELETE FROM qc_rule AS legacy WHERE legacy.parameter_id = :alias_id "
            "AND EXISTS (SELECT 1 FROM qc_rule AS canonical "
            "WHERE canonical.parameter_id = :canonical_id "
            "AND canonical.check_code = legacy.check_code "
            "AND canonical.sensor_id IS NOT DISTINCT FROM legacy.sensor_id "
            "AND canonical.external_api_id IS NOT DISTINCT FROM legacy.external_api_id "
            "AND canonical.aggregate_code IS NOT DISTINCT FROM legacy.aggregate_code "
            "AND canonical.policy_unit_id IS NOT DISTINCT FROM legacy.policy_unit_id)"
        ),
        {"alias_id": alias_id, "canonical_id": canonical_id},
    )
    connection.execute(
        sa.text(
            "DELETE FROM parameter_aggregation_rule AS legacy "
            "WHERE legacy.parameter_id = :alias_id AND EXISTS ("
            "SELECT 1 FROM parameter_aggregation_rule AS canonical "
            "WHERE canonical.parameter_id = :canonical_id "
            "AND canonical.aggregation_period_id = legacy.aggregation_period_id)"
        ),
        {"alias_id": alias_id, "canonical_id": canonical_id},
    )
    connection.execute(
        sa.text(
            "DELETE FROM parameter_aggregation_rollup AS legacy "
            "WHERE legacy.parameter_id = :alias_id AND EXISTS ("
            "SELECT 1 FROM parameter_aggregation_rollup AS canonical "
            "WHERE canonical.parameter_id = :canonical_id "
            "AND canonical.from_aggregation_period_id = legacy.from_aggregation_period_id "
            "AND canonical.to_aggregation_period_id = legacy.to_aggregation_period_id)"
        ),
        {"alias_id": alias_id, "canonical_id": canonical_id},
    )
    connection.execute(
        sa.text(
            "INSERT INTO parameter_supported_unit (parameter_id, unit_id) "
            "SELECT :canonical_id, unit_id FROM parameter_supported_unit "
            "WHERE parameter_id = :alias_id ON CONFLICT DO NOTHING"
        ),
        {"alias_id": alias_id, "canonical_id": canonical_id},
    )

    for table_name in (
        "sensor",
        "measurement_qc_result",
        "qc_rule",
        "parameter_aggregation_rule",
        "parameter_aggregation_rollup",
    ):
        connection.execute(
            sa.text(
                f"UPDATE {table_name} SET parameter_id = :canonical_id "
                "WHERE parameter_id = :alias_id"
            ),
            {"alias_id": alias_id, "canonical_id": canonical_id},
        )
    connection.execute(
        sa.text("DELETE FROM parameter_supported_unit WHERE parameter_id = :alias_id"),
        {"alias_id": alias_id},
    )
    connection.execute(
        sa.text("DELETE FROM parameter WHERE parameter_id = :alias_id"),
        {"alias_id": alias_id},
    )


def _merge_unit_alias(connection, alias_code: str, canonical_code: str) -> None:
    alias_id = _catalog_id(connection, "unit", alias_code)
    canonical_id = _catalog_id(connection, "unit", canonical_code)
    if alias_id is None or canonical_id is None or alias_id == canonical_id:
        return

    # Compare the complete rule identity before changing the unit foreign key.
    # This is plugin-generic: any check can be unit-scoped when policy_unit_id
    # is present. The canonical-unit row wins only a true duplicate.
    connection.execute(
        sa.text(
            "DELETE FROM qc_rule AS legacy WHERE legacy.policy_unit_id = :alias_id "
            "AND EXISTS (SELECT 1 FROM qc_rule AS canonical "
            "WHERE canonical.policy_unit_id = :canonical_id "
            "AND canonical.check_code = legacy.check_code "
            "AND canonical.parameter_id IS NOT DISTINCT FROM legacy.parameter_id "
            "AND canonical.sensor_id IS NOT DISTINCT FROM legacy.sensor_id "
            "AND canonical.external_api_id IS NOT DISTINCT FROM legacy.external_api_id "
            "AND canonical.aggregate_code IS NOT DISTINCT FROM legacy.aggregate_code)"
        ),
        {"alias_id": alias_id, "canonical_id": canonical_id},
    )
    connection.execute(
        sa.text(
            "INSERT INTO parameter_supported_unit (parameter_id, unit_id) "
            "SELECT parameter_id, :canonical_id FROM parameter_supported_unit "
            "WHERE unit_id = :alias_id ON CONFLICT DO NOTHING"
        ),
        {"alias_id": alias_id, "canonical_id": canonical_id},
    )
    connection.execute(
        sa.text(
            "UPDATE parameter SET default_unit_id = :canonical_id "
            "WHERE default_unit_id = :alias_id"
        ),
        {"alias_id": alias_id, "canonical_id": canonical_id},
    )
    connection.execute(
        sa.text("UPDATE sensor SET unit_id = :canonical_id WHERE unit_id = :alias_id"),
        {"alias_id": alias_id, "canonical_id": canonical_id},
    )
    connection.execute(
        sa.text(
            "UPDATE qc_rule SET policy_unit_id = :canonical_id "
            "WHERE policy_unit_id = :alias_id"
        ),
        {"alias_id": alias_id, "canonical_id": canonical_id},
    )
    connection.execute(
        sa.text("DELETE FROM parameter_supported_unit WHERE unit_id = :alias_id"),
        {"alias_id": alias_id},
    )
    connection.execute(
        sa.text("DELETE FROM unit WHERE unit_id = :alias_id"),
        {"alias_id": alias_id},
    )


def upgrade() -> None:
    connection = op.get_bind()

    for code, symbol, name in CANONICAL_UNITS:
        connection.execute(
            sa.text(
                "INSERT INTO unit (code, symbol, name) VALUES (:code, :symbol, :name) "
                "ON CONFLICT (code) DO UPDATE SET symbol = EXCLUDED.symbol, name = EXCLUDED.name"
            ),
            {"code": code, "symbol": symbol, "name": name},
        )

    for code, display_name, unit_code in CANONICAL_PARAMETERS:
        connection.execute(
            sa.text(
                "INSERT INTO parameter (code, display_name, default_unit_id) "
                "SELECT :code, :display_name, unit_id FROM unit WHERE code = :unit_code "
                "ON CONFLICT (code) DO UPDATE SET "
                "display_name = EXCLUDED.display_name, "
                "default_unit_id = EXCLUDED.default_unit_id"
            ),
            {
                "code": code,
                "display_name": display_name,
                "unit_code": unit_code,
            },
        )

    _merge_parameter_alias(connection, "temp", "temperature")
    _merge_parameter_alias(connection, "rh", "relative_humidity")
    _merge_unit_alias(connection, "c", "celsius")
    _merge_unit_alias(connection, "%", "percent")

    for parameter_code, unit_code in SUPPORTED_PARAMETER_UNITS:
        connection.execute(
            sa.text(
                "INSERT INTO parameter_supported_unit (parameter_id, unit_id) "
                "SELECT parameter.parameter_id, unit.unit_id FROM parameter "
                "JOIN unit ON unit.code = :unit_code "
                "WHERE parameter.code = :parameter_code ON CONFLICT DO NOTHING"
            ),
            {"parameter_code": parameter_code, "unit_code": unit_code},
        )

    # Existing fixed-reference streams predate temporal metadata. Their public
    # current-measure payloads are Wi-Fi observations; later imports refresh
    # this metadata from each current provider payload.
    connection.execute(
        sa.text(
            "UPDATE sensor SET "
            "aggregation_period_id = (SELECT aggregation_period_id FROM aggregation_period WHERE code = '1m'), "
            "expected_frequency_seconds = 60, "
            "measurement_duration_seconds = 12, "
            "source_aggregation_duration_seconds = 12, "
            "measurement_timestamp_semantics = 'observation_instant', "
            "measurement_metadata_status = 'provider_documented', "
            "measurement_metadata_managed_by = 'airgradient_importer' "
            "WHERE device_id IN (SELECT device.device_id FROM device "
            "JOIN external_api ON external_api.external_api_id = device.external_api_id "
            "WHERE external_api.provider_code = 'airgradient')"
        )
    )


def downgrade() -> None:
    # Canonicalized measurements and sensor relationships must not be moved
    # back onto duplicate scientific aliases. The catalog additions are safe
    # for the preceding schema and intentionally remain in place.
    pass
