"""Seed DEV-004 only in its disposable PostgreSQL database, never a deployment.

Supply one UTC evaluation instant explicitly. Stored observations are retained
unchanged across before/after API and browser checks.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import make_url

from db import DATABASE_URL, SessionLocal
import models
from services.auth import hash_password
from services.device_locations import set_device_location
from services.system_settings import get_or_create_system_settings


def seed(evaluation_time, output):
    url = make_url(DATABASE_URL)
    if (os.environ.get("COMPASSAQ_DEV004_QA") != "1" or url.database != "dev004_qa"
            or url.host != "db" or url.username != "dev004"):
        raise RuntimeError("Requires COMPASSAQ_DEV004_QA=1 and the dedicated dev004_qa PostgreSQL database")
    if evaluation_time.tzinfo is None:
        raise ValueError("An explicit UTC offset is required")
    evaluation_time = evaluation_time.astimezone(timezone.utc)
    with SessionLocal() as session:
        if session.scalar(select(models.Sensor).where(models.Sensor.external_sensor_id == "SYNTHETIC-DEV004-hour")):
            raise RuntimeError("Fixture already exists; preserve the original evidence and observations")
        settings = get_or_create_system_settings(session)
        settings.is_system_setup_complete = True
        role = session.scalar(select(models.Role).where(models.Role.name == "analyst"))
        user = models.User(user_id=uuid4(), org_id=uuid4(), email="synthetic.dev004@example.com",
                           is_active=True, password_hash=hash_password("Synthetic-DEV004-QA-only-2026!"))
        session.add(user)
        session.flush()
        session.add(models.UserRole(user_id=user.user_id, role_id=role.role_id))
        parameter = session.scalar(select(models.Parameter).where(models.Parameter.code == "pm25"))
        source = models.ExternalAPI(name="SYNTHETIC DEV-004", enabled=False, params={})
        session.add(source)
        session.flush()
        fixture = {"evaluation_time": evaluation_time.isoformat(), "streams": {}}
        for name, code, longitude in [("hour", "1h", -118.25), ("sparse", "1m", -118.15)]:
            period = session.scalar(select(models.AggregationPeriod).where(models.AggregationPeriod.code == code))
            device = models.Device(name=f"SYNTHETIC DEV-004 {name}", external_api_id=source.external_api_id, timezone="UTC")
            session.add(device)
            session.flush()
            set_device_location(session, device, latitude=34.05, longitude=longitude)
            sensor = models.Sensor(device_id=device.device_id, parameter_id=parameter.parameter_id,
                unit_id=parameter.default_unit_id, aggregation_period_id=period.aggregation_period_id,
                external_sensor_id=f"SYNTHETIC-DEV004-{name}", expected_frequency_seconds=period.duration_minutes * 60,
                measurement_duration_seconds=period.duration_minutes * 60, measurement_timestamp_semantics="instant")
            session.add(sensor)
            session.flush()
            if name == "hour":
                inputs = [(evaluation_time + timedelta(hours=index), 50 + index / 10, index != -10)
                          for index in range(-25, 289)]
            else:
                inputs = [(evaluation_time - timedelta(hours=23), 10.123456789, True),
                          (evaluation_time - timedelta(hours=22), 14, True),
                          (evaluation_time - timedelta(hours=1), 20, False),
                          (evaluation_time, 30, True),
                          (evaluation_time + timedelta(seconds=1), 999, True),
                          (evaluation_time + timedelta(days=12), 9999, True)]
            observations = []
            for index, (when, value, valid) in enumerate(inputs):
                measurement = models.Measurement(sensor_id=sensor.sensor_id, observed_at=when, value=value, is_valid=valid)
                session.add(measurement)
                session.flush()
                if not valid or (name == "sparse" and index == 1):
                    session.add(models.MeasurementQCResult(measurement_id=measurement.measurement_id,
                        aggregate_code=code, check_code="max_value", passed=False, evaluation_status="failed",
                        failure_action="flag_for_review" if valid else "mark_invalid", reason_code="above_maximum",
                        severity="warning", message="Synthetic historical QC outcome"))
                observations.append({"measurement_id": measurement.measurement_id, "timestamp": when.isoformat(), "value": value, "is_valid": valid})
            fixture["streams"][name] = {"sensor_id": sensor.sensor_id, "device_id": device.device_id,
                                        "aggregation": code, "observations": observations}
        session.commit()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(fixture, indent=2), encoding="utf-8")
    print(json.dumps({"evaluation_time": fixture["evaluation_time"],
                      "sensor_ids": [stream["sensor_id"] for stream in fixture["streams"].values()]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-time", type=datetime.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    seed(args.evaluation_time, args.output)
