"""Provision clearly synthetic local-development data for the CSV browser test.

Run inside the local development API container. Credentials go only to the
requested fixture file, never stdout. No external provider calls or email are used.
The single synthetic baseline uses the isolated QA CSV upload key.
"""

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import secrets
import uuid

import httpx
from sqlalchemy import select

from db import SessionLocal
import models
from services.auth import hash_password
from services.device_locations import set_device_location


def create_fixture(path: Path):
    suffix = uuid.uuid4().hex[:8]
    password = secrets.token_urlsafe(28)
    with SessionLocal() as session:
        administrator = models.User(
            user_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            email=f"synthetic-csv-qa-{suffix}@example.com",
            first_name="Synthetic CSV",
            last_name="QA",
            password_hash=hash_password(password),
            is_active=True,
            preferred_language_code="en",
        )
        administrator.roles.append(
            session.scalar(select(models.Role).where(models.Role.name == "admin"))
        )
        session.add(administrator)
        source = models.ExternalAPI(
            name=f"Synthetic CSV acceptance {suffix}", params={}
        )
        session.add(source)
        session.flush()
        parameter = session.scalar(
            select(models.Parameter).where(models.Parameter.code == "pm25")
        )
        unit = session.scalar(select(models.Unit).where(models.Unit.code == "ug_m3"))
        period = session.scalar(
            select(models.AggregationPeriod).where(
                models.AggregationPeriod.code == "2m"
            )
        )
        device = models.Device(
            name=source.name,
            external_id=f"synthetic-csv-device-{suffix}",
            external_api_id=source.external_api_id,
            timezone="UTC",
            allow_updates=models.UpdatePolicy.DENY,
        )
        session.add(device)
        session.flush()
        set_device_location(session, device, latitude=34.12, longitude=-118.32)
        sensors = []
        for name, action in [
            ("flag", "flag_for_review"),
            ("invalid", "mark_invalid"),
            ("drift", "flag_for_review"),
        ]:
            sensor = models.Sensor(
                device_id=device.device_id,
                parameter_id=parameter.parameter_id,
                unit_id=unit.unit_id,
                aggregation_period_id=period.aggregation_period_id,
                external_sensor_id=f"synthetic-{name}-{suffix}",
                allow_updates=models.UpdatePolicy.INHERIT,
                expected_frequency_seconds=120,
                measurement_duration_seconds=120,
                source_aggregation_duration_seconds=120,
                measurement_timestamp_semantics="interval_start",
                measurement_metadata_status="provider_documented",
                measurement_metadata_managed_by="synthetic_acceptance_fixture",
            )
            session.add(sensor)
            session.flush()
            session.add(
                models.QCRule(
                    check_code="max_value",
                    sensor_id=sensor.sensor_id,
                    policy_unit_id=unit.unit_id,
                    failure_action_override=action,
                )
            )
            if name == "drift":
                session.add(
                    models.QCRule(
                        check_code="baseline_drift",
                        sensor_id=sensor.sensor_id,
                        policy_unit_id=unit.unit_id,
                        enabled_override=True,
                        settings={
                            "lookback_hours": 192,
                            "min_samples": 8,
                            "baseline_quantile": 0.1,
                            "max_drift_per_day": 5,
                            "direction": "both",
                        },
                    )
                )
            sensors.append({"id": sensor.sensor_id, "name": name})
        session.commit()
        fixture = {
            "email": administrator.email,
            "password": password,
            "user_id": str(administrator.user_id),
            "source_id": source.external_api_id,
            "device_id": device.device_id,
            "device_name": device.name,
            "external_device_id": device.external_id,
            "sensors": sensors,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fixture, indent=2), encoding="utf-8")

    csv_upload_key = os.environ.get("COMPASSAQ_CSV_UPLOAD_API_KEY", "").strip()
    if not csv_upload_key:
        raise RuntimeError("COMPASSAQ_CSV_UPLOAD_API_KEY is required for the QA baseline observation")
    baseline_observed_at = (datetime.now(timezone.utc) - timedelta(minutes=2)).replace(
        second=0, microsecond=0
    )
    baseline_csv = (
        "internalsensorid,datetime,value\n"
        f"{sensors[0]['id']},{baseline_observed_at.isoformat()},12.345678901\n"
    )
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
        response = client.post(
            "/ingest/upload-csv",
            headers={"X-API-Key": csv_upload_key},
            files={"file": ("restart-baseline.csv", baseline_csv, "text/csv")},
        )
        response.raise_for_status()
        result = response.json()
    if result.get("inserted_records") != 1 or result.get("failed_records") != 0:
        raise RuntimeError("The QA baseline CSV did not insert exactly one measurement")
    fixture["baseline"] = {
        "sensor_id": sensors[0]["id"],
        "observed_at": baseline_observed_at.isoformat(),
        "value": 12.345678901,
    }
    path.write_text(json.dumps(fixture, indent=2), encoding="utf-8")
    print(f"Synthetic CSV acceptance fixture written to {path}")


def cleanup_fixture(path: Path):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    with SessionLocal() as session:
        device = session.get(models.Device, fixture["device_id"])
        source = session.get(models.ExternalAPI, fixture["source_id"])
        administrator = session.get(models.User, uuid.UUID(fixture["user_id"]))
        if device and (
            device.name != fixture["device_name"]
            or not device.name.startswith("Synthetic CSV acceptance ")
        ):
            raise ValueError(
                "Refusing to remove a device that does not match the synthetic fixture"
            )
        if source and source.name != fixture["device_name"]:
            raise ValueError(
                "Refusing to remove a source that does not match the synthetic fixture"
            )
        if administrator and (
            administrator.email != fixture["email"]
            or not administrator.email.startswith("synthetic-csv-qa-")
        ):
            raise ValueError(
                "Refusing to remove a user that does not match the synthetic fixture"
            )
        # Database FK cascades remove only these fixture measurements, sensors,
        # and policies. Events retain their saved actor names and summaries.
        for record in (device, source, administrator):
            if record:
                session.delete(record)
        session.commit()
    print("Synthetic CSV acceptance fixture removed; audit Events retained")


if __name__ == "__main__":
    if os.environ.get("COMPASSAQ_ENV") != "development":
        raise SystemExit("CSV browser fixtures are restricted to local development")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("/tmp/csv-acceptance-fixture.json")
    )
    parser.add_argument("--cleanup", action="store_true")
    arguments = parser.parse_args()
    if arguments.cleanup:
        cleanup_fixture(arguments.output)
    else:
        create_fixture(arguments.output)
