from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from postgresql_test_support import temporary_postgres_database, upgrade


def test_airgradient_alias_repair_preserves_measurements_and_qc_provenance() -> None:
    with temporary_postgres_database("airgradient_canonical") as (database_url, engine):
        upgrade(database_url, "20260902_0017")
        with engine.begin() as connection:
            source_id = connection.scalar(
                text(
                    "SELECT external_api_id FROM external_api "
                    "WHERE provider_code = 'airgradient'"
                )
            )
            device_id = connection.scalar(
                text(
                    "INSERT INTO device (name, external_id, external_api_id, timezone) "
                    "VALUES ('Legacy AirGradient', 'legacy-1', :source_id, 'UTC') "
                    "RETURNING device_id"
                ),
                {"source_id": source_id},
            )
            celsius_alias_id = connection.scalar(
                text(
                    "INSERT INTO unit (code, symbol, name) "
                    "VALUES ('c', 'C', 'Legacy Celsius') RETURNING unit_id"
                )
            )
            percent_alias_id = connection.scalar(
                text(
                    "INSERT INTO unit (code, symbol, name) "
                    "VALUES ('%', '%', 'Legacy percent') RETURNING unit_id"
                )
            )
            temperature_alias_id = connection.scalar(
                text(
                    "INSERT INTO parameter (code, display_name, default_unit_id) "
                    "VALUES ('temp', 'Temp', :unit_id) RETURNING parameter_id"
                ),
                {"unit_id": celsius_alias_id},
            )
            humidity_alias_id = connection.scalar(
                text(
                    "INSERT INTO parameter (code, display_name, default_unit_id) "
                    "VALUES ('rh', 'RH', :unit_id) RETURNING parameter_id"
                ),
                {"unit_id": percent_alias_id},
            )
            connection.execute(
                text(
                    "INSERT INTO parameter_supported_unit (parameter_id, unit_id) "
                    "VALUES (:temperature_id, :celsius_id), (:humidity_id, :percent_id)"
                ),
                {
                    "temperature_id": temperature_alias_id,
                    "celsius_id": celsius_alias_id,
                    "humidity_id": humidity_alias_id,
                    "percent_id": percent_alias_id,
                },
            )
            temperature_sensor_id = connection.scalar(
                text(
                    "INSERT INTO sensor (device_id, parameter_id, unit_id, external_sensor_id) "
                    "VALUES (:device_id, :parameter_id, :unit_id, 'legacy-1:atmp') "
                    "RETURNING sensor_id"
                ),
                {
                    "device_id": device_id,
                    "parameter_id": temperature_alias_id,
                    "unit_id": celsius_alias_id,
                },
            )
            humidity_sensor_id = connection.scalar(
                text(
                    "INSERT INTO sensor (device_id, parameter_id, unit_id, external_sensor_id) "
                    "VALUES (:device_id, :parameter_id, :unit_id, 'legacy-1:rhum') "
                    "RETURNING sensor_id"
                ),
                {
                    "device_id": device_id,
                    "parameter_id": humidity_alias_id,
                    "unit_id": percent_alias_id,
                },
            )
            observed_at = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)
            temperature_measurement_id = connection.scalar(
                text(
                    "INSERT INTO measurement (sensor_id, value, observed_at) "
                    "VALUES (:sensor_id, 21.5, :observed_at) RETURNING measurement_id"
                ),
                {"sensor_id": temperature_sensor_id, "observed_at": observed_at},
            )
            connection.execute(
                text(
                    "INSERT INTO measurement (sensor_id, value, observed_at) "
                    "VALUES (:sensor_id, 45.0, :observed_at)"
                ),
                {"sensor_id": humidity_sensor_id, "observed_at": observed_at},
            )
            connection.execute(
                text(
                    "INSERT INTO measurement_qc_result "
                    "(measurement_id, parameter_id, aggregate_code, check_code, passed) "
                    "VALUES (:measurement_id, :parameter_id, 'raw', 'legacy_check', true)"
                ),
                {
                    "measurement_id": temperature_measurement_id,
                    "parameter_id": temperature_alias_id,
                },
            )
            rule_created_at = datetime(2026, 8, 30, 9, tzinfo=timezone.utc)
            rule_updated_at = datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
            baseline_rule_id = connection.scalar(
                text(
                    "INSERT INTO qc_rule "
                    "(check_code, parameter_id, enabled_override, "
                    "failure_action_override, settings, policy_unit_id, version, "
                    "state, draft_settings, created_at, updated_at) VALUES "
                    "('baseline_drift', :parameter_id, false, 'flag_for_review', "
                    "CAST('{\"lookback_hours\": 168, \"max_drift_per_day\": 5}' AS json), "
                    ":unit_id, 7, 'active', "
                    "CAST('{\"max_drift_per_day\": 4}' AS json), :created_at, :updated_at) "
                    "RETURNING qc_rule_id"
                ),
                {
                    "parameter_id": temperature_alias_id,
                    "unit_id": celsius_alias_id,
                    "created_at": rule_created_at,
                    "updated_at": rule_updated_at,
                },
            )

        upgrade(database_url, "head")

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT code FROM parameter WHERE code IN ('temp', 'rh')")
            ).all() == []
            assert connection.execute(
                text("SELECT code FROM unit WHERE code IN ('c', '%')")
            ).all() == []
            stream_rows = connection.execute(
                text(
                    "SELECT sensor.sensor_id, parameter.code, unit.code, measurement.value "
                    "FROM sensor JOIN parameter USING (parameter_id) JOIN unit USING (unit_id) "
                    "JOIN measurement USING (sensor_id) ORDER BY sensor.sensor_id"
                )
            ).all()
            assert stream_rows == [
                (temperature_sensor_id, "temperature", "celsius", 21.5),
                (humidity_sensor_id, "relative_humidity", "percent", 45.0),
            ]
            assert connection.scalar(
                text(
                    "SELECT parameter.code FROM measurement_qc_result "
                    "JOIN parameter USING (parameter_id) WHERE check_code = 'legacy_check'"
                )
            ) == "temperature"
            baseline_rule = connection.execute(
                text(
                    "SELECT qc_rule.qc_rule_id, parameter.code AS parameter_code, "
                    "unit.code AS unit_code, qc_rule.enabled_override, "
                    "qc_rule.failure_action_override, qc_rule.settings, qc_rule.version, "
                    "qc_rule.state, qc_rule.draft_settings, qc_rule.created_at, "
                    "qc_rule.updated_at FROM qc_rule "
                    "JOIN parameter USING (parameter_id) "
                    "JOIN unit ON unit.unit_id = qc_rule.policy_unit_id "
                    "WHERE qc_rule.check_code = 'baseline_drift'"
                )
            ).mappings().one()
            assert baseline_rule == {
                "qc_rule_id": baseline_rule_id,
                "parameter_code": "temperature",
                "unit_code": "celsius",
                "enabled_override": False,
                "failure_action_override": "flag_for_review",
                "settings": {"lookback_hours": 168, "max_drift_per_day": 5},
                "version": 7,
                "state": "active",
                "draft_settings": {"max_drift_per_day": 4},
                "created_at": rule_created_at,
                "updated_at": rule_updated_at,
            }
            assert connection.execute(
                text(
                    "SELECT expected_frequency_seconds, measurement_duration_seconds, "
                    "source_aggregation_duration_seconds, measurement_timestamp_semantics "
                    "FROM sensor ORDER BY sensor_id"
                )
            ).all() == [
                (60, 12, 12, "observation_instant"),
                (60, 12, 12, "observation_instant"),
            ]


