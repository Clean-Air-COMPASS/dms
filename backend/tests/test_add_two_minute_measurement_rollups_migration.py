from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "20260810_0005_add_two_minute_measurement_rollups.py"
)


class _MigrationOperations:
    def __init__(self, connection: sa.Connection):
        self.connection = connection

    def get_bind(self) -> sa.Connection:
        return self.connection


def _load_migration(connection: sa.Connection):
    operations = _MigrationOperations(connection)
    spec = importlib.util.spec_from_file_location("two_minute_rollup_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = operations
    return module


def test_upgrade_adds_only_pm_two_minute_rollups_and_is_idempotent() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text(
            "CREATE TABLE parameter (parameter_id INTEGER PRIMARY KEY, code VARCHAR(32) UNIQUE)"
        ))
        connection.execute(sa.text(
            "CREATE TABLE aggregation_period (aggregation_period_id INTEGER PRIMARY KEY, code VARCHAR(32) UNIQUE)"
        ))
        connection.execute(sa.text(
            "CREATE TABLE parameter_aggregation_rollup ("
            "parameter_id INTEGER NOT NULL, from_aggregation_period_id INTEGER NOT NULL, "
            "to_aggregation_period_id INTEGER NOT NULL, "
            "UNIQUE(parameter_id, from_aggregation_period_id, to_aggregation_period_id))"
        ))
        connection.execute(sa.text(
            "INSERT INTO parameter VALUES (1, 'pm25'), (2, 'pm10'), (3, 'o3')"
        ))
        connection.execute(sa.text(
            "INSERT INTO aggregation_period VALUES (1, '2m'), (2, '1h')"
        ))
        migration = _load_migration(connection)

        migration.upgrade()
        migration.upgrade()
        rows = connection.execute(sa.text(
            "SELECT parameter.code, source.code, target.code "
            "FROM parameter_aggregation_rollup AS rollup "
            "JOIN parameter ON parameter.parameter_id = rollup.parameter_id "
            "JOIN aggregation_period AS source ON source.aggregation_period_id = rollup.from_aggregation_period_id "
            "JOIN aggregation_period AS target ON target.aggregation_period_id = rollup.to_aggregation_period_id "
            "ORDER BY parameter.code"
        )).all()
        assert rows == [("pm10", "2m", "1h"), ("pm25", "2m", "1h")]

        migration.downgrade()
        assert connection.scalar(sa.text(
            "SELECT count(*) FROM parameter_aggregation_rollup"
        )) == 0
