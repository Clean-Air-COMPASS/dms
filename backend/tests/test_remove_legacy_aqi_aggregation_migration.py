from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "20260729_0002_remove_legacy_aqi_aggregation.py"
)


class _MigrationOperations:
    def __init__(self, connection: sa.Connection):
        self.connection = connection

    def get_bind(self) -> sa.Connection:
        return self.connection


def _load_migration(connection: sa.Connection):
    operations = _MigrationOperations(connection)
    spec = importlib.util.spec_from_file_location("legacy_aqi_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = operations
    return module


def _database(*, include_legacy_lookup: bool = True) -> sa.Connection:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    connection = engine.connect()
    connection.execute(sa.text(
        "CREATE TABLE aggregation_period ("
        "aggregation_period_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "code VARCHAR(64) NOT NULL UNIQUE, display_name VARCHAR(120) NOT NULL, "
        "duration_minutes INTEGER, is_rolling BOOLEAN NOT NULL DEFAULT 0, "
        "expected_interval VARCHAR(16))"
    ))
    connection.execute(sa.text(
        "CREATE TABLE parameter (parameter_id INTEGER PRIMARY KEY, code VARCHAR(32) UNIQUE)"
    ))
    connection.execute(sa.text(
        "CREATE TABLE sensor (sensor_id INTEGER PRIMARY KEY, aggregation_period_id INTEGER)"
    ))
    connection.execute(sa.text(
        "CREATE TABLE parameter_aggregation_rule ("
        "parameter_aggregation_rule_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "parameter_id INTEGER NOT NULL, aggregation_period_id INTEGER NOT NULL, "
        "rounding_method VARCHAR(16), truncation_method VARCHAR(16), "
        "UNIQUE(parameter_id, aggregation_period_id))"
    ))
    for parameter_id, code in enumerate(("pm25", "pm10", "o3", "co", "no2", "so2"), start=1):
        connection.execute(
            sa.text("INSERT INTO parameter (parameter_id, code) VALUES (:id, :code)"),
            {"id": parameter_id, "code": code},
        )
    if include_legacy_lookup:
        connection.execute(sa.text(
            "INSERT INTO aggregation_period "
            "(code, display_name, duration_minutes, is_rolling, expected_interval) "
            "VALUES ('aqi', 'AQI', 60, 0, '01:00:00')"
        ))
        connection.execute(sa.text(
            "INSERT INTO parameter_aggregation_rule "
            "(parameter_id, aggregation_period_id, rounding_method, truncation_method) "
            "SELECT parameter_id, 1, 'round', 'none' FROM parameter"
        ))
    return connection


def test_upgrade_removes_lookup_and_downgrade_restores_rules_without_duplicates() -> None:
    connection = _database()
    migration = _load_migration(connection)

    migration.upgrade()
    assert connection.scalar(sa.text(
        "SELECT count(*) FROM aggregation_period WHERE code = 'aqi'"
    )) == 0
    assert connection.scalar(sa.text(
        "SELECT count(*) FROM parameter_aggregation_rule"
    )) == 0

    migration.downgrade()
    assert connection.scalar(sa.text(
        "SELECT count(*) FROM aggregation_period WHERE code = 'aqi'"
    )) == 1
    assert connection.scalar(sa.text(
        "SELECT count(*) FROM parameter_aggregation_rule"
    )) == 6

    migration.upgrade()
    assert connection.scalar(sa.text(
        "SELECT count(*) FROM aggregation_period WHERE code = 'aqi'"
    )) == 0
    assert connection.scalar(sa.text(
        "SELECT count(*) FROM parameter_aggregation_rule"
    )) == 0


def test_upgrade_is_safe_when_lookup_is_already_absent() -> None:
    connection = _database(include_legacy_lookup=False)
    _load_migration(connection).upgrade()
    assert connection.scalar(sa.text("SELECT count(*) FROM aggregation_period")) == 0


def test_upgrade_refuses_to_remove_a_sensor_referenced_lookup() -> None:
    connection = _database()
    connection.execute(sa.text(
        "INSERT INTO sensor (sensor_id, aggregation_period_id) VALUES (1, 1)"
    ))
    with pytest.raises(RuntimeError, match="sensor streams still reference"):
        _load_migration(connection).upgrade()
    assert connection.scalar(sa.text(
        "SELECT count(*) FROM aggregation_period WHERE code = 'aqi'"
    )) == 1
    assert connection.scalar(sa.text(
        "SELECT count(*) FROM parameter_aggregation_rule"
    )) == 6
