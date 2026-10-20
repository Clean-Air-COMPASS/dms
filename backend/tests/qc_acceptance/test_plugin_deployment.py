from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import models
from api.routes.admin.plugins import list_plugins
from qaqc import discovery, registry
from qaqc.admin_policy import get_check_metadata
from qaqc.plugins import BUILT_IN_PLUGINS
from sources.openaq.openaq_upserts import upsert_measurement_with_policy_detailed
from .support import (
    ensure_catalog,
    ensure_source,
    measurement_qc_rows,
)


@pytest.fixture()
def preserved_plugin_registry():
    previous_registrations = tuple(registry.all_registrations().values())
    try:
        yield
    finally:
        registry.replace_all(previous_registrations)


def _built_in_registrations():
    return [
        registry.validate_plugin(plugin, origin="built_in")
        for plugin in BUILT_IN_PLUGINS
    ]


def _ingest(session, device, sensor, observed_at):
    measurement = models.Measurement(
        sensor_id=sensor.sensor_id,
        value=101.0,
        observed_at=observed_at,
    )
    result = upsert_measurement_with_policy_detailed(
        session,
        measurement,
        device=device,
        sensor=sensor,
    )
    session.flush()
    return measurement, result


@pytest.mark.qc_acceptance(
    id="plugin-unavailable-diagnostics-recovery",
    source="CompassAQ deployment plugin discovery",
    parameter="relative_humidity",
    qc_layer="deployment_plugin",
    expected=(
        "A missing expected check is explicit in the API and ingest evidence, then "
        "entry-point discovery restores normal evaluation"
    ),
)
def test_missing_maximum_plugin_is_visible_and_discovery_restores_evaluation(
    acceptance_session_factory,
    acceptance_evidence,
    preserved_plugin_registry,
):
    registry.replace_all(_built_in_registrations())

    maximum_metadata = next(
        item for item in get_check_metadata() if item["check_code"] == "max_value"
    )
    assert maximum_metadata["available"] is False

    Session = acceptance_session_factory
    with Session() as session:
        units, parameters, periods = ensure_catalog(session)
        source = ensure_source(session, "openaq", "OpenAQ")
        device = models.Device(
            name="Missing plugin sensor",
            external_id="missing-plugin-sensor",
            external_api_id=source.external_api_id,
        )
        session.add(device)
        session.flush()
        sensor = models.Sensor(
            device_id=device.device_id,
            parameter_id=parameters["rh"].parameter_id,
            unit_id=units["percent"].unit_id,
            aggregation_period_id=periods["2m"].aggregation_period_id,
            external_sensor_id="missing-plugin-sensor:rh",
        )
        session.add(sensor)
        session.flush()

        diagnostics = list_plugins(session)
        assert diagnostics["unavailable_checks"] == [
            {
                "check_code": "max_value",
                "display_name": "max_value",
                "reason_code": "plugin_unavailable",
                "configured_rule_count": 0,
            }
        ]

        observed_at = datetime.now(timezone.utc)
        unavailable_measurement, unavailable_result = _ingest(
            session, device, sensor, observed_at
        )
        unavailable_qc = measurement_qc_rows(
            session, unavailable_measurement.measurement_id
        )
        assert unavailable_result.qc["indeterminate"] == 1
        assert unavailable_measurement.is_valid is True
        assert unavailable_qc[0].check_code == "max_value"
        assert unavailable_qc[0].evaluation_status == "indeterminate"
        assert unavailable_qc[0].reason_code == "plugin_unavailable"

        discovery_report = discovery.load_plugins()
        registration = registry.get_registration("max_value")
        assert registration is not None
        assert registration.metadata.origin == "entry_point"
        assert registration.metadata.distribution == "compassaq-max-value"
        assert {item["name"] for item in discovery_report["entry_points"]} >= {
            "max_value"
        }
        assert list_plugins(session)["unavailable_checks"] == []

        restored_measurement, restored_result = _ingest(
            session, device, sensor, observed_at + timedelta(seconds=1)
        )
        restored_qc = measurement_qc_rows(
            session, restored_measurement.measurement_id
        )
        assert restored_result.qc["flagged"] == 1
        assert restored_measurement.is_valid is False
        assert restored_qc[0].evaluation_status == "failed"
        assert restored_qc[0].plugin_version == registration.metadata.version

        acceptance_evidence.update(
            {
                "unavailable_reason_code": unavailable_qc[0].reason_code,
                "unavailable_measurement_valid": unavailable_measurement.is_valid,
                "restored_origin": registration.metadata.origin,
                "restored_distribution": registration.metadata.distribution,
                "restored_measurement_valid": restored_measurement.is_valid,
            }
        )
