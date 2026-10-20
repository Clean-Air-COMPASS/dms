from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.schema import CreateColumn


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "20260730_0004_add_measurement_frequency_metadata.py"
)


class _MigrationOperations:
    def __init__(self, connection: sa.Connection):
        self.connection = connection

    def get_bind(self) -> sa.Connection:
        return self.connection

    def add_column(self, table_name: str, column: sa.Column) -> None:
        column_ddl = str(
            CreateColumn(column).compile(dialect=self.connection.dialect)
        )
        self.connection.execute(
            sa.text(f"ALTER TABLE {table_name} ADD COLUMN {column_ddl}")
        )

    def drop_column(self, table_name: str, column_name: str) -> None:
        self.connection.execute(
            sa.text(f"ALTER TABLE {table_name} DROP COLUMN {column_name}")
        )


def _load_migration(connection: sa.Connection):
    operations = _MigrationOperations(connection)
    spec = importlib.util.spec_from_file_location(
        "measurement_frequency_metadata_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = operations
    return module


def _database() -> sa.Connection:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    connection = engine.connect()
    connection.execute(sa.text(
        "CREATE TABLE external_api ("
        "external_api_id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL)"
    ))
    connection.execute(sa.text(
        "CREATE TABLE device ("
        "device_id INTEGER PRIMARY KEY, external_api_id INTEGER)"
    ))
    connection.execute(sa.text(
        "CREATE TABLE parameter ("
        "parameter_id INTEGER PRIMARY KEY, code VARCHAR(32) NOT NULL)"
    ))
    connection.execute(sa.text(
        "CREATE TABLE aggregation_period ("
        "aggregation_period_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "code VARCHAR(32) NOT NULL UNIQUE, display_name VARCHAR(64) NOT NULL, "
        "duration_minutes INTEGER, is_rolling BOOLEAN NOT NULL DEFAULT 0, "
        "expected_interval VARCHAR(16))"
    ))
    connection.execute(sa.text(
        "CREATE TABLE sensor ("
        "sensor_id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, "
        "parameter_id INTEGER, aggregation_period_id INTEGER)"
    ))
    connection.execute(sa.text(
        "INSERT INTO external_api (external_api_id, name) VALUES "
        "(1, 'PurpleAir'), (2, 'Other Source')"
    ))
    connection.execute(sa.text(
        "INSERT INTO device (device_id, external_api_id) VALUES "
        "(1, 1), (2, 2)"
    ))
    connection.execute(sa.text(
        "INSERT INTO parameter (parameter_id, code) VALUES "
        "(1, 'pm25'), (2, 'pm10'), (3, 'o3')"
    ))
    connection.execute(sa.text(
        "INSERT INTO aggregation_period "
        "(aggregation_period_id, code, display_name, duration_minutes, "
        "is_rolling, expected_interval) "
        "VALUES (1, '1m', '1 Minute', 1, 0, '00:01:00')"
    ))
    connection.execute(sa.text(
        "INSERT INTO sensor "
        "(sensor_id, device_id, parameter_id, aggregation_period_id) VALUES "
        "(1, 1, 1, 1), (2, 1, 2, 1), (3, 1, 3, 1), (4, 2, 1, 1)"
    ))
    return connection


def test_upgrade_backfills_only_unambiguous_purpleair_pm_sensors() -> None:
    connection = _database()
    migration = _load_migration(connection)

    migration.upgrade()

    columns = {
        column["name"]: column
        for column in sa.inspect(connection).get_columns("sensor")
    }
    for column_name in migration.PURPLEAIR_METADATA:
        assert column_name in columns
        assert columns[column_name]["nullable"] is True

    rows = connection.execute(sa.text(
        "SELECT sensor_id, aggregation_period_id, expected_frequency_seconds, "
        "measurement_duration_seconds, "
        "source_aggregation_duration_seconds, "
        "measurement_timestamp_semantics, measurement_metadata_status, "
        "measurement_metadata_managed_by "
        "FROM sensor ORDER BY sensor_id"
    )).mappings().all()
    assert len(rows) == 4

    for row in rows[:2]:
        assert row["aggregation_period_id"] == 2
        assert row["expected_frequency_seconds"] == 120
        assert row["measurement_duration_seconds"] == 120
        assert row["source_aggregation_duration_seconds"] == 120
        assert row["measurement_timestamp_semantics"] == "provider_received_at"
        assert row["measurement_metadata_status"] == "provider_documented"
        assert row["measurement_metadata_managed_by"] == "purpleair_importer"

    for row in rows[2:]:
        assert row["aggregation_period_id"] == 1
        assert row["expected_frequency_seconds"] is None
        assert row["measurement_duration_seconds"] is None
        assert row["source_aggregation_duration_seconds"] is None
        assert row["measurement_timestamp_semantics"] is None
        assert row["measurement_metadata_status"] is None
        assert row["measurement_metadata_managed_by"] is None


def test_downgrade_removes_measurement_metadata_columns() -> None:
    connection = _database()
    migration = _load_migration(connection)
    migration.upgrade()

    migration.downgrade()

    column_names = {
        column["name"]
        for column in sa.inspect(connection).get_columns("sensor")
    }
    assert column_names == {
        "sensor_id",
        "device_id",
        "parameter_id",
        "aggregation_period_id",
    }
    purpleair_aggregation_periods = connection.execute(sa.text(
        "SELECT aggregation_period_id FROM sensor "
        "WHERE sensor_id IN (1, 2) ORDER BY sensor_id"
    )).scalars().all()
    assert purpleair_aggregation_periods == [1, 1]