def test_fresh_catalog_contains_every_airgradient_canonical_pair() -> None:
    with temporary_postgres_database("airgradient_catalog") as (database_url, engine):
        upgrade(database_url, "head")
        with engine.connect() as connection:
            pairs = set(
                connection.execute(
                    text(
                        "SELECT parameter.code, unit.code FROM parameter_supported_unit "
                        "JOIN parameter USING (parameter_id) JOIN unit USING (unit_id)"
                    )
                ).all()
            )
            assert {
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
            }.issubset(pairs)


def test_unknown_plugin_unit_scoped_rule_survives_alias_canonicalization() -> None:
    with temporary_postgres_database("airgradient_unknown_qc") as (database_url, engine):
        upgrade(database_url, "20260902_0017")
        with engine.begin() as connection:
            source_id = connection.scalar(
                text(
                    "SELECT external_api_id FROM external_api "
                    "WHERE provider_code = 'airgradient'"
                )
            )
            celsius_alias_id = connection.scalar(
                text(
                    "INSERT INTO unit (code, symbol, name) "
                    "VALUES ('c', 'C', 'Legacy Celsius') RETURNING unit_id"
                )
            )
            temperature_alias_id = connection.scalar(
                text(
                    "INSERT INTO parameter (code, display_name, default_unit_id) "
                    "VALUES ('temp', 'Temp', :unit_id) RETURNING parameter_id"
                ),
                {"unit_id": celsius_alias_id},
            )
            connection.execute(
                text(
                    "INSERT INTO parameter_supported_unit (parameter_id, unit_id) "
                    "VALUES (:parameter_id, :unit_id)"
                ),
                {"parameter_id": temperature_alias_id, "unit_id": celsius_alias_id},
            )
            rule_created_at = datetime(2026, 8, 31, 11, tzinfo=timezone.utc)
            rule_updated_at = datetime(2026, 9, 2, 11, tzinfo=timezone.utc)
            plugin_rule_id = connection.scalar(
                text(
                    "INSERT INTO qc_rule "
                    "(check_code, parameter_id, external_api_id, aggregate_code, "
                    "enabled_override, failure_action_override, settings, policy_unit_id, "
                    "version, state, draft_settings, created_at, updated_at) VALUES "
                    "('reference_threshold', :parameter_id, :source_id, 'raw', true, "
                    "'mark_invalid', CAST('{\"threshold\": 12.5}' AS json), :unit_id, "
                    "4, 'active', CAST('{\"threshold\": 13}' AS json), "
                    ":created_at, :updated_at) RETURNING qc_rule_id"
                ),
                {
                    "parameter_id": temperature_alias_id,
                    "source_id": source_id,
                    "unit_id": celsius_alias_id,
                    "created_at": rule_created_at,
                    "updated_at": rule_updated_at,
                },
            )

        upgrade(database_url, "head")

        with engine.connect() as connection:
            plugin_rule = connection.execute(
                text(
                    "SELECT qc_rule.qc_rule_id, parameter.code AS parameter_code, "
                    "unit.code AS unit_code, external_api.provider_code, "
                    "qc_rule.aggregate_code, qc_rule.enabled_override, "
                    "qc_rule.failure_action_override, qc_rule.settings, qc_rule.version, "
                    "qc_rule.state, qc_rule.draft_settings, qc_rule.created_at, "
                    "qc_rule.updated_at FROM qc_rule "
                    "JOIN parameter USING (parameter_id) "
                    "JOIN external_api USING (external_api_id) "
                    "JOIN unit ON unit.unit_id = qc_rule.policy_unit_id "
                    "WHERE qc_rule.qc_rule_id = :rule_id"
                ),
                {"rule_id": plugin_rule_id},
            ).mappings().one()
            assert plugin_rule == {
                "qc_rule_id": plugin_rule_id,
                "parameter_code": "temperature",
                "unit_code": "celsius",
                "provider_code": "airgradient",
                "aggregate_code": "raw",
                "enabled_override": True,
                "failure_action_override": "mark_invalid",
                "settings": {"threshold": 12.5},
                "version": 4,
                "state": "active",
                "draft_settings": {"threshold": 13},
                "created_at": rule_created_at,
                "updated_at": rule_updated_at,
            }


