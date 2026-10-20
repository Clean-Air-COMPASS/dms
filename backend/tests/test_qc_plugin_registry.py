from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy import select

import models
from db import SessionLocal
from qaqc import discovery, registry
from qaqc.pipeline import run_ingest_detailed
from qaqc.policy_defaults import FLAG_FOR_REVIEW
from qaqc.types import QCDecision, QCRecord


class FixturePlugin:
    name = "test_check"
    version = "2.1.0"
    qc_api = 1
    required_access = "api-only"
    display_name = "Test check"
    description = "Short test check description"
    long_description = "A deterministic plugin used to validate discovery."
    param_schema = {
        "limit": {
            "type": "number",
            "label": "Limit",
            "help": "Threshold used by the test check",
            "required": True,
        }
    }
    unit_settings = ()

    def apply(self, records, context):
        return [QCDecision(True, [], "info") for _ in records]


@dataclass
class FakeDistribution:
    name: str = "compassaq-test-plugin"


class FakeEntryPoint:
    def __init__(self, name: str, value: str, loaded):
        self.name = name
        self.value = value
        self.dist = FakeDistribution()
        self._loaded = loaded

    def load(self):
        if isinstance(self._loaded, Exception):
            raise self._loaded
        return self._loaded


@pytest.fixture()
def preserved_plugin_registry():
    previous = tuple(registry.all_registrations().values())
    try:
        yield
    finally:
        registry.replace_all(previous)


def test_registry_validates_metadata_and_rejects_silent_replacement(
    preserved_plugin_registry,
):
    plugin = FixturePlugin()
    registry.register(plugin)
    assert registry.get("test_check") is plugin

    with pytest.raises(registry.PluginRegistrationError) as duplicate_error:
        registry.register(FixturePlugin())
    assert duplicate_error.value.reason_code == "duplicate_plugin"
    assert registry.get("test_check") is plugin

    invalid = FixturePlugin()
    invalid.qc_api = 99
    invalid.name = "unsupported_api_check"
    with pytest.raises(registry.PluginRegistrationError) as api_error:
        registry.register(invalid)
    assert api_error.value.reason_code == "unsupported_plugin_api"

    invalid_schema = FixturePlugin()
    invalid_schema.name = "invalid_schema_check"
    invalid_schema.param_schema = {"limit": {"type": "mystery"}}
    with pytest.raises(registry.PluginRegistrationError) as schema_error:
        registry.register(invalid_schema)
    assert schema_error.value.reason_code == "invalid_parameter_schema"

    invalid_overview = FixturePlugin()
    invalid_overview.name = "invalid_overview_check"
    invalid_overview.overview = {"summary_setting": "missing"}
    with pytest.raises(registry.PluginRegistrationError) as overview_error:
        registry.register(invalid_overview)
    assert overview_error.value.reason_code == "invalid_overview_metadata"


def test_failed_atomic_replacement_keeps_current_registry(
    preserved_plugin_registry,
):
    original = registry.all_registrations()
    registration = registry.validate_plugin(FixturePlugin(), origin="runtime")

    with pytest.raises(registry.PluginRegistrationError):
        registry.replace_all([registration, registration])

    assert registry.all_registrations() == original


def test_discovery_accepts_valid_entry_point_and_rejects_collisions_and_write_access(
    monkeypatch,
    preserved_plugin_registry,
):
    valid_plugin = FixturePlugin()

    duplicate = FixturePlugin()
    duplicate.name = "min_value"

    write_plugin = FixturePlugin()
    write_plugin.name = "write_check"
    write_plugin.required_access = "db-write"

    bad_api = FixturePlugin()
    bad_api.name = "bad_api_check"
    bad_api.qc_api = 2

    side_effect_plugin = FixturePlugin()
    side_effect_plugin.name = "side_effect_check"

    def side_effect_factory():
        registry.register(side_effect_plugin)
        return side_effect_plugin

    monkeypatch.setattr(
        discovery,
        "_installed_entry_points",
        lambda: [
            FakeEntryPoint("valid", "package:plugin", FixturePlugin),
            FakeEntryPoint("duplicate", "package:duplicate", duplicate),
            FakeEntryPoint("write", "package:write", write_plugin),
            FakeEntryPoint("bad", "package:bad", bad_api),
            FakeEntryPoint("side_effect", "package:side_effect", side_effect_factory),
            FakeEntryPoint("broken", "package:broken", RuntimeError("boom")),
        ],
    )

    report = discovery.load_plugins(approve_write=False)

    assert registry.get(valid_plugin.name) is not None
    assert registry.get("min_value") is not duplicate
    assert registry.get("write_check") is None
    assert {item["reason_code"] for item in report["rejected"]} == {
        "duplicate_plugin",
        "db_write_not_approved",
        "unsupported_plugin_api",
        "side_effect_registration",
    }
    assert report["failed"][0]["reason_code"] == "plugin_load_failed"
    assert {item["name"] for item in report["built_in"]} == {
        "min_value",
        "baseline_drift",
    }
    assert report["entry_points"][0]["origin"] == "entry_point"
    assert report["entry_points"][0]["distribution"] == "compassaq-test-plugin"


def test_db_write_plugin_requires_explicit_process_configuration(
    monkeypatch,
    preserved_plugin_registry,
):
    write_plugin = FixturePlugin()
    write_plugin.name = "write_check"
    write_plugin.required_access = "db-write"
    monkeypatch.setattr(
        discovery,
        "_installed_entry_points",
        lambda: [FakeEntryPoint("write", "package:write", write_plugin)],
    )

    report = discovery.load_plugins(approve_write=True)

    assert report["db_write_plugins_allowed"] is True
    assert registry.get("write_check") is write_plugin


