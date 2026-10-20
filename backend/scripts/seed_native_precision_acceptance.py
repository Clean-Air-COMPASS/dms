"""Opt-in DEF-004 fixture for a disposable precision_qa database and real API.

Run after migrations and API startup, with COMPASSAQ_PRECISION_QA=1.
No provider requests, schedules, existing observations or QC policies are changed.
"""
import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.engine import make_url

from db import DATABASE_URL, SessionLocal
from models import AggregationPeriod, Device, ExternalAPI, Parameter, Role, Sensor, User, UserRole
from services.auth import hash_password
from services.device_locations import set_device_location
from services.system_settings import get_or_create_system_settings


def seed(output_directory: Path, api_url: str):
    if os.environ.get("COMPASSAQ_PRECISION_QA") != "1" or make_url(DATABASE_URL).database != "precision_qa":
        raise RuntimeError("Requires COMPASSAQ_PRECISION_QA=1 and a disposable database named precision_qa")
    csv_key = os.environ["COMPASSAQ_CSV_UPLOAD_API_KEY"]
    with SessionLocal() as session:
        settings = get_or_create_system_settings(session)
        settings.is_system_setup_complete = True
        role = session.scalar(select(Role).where(Role.name == "analyst"))
        if role is None:
            raise RuntimeError("Run database migrations before seeding the fixture")
        for name in ["alex", "daniela"]:
            email = f"{name}.precision@example.com"
            if session.scalar(select(User).where(User.email == email)) is None:
                user = User(user_id=uuid4(), org_id=uuid4(), email=email, is_active=True,
                            password_hash=hash_password("Isolated-Precision-QA-2026!"))
                session.add(user)
                session.flush()
                session.add(UserRole(user_id=user.user_id, role_id=role.role_id))
        sensor = session.scalar(select(Sensor).where(Sensor.external_sensor_id == "SYNTHETIC-D01"))
        if sensor is None:
            source = ExternalAPI(name="SYNTHETIC DEF-004 precision", enabled=False, params={})
            session.add(source)
            session.flush()
            device = Device(name="SYNTHETIC DEF-004 precision station", timezone="UTC", external_api_id=source.external_api_id)
            session.add(device)
            session.flush()
            set_device_location(session, device, latitude=34.05, longitude=-118.25)
            parameter = session.scalar(select(Parameter).where(Parameter.code == "pm25"))
            period = session.scalar(select(AggregationPeriod).where(AggregationPeriod.code == "1m"))
            sensor = Sensor(device_id=device.device_id, parameter_id=parameter.parameter_id,
                unit_id=parameter.default_unit_id, aggregation_period_id=period.aggregation_period_id,
                external_sensor_id="SYNTHETIC-D01", expected_frequency_seconds=60,
                measurement_duration_seconds=60, source_aggregation_duration_seconds=60,
                measurement_timestamp_semantics="interval_start")
            session.add(sensor)
        session.commit()
        sensor_id, device_id = sensor.sensor_id, sensor.device_id

    start = datetime(2026, 10, 15, 3, 50, tzinfo=timezone.utc)
    values = [Decimal("10.123456789"), *[Decimal(100 + index) / 10 for index in range(1, 24)]]
    csv_text = "internalsensorid,datetime,value\n" + "\n".join(
        f"{sensor_id},{(start + timedelta(minutes=index)).isoformat()},{value}"
        for index, value in enumerate(values))
    with httpx.Client(base_url=api_url) as client:
        response = client.post('/ingest/upload-csv', headers={"X-API-Key": csv_key},
                               files={"file": ("native-input.csv", csv_text, "text/csv")})
        response.raise_for_status()
        if response.json()["failed_records"]:
            raise RuntimeError(response.text)
    fixture = {"sensor_id": sensor_id, "device_id": device_id, "start": start.isoformat(),
               "end": (start + timedelta(minutes=23)).isoformat(), "raw_mean": str(sum(values) / 24)}
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "native-input.csv").write_text(csv_text, encoding="utf-8")
    (output_directory / "fixture.json").write_text(json.dumps(fixture, indent=2), encoding="utf-8")
    print(json.dumps(fixture))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, default=Path("/evidence"))
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    arguments = parser.parse_args()
    seed(arguments.output_directory, arguments.api_url)
