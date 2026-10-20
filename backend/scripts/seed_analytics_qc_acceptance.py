"""Opt-in synthetic Analytics fixtures; never modifies existing measurements or policies.

Run inside the local API container. The explicit synthetic device can be removed
through normal administration after acceptance. This is not historical re-QC.
"""
from datetime import datetime, timedelta, timezone
import json
from sqlalchemy import select
from db import SessionLocal
from models import Device, Sensor, Parameter, Unit, AggregationPeriod, Measurement, MeasurementQCResult, ExternalAPI


def seed():
    with SessionLocal() as session:
        name = "Synthetic Analytics QC acceptance v2"
        device = session.scalar(select(Device).where(Device.name == name))
        if device:
            sensor = session.scalar(select(Sensor).where(Sensor.device_id == device.device_id))
            return sensor.sensor_id
        parameter = session.scalar(select(Parameter).where(Parameter.code == "pm25"))
        unit = session.scalar(select(Unit).where(Unit.code == "ug_m3"))
        period = session.scalar(select(AggregationPeriod).where(AggregationPeriod.code == "2m"))
        source = ExternalAPI(name=name, provider_code="synthetic-analytics-qc-v2", enabled=False, params={})
        session.add(source)
        session.flush()
        device = Device(name=name, timezone="UTC", external_api_id=source.external_api_id)
        session.add(device)
        session.flush()
        sensor = Sensor(device_id=device.device_id, parameter_id=parameter.parameter_id,
                        unit_id=unit.unit_id, aggregation_period_id=period.aggregation_period_id,
                        expected_frequency_seconds=120, external_sensor_id="synthetic-analytics-qc")
        session.add(sensor)
        session.flush()
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        for index in range(3000):
            # All seven cases are represented in the first hour, then a dense series.
            invalid = index in (2, 4)
            measurement = Measurement(sensor_id=sensor.sensor_id, observed_at=start + timedelta(minutes=2*index),
                                      value=80 if invalid else 38.2 if index == 1 else 12 + index % 10,
                                      is_valid=not invalid)
            session.add(measurement)
            session.flush()
            checks = []
            if index in (1, 2, 4, 1000, 2000):
                checks.append(("max_value", "failed", "mark_invalid" if invalid else "flag_for_review"))
            if index in (3, 4):
                checks.append(("baseline_drift", "indeterminate", "flag_for_review"))
            if index == 4:
                checks.append(("min_value", "failed", "mark_invalid"))
            for code, status, action in checks:
                settings = ({"max": 35} if code == "max_value" else {"min": 100} if code == "min_value"
                            else {"lookback_hours": 168, "min_samples": 72})
                provenance = {f"settings.{key}": {"layer": "sensor_override", "rule_version": 7} for key in settings}
                session.add(MeasurementQCResult(measurement_id=measurement.measurement_id,
                    parameter_id=parameter.parameter_id, aggregate_code="2m", check_code=code,
                    passed=False if status == "failed" else None, evaluation_status=status,
                    failure_action=action, severity="warning", rule_source="sensor_override",
                    message=("Synthetic recorded maximum exceeded." if code == "max_value" else
                             "Synthetic recorded minimum not reached." if code == "min_value" else
                             "Synthetic insufficient history for baseline evaluation."),
                    reason_code="above_maximum" if code == "max_value" else "below_minimum" if code == "min_value" else "insufficient_history",
                    params_snapshot=settings, policy_provenance=provenance,
                    policy_snapshot={"configured_settings": settings, "evaluation_settings": settings,
                                     "evaluation_unit_code": "ug_m3", "default_profile_version": "synthetic-historical-1"},
                    plugin_version="1.0.0", qc_version="synthetic-historical-1", stage="ingest"))
        session.commit()
        return sensor.sensor_id


if __name__ == "__main__":
    print(json.dumps({"sensor_id": seed(), "start": "2026-10-01T00:00:00Z", "end": "2026-10-06T00:00:00Z"}))