def test_qc_rule_merge_keeps_distinct_units_and_canonical_row_wins_duplicates() -> None:
    with temporary_postgres_database("airgradient_qc_identity") as (database_url, engine):
        upgrade(database_url, "20260902_0017")
        with engine.begin() as connection:
            celsius_id = connection.scalar(
                text("SELECT unit_id FROM unit WHERE code = 'celsius'")
            )
            kelvin_id = connection.scalar(
                text("SELECT unit_id FROM unit WHERE code = 'kelvin'")
            )
            celsius_alias_id = connection.scalar(
                text(
                    "INSERT INTO unit (code, symbol, name) "
                    "VALUES ('c', 'C', 'Legacy Celsius') RETURNING unit_id"
                )
            )
            canonical_temperature_id = connection.scalar(
                text(
                    "INSERT INTO parameter (code, display_name, default_unit_id) "
                    "VALUES ('temperature', 'Temperature', :unit_id) RETURNING parameter_id"
                ),
                {"unit_id": celsius_id},
            )
            temperature_alias_id = connection.scalar(
                text(
                    "INSERT INTO parameter (code, display_name, default_unit_id) "
                    "VALUES ('temp', 'Temp', :unit_id) RETURNING parameter_id"
                ),
                {"unit_id": celsius_alias_id},
            )
            connection.execute(
                text(
                    "INSERT INTO parameter_supported_unit (parameter_id, unit_id) VALUES "
                    "(:canonical_id, :celsius_id), (:canonical_id, :kelvin_id), "
                    "(:alias_id, :celsius_alias_id), (:alias_id, :kelvin_id)"
                ),
                {
                    "canonical_id": canonical_temperature_id,
                    "alias_id": temperature_alias_id,
                    "celsius_id": celsius_id,
                    "celsius_alias_id": celsius_alias_id,
                    "kelvin_id": kelvin_id,
                },
            )
            canonical_rule_id = connection.scalar(
                text(
                    "INSERT INTO qc_rule "
                    "(check_code, parameter_id, enabled_override, settings, policy_unit_id, "
                    "version) VALUES ('reference_threshold', :parameter_id, true, "
                    "CAST('{\"threshold\": 20}' AS json), :unit_id, 9) "
                    "RETURNING qc_rule_id"
                ),
                {"parameter_id": canonical_temperature_id, "unit_id": celsius_id},
            )
            duplicate_alias_rule_id = connection.scalar(
                text(
                    "INSERT INTO qc_rule "
                    "(check_code, parameter_id, enabled_override, settings, policy_unit_id, "
                    "version) VALUES ('reference_threshold', :parameter_id, false, "
                    "CAST('{\"threshold\": 99}' AS json), :unit_id, 2) "
                    "RETURNING qc_rule_id"
                ),
                {
                    "parameter_id": temperature_alias_id,
                    "unit_id": celsius_alias_id,
                },
            )
            kelvin_rule_id = connection.scalar(
                text(
                    "INSERT INTO qc_rule "
                    "(check_code, parameter_id, enabled_override, settings, policy_unit_id, "
                    "version) VALUES ('reference_threshold', :parameter_id, false, "
                    "CAST('{\"threshold\": 295}' AS json), :unit_id, 3) "
                    "RETURNING qc_rule_id"
                ),
                {"parameter_id": temperature_alias_id, "unit_id": kelvin_id},
            )

        upgrade(database_url, "head")

        with engine.connect() as connection:
            rules = connection.execute(
                text(
                    "SELECT qc_rule.qc_rule_id, parameter.code AS parameter_code, "
                    "unit.code AS unit_code, qc_rule.enabled_override, qc_rule.settings, "
                    "qc_rule.version FROM qc_rule JOIN parameter USING (parameter_id) "
                    "JOIN unit ON unit.unit_id = qc_rule.policy_unit_id "
                    "WHERE qc_rule.check_code = 'reference_threshold' "
                    "ORDER BY unit.code"
                )
            ).all()
            assert rules == [
                (
                    canonical_rule_id,
                    "temperature",
                    "celsius",
                    True,
                    {"threshold": 20},
                    9,
                ),
                (
                    kelvin_rule_id,
                    "temperature",
                    "kelvin",
                    False,
                    {"threshold": 295},
                    3,
                ),
            ]
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM qc_rule "
                    "WHERE qc_rule_id = :duplicate_rule_id"
                ),
                {"duplicate_rule_id": duplicate_alias_rule_id},
            ) == 0


def test_migration_does_not_classify_unit_scope_by_qc_check_code() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260903_0018_canonicalize_airgradient_measurements.py"
    )
    migration_source = migration_path.read_text(encoding="utf-8")

    assert "check_code IN (" not in migration_source
    assert "check_code NOT IN (" not in migration_source
    assert "canonical.policy_unit_id IS NOT DISTINCT FROM legacy.policy_unit_id" in (
        migration_source
    )
