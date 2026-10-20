from __future__ import annotations

import os

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from postgresql_test_support import (
    POSTGRES_TEST_URL_ENV,
    downgrade,
    temporary_postgres_database,
    upgrade,
)


def test_qc_policy_migration_upgrade_downgrade_and_constraints():
    if not os.environ.get(POSTGRES_TEST_URL_ENV):
        pytest.skip(f"Set {POSTGRES_TEST_URL_ENV} to run PostgreSQL migration tests")

    with temporary_postgres_database("qc_policy") as (database_url, engine):
        upgrade(database_url, "20260812_0008")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO qc_rule (check_code, enabled, params) "
                    "VALUES ('min_value', true, '{\"min\": 0}')"
                )
            )

        # Include the unit/plugin constraint refinements, but do not cross the
        # later irreversible Demo activation-state migration on downgrade.
        upgrade(database_url, "20260827_0016")
        inspector = inspect(engine)
        rule_columns = {column["name"] for column in inspector.get_columns("qc_rule")}
        assert {
            "external_api_id",
            "enabled_override",
            "failure_action_override",
            "settings",
            "policy_unit_id",
        }.issubset(rule_columns)
        result_columns = {
            column["name"]
            for column in inspector.get_columns("measurement_qc_result")
        }
        assert {
            "evaluation_status",
            "failure_action",
            "reason_code",
            "policy_snapshot",
            "policy_provenance",
        }.issubset(result_columns)
        assert "parameter_supported_unit" in inspector.get_table_names()

        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM qc_rule")) == 0
            parameter_id = connection.scalar(
                text("SELECT parameter_id FROM parameter ORDER BY parameter_id LIMIT 1")
            )
            unit_id = connection.scalar(
                text(
                    "SELECT default_unit_id FROM parameter "
                    "WHERE parameter_id = :parameter_id"
                ),
                {"parameter_id": parameter_id},
            )
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM parameter_supported_unit "
                    "WHERE parameter_id = :parameter_id AND unit_id = :unit_id"
                ),
                {"parameter_id": parameter_id, "unit_id": unit_id},
            ) == 1

        # Plugin metadata, rather than a database check-code list, determines
        # whether a rule requires a unit. The database only enforces uniqueness
        # separately for unitless and unit-scoped rule identities.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO qc_rule "
                    "(check_code, parameter_id, enabled_override) "
                    "VALUES ('reference_threshold', :parameter_id, true)"
                ),
                {"parameter_id": parameter_id},
            )
            connection.execute(
                text(
                    "INSERT INTO qc_rule "
                    "(check_code, parameter_id, enabled_override, settings, policy_unit_id) "
                    "VALUES ('third_party_unit_check', :parameter_id, true, "
                    "'{\"limit\": 25}', :unit_id)"
                ),
                {"parameter_id": parameter_id, "unit_id": unit_id},
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO qc_rule "
                        "(check_code, parameter_id, enabled_override, settings, policy_unit_id) "
                        "VALUES ('third_party_unit_check', :parameter_id, false, "
                        "'{\"limit\": 50}', :unit_id)"
                    ),
                    {"parameter_id": parameter_id, "unit_id": unit_id},
                )

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO qc_rule "
                    "(check_code, parameter_id, settings, policy_unit_id) "
                    "VALUES ('min_value', :parameter_id, '{\"min\": 0}', :unit_id)"
                ),
                {"parameter_id": parameter_id, "unit_id": unit_id},
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO qc_rule "
                        "(check_code, parameter_id, settings, policy_unit_id) "
                        "VALUES ('min_value', :parameter_id, '{\"min\": -1}', :unit_id)"
                    ),
                    {"parameter_id": parameter_id, "unit_id": unit_id},
                )

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO qc_rule "
                    "(check_code, parameter_id, enabled_override, settings, policy_unit_id) "
                    "VALUES ('baseline_drift', :parameter_id, true, '{}', :unit_id)"
                ),
                {"parameter_id": parameter_id, "unit_id": unit_id},
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO qc_rule "
                        "(check_code, parameter_id, enabled_override, settings, policy_unit_id) "
                        "VALUES ('baseline_drift', :parameter_id, false, '{}', :unit_id)"
                    ),
                    {"parameter_id": parameter_id, "unit_id": unit_id},
                )

        with engine.begin() as connection:
            connection.execute(text("DELETE FROM qc_rule"))
        downgrade(database_url, "20260812_0008")
        legacy_columns = {
            column["name"] for column in inspect(engine).get_columns("qc_rule")
        }
        assert "enabled" in legacy_columns
        assert "params" in legacy_columns
        assert "enabled_override" not in legacy_columns

        upgrade(database_url, "head")
        assert "enabled_override" in {
            column["name"] for column in inspect(engine).get_columns("qc_rule")
        }


def test_baseline_drift_default_change_preserves_existing_rule_state():
    if not os.environ.get(POSTGRES_TEST_URL_ENV):
        pytest.skip(f"Set {POSTGRES_TEST_URL_ENV} to run PostgreSQL migration tests")

    with temporary_postgres_database("baseline_default") as (database_url, engine):
        upgrade(database_url, "20260827_0014")
        with engine.begin() as connection:
            parameters = connection.execute(
                text(
                    "SELECT parameter_id, default_unit_id FROM parameter "
                    "ORDER BY parameter_id LIMIT 3"
                )
            ).all()
            assert len(parameters) == 3
            for (parameter_id, unit_id), enabled_override in zip(
                parameters,
                (None, True, False),
            ):
                connection.execute(
                    text(
                        "INSERT INTO qc_rule "
                        "(check_code, parameter_id, enabled_override, settings, policy_unit_id) "
                        "VALUES ('baseline_drift', :parameter_id, :enabled_override, '{}', :unit_id)"
                    ),
                    {
                        "parameter_id": parameter_id,
                        "enabled_override": enabled_override,
                        "unit_id": unit_id,
                    },
                )

        upgrade(database_url, "20260827_0015")
        with engine.connect() as connection:
            enabled_states = connection.execute(
                text(
                    "SELECT enabled_override FROM qc_rule "
                    "WHERE check_code = 'baseline_drift' ORDER BY parameter_id"
                )
            ).scalars().all()
        assert enabled_states == [True, True, False]

        downgrade(database_url, "20260827_0014")
        with engine.connect() as connection:
            enabled_states_after_downgrade = connection.execute(
                text(
                    "SELECT enabled_override FROM qc_rule "
                    "WHERE check_code = 'baseline_drift' ORDER BY parameter_id"
                )
            ).scalars().all()
        assert enabled_states_after_downgrade == [True, True, False]

        upgrade(database_url, "head")
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT enabled_override FROM qc_rule "
                "WHERE check_code = 'baseline_drift' ORDER BY parameter_id"
            )).scalars().all() == [True, True, False]