def _pipeline_context(
    session,
    plugin: FixturePlugin,
    *,
    sensor_unit_code: str = "ug_m3",
    policy_unit_code: str | None = None,
) -> tuple[models.Sensor, QCRecord]:
    suffix = uuid.uuid4().hex
    unit = session.scalar(
        select(models.Unit).where(models.Unit.code == sensor_unit_code)
    )
    if unit is None:
        unit = models.Unit(
            code=sensor_unit_code,
            symbol=sensor_unit_code,
            name=f"Test {sensor_unit_code}",
        )
        session.add(unit)
        session.flush()
    policy_unit = None
    if policy_unit_code is not None:
        policy_unit = session.scalar(
            select(models.Unit).where(models.Unit.code == policy_unit_code)
        )
        if policy_unit is None:
            policy_unit = models.Unit(
                code=policy_unit_code,
                symbol=policy_unit_code,
                name=f"Test {policy_unit_code}",
            )
            session.add(policy_unit)
            session.flush()
    parameter = models.Parameter(
        code=f"plugin_{suffix[:16]}",
        display_name="Plugin test parameter",
        default_unit_id=unit.unit_id,
    )
    source = models.ExternalAPI(
        provider_code=f"plugin-{suffix}",
        name=f"Plugin source {suffix}",
        params={},
    )
    session.add_all([parameter, source])
    session.flush()
    device = models.Device(
        name=f"Plugin device {suffix}",
        external_id=f"device-{suffix}",
        external_api_id=source.external_api_id,
    )
    session.add(device)
    session.flush()
    sensor = models.Sensor(
        device_id=device.device_id,
        parameter_id=parameter.parameter_id,
        unit_id=unit.unit_id,
        external_sensor_id=f"sensor-{suffix}",
    )
    session.add(sensor)
    session.flush()
    session.add(
        models.QCRule(
            check_code=plugin.name,
            sensor_id=sensor.sensor_id,
            enabled_override=True,
            failure_action_override=FLAG_FOR_REVIEW,
            settings={"limit": 1},
            policy_unit_id=(policy_unit.unit_id if policy_unit is not None else None),
        )
    )
    session.flush()
    return sensor, QCRecord(
        sensor_id=sensor.sensor_id,
        parameter_id=parameter.parameter_id,
        value=2.0,
        unit_id=unit.unit_id,
        observed_at=datetime.now(timezone.utc),
    )


def test_pipeline_limits_database_context_by_declared_access(
    preserved_plugin_registry,
):
    class ContextPlugin(FixturePlugin):
        name = "context_check"

        def __init__(self):
            self.received_session = None

        def apply(self, records, context):
            self.received_session = context.get("session")
            return super().apply(records, context)

    api_only_plugin = ContextPlugin()
    registry.register(api_only_plugin)
    with SessionLocal() as session:
        _, record = _pipeline_context(session, api_only_plugin)
        result = run_ingest_detailed([record], {"session": session})
        assert result["per_plugin"][api_only_plugin.name][0].is_valid is True
        assert api_only_plugin.received_session is None

    registry.replace_all(
        registration
        for name, registration in registry.all_registrations().items()
        if name != api_only_plugin.name
    )
    db_read_plugin = ContextPlugin()
    db_read_plugin.name = "db_read_check"
    db_read_plugin.required_access = "db-read"
    registry.register(db_read_plugin)
    with SessionLocal() as session:
        _, record = _pipeline_context(session, db_read_plugin)
        result = run_ingest_detailed([record], {"session": session})
        assert result["per_plugin"][db_read_plugin.name][0].is_valid is True
        assert db_read_plugin.received_session is session


def test_malformed_plugin_output_becomes_indeterminate(
    preserved_plugin_registry,
):
    class MalformedPlugin(FixturePlugin):
        name = "malformed_check"

        def apply(self, records, context):
            return [{"is_valid": True}]

    plugin = MalformedPlugin()
    registry.register(plugin)
    with SessionLocal() as session:
        _, record = _pipeline_context(session, plugin)
        result = run_ingest_detailed([record], {"session": session})

    decision = result["per_plugin"][plugin.name][0]
    assert decision.is_valid is None
    assert decision.patch == {"reason_code": "invalid_plugin_result"}
    assert decision.plugin_error["plugin"] == plugin.name


def test_declared_unit_settings_use_the_authoritative_safe_conversion(
    preserved_plugin_registry,
):
    class UnitPlugin(FixturePlugin):
        name = "unit_contract_check"
        unit_settings = ("limit",)

        def __init__(self):
            self.evaluation_limit = None

        def apply(self, records, context):
            self.evaluation_limit = context["effective_policies"][0].evaluation_settings[
                "limit"
            ]
            return super().apply(records, context)

    plugin = UnitPlugin()
    registry.register(plugin)
    with SessionLocal() as session:
        _, record = _pipeline_context(
            session,
            plugin,
            sensor_unit_code="mg_m3",
            policy_unit_code="ug_m3",
        )
        result = run_ingest_detailed([record], {"session": session})

    assert result["per_plugin"][plugin.name][0].is_valid is True
    assert plugin.evaluation_limit == 0.001
    policy = result["policies"][plugin.name][0]
    assert policy.unit_conversion["status"] == "converted"
    assert policy.unit_conversion["factor"] == 0.001
