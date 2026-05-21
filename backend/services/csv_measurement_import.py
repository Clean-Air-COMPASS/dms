from __future__ import annotations

import csv
import io
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import Header, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db import SessionLocal
import models


CSV_UPLOAD_API_KEY_ENV = "COMPASSAQ_CSV_UPLOAD_API_KEY"
CSV_UPLOAD_MAX_BYTES_ENV = "COMPASSAQ_CSV_UPLOAD_MAX_BYTES"
DEFAULT_CSV_UPLOAD_MAX_BYTES = 1_048_576
CSV_REQUIRED_HEADERS = ("internalsensorid", "datetime", "value")
API_KEY_HEADER_NAME = "X-API-Key"


@dataclass
class CsvUploadPayload:
    text: str


def get_csv_upload_api_key() -> str:
    value = (os.environ.get(CSV_UPLOAD_API_KEY_ENV) or "").strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{CSV_UPLOAD_API_KEY_ENV} is not configured",
        )
    return value


def require_csv_upload_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing {API_KEY_HEADER_NAME} header",
        )
    expected = get_csv_upload_api_key()
    if not secrets.compare_digest(x_api_key.strip(), expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )


def get_csv_upload_max_bytes() -> int:
    raw = (os.environ.get(CSV_UPLOAD_MAX_BYTES_ENV) or "").strip()
    if not raw:
        return DEFAULT_CSV_UPLOAD_MAX_BYTES
    try:
        value = int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{CSV_UPLOAD_MAX_BYTES_ENV} must be an integer",
        ) from exc
    if value <= 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{CSV_UPLOAD_MAX_BYTES_ENV} must be greater than zero",
        )
    return value


def _looks_binary(payload: bytes) -> bool:
    if not payload:
        return False
    sample = payload[:4096]
    if b"\x00" in sample:
        return True
    suspicious = 0
    for byte in sample:
        if byte in (9, 10, 13):
            continue
        if 32 <= byte <= 126:
            continue
        if 160 <= byte <= 255:
            continue
        suspicious += 1
    return suspicious / max(len(sample), 1) > 0.30


async def validate_csv_upload_file(file: UploadFile) -> CsvUploadPayload:
    payload = await file.read()
    max_bytes = get_csv_upload_max_bytes()
    if len(payload) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Upload exceeds maximum size of {max_bytes} bytes",
        )

    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    if _looks_binary(payload):
        raise HTTPException(status_code=400, detail="Uploaded file must be a text-based CSV")

    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Uploaded file must be valid UTF-8 CSV text") from exc

    if "," not in text:
        raise HTTPException(status_code=400, detail="Uploaded file does not appear to be CSV")

    preview_reader = csv.reader(io.StringIO(text))
    try:
        first_row = next(preview_reader)
    except StopIteration as exc:
        raise HTTPException(status_code=400, detail="CSV header row is required") from exc

    if not first_row:
        raise HTTPException(status_code=400, detail="CSV header row is required")

    normalized_headers = {(header or "").strip().lower() for header in first_row}
    missing = [name for name in CSV_REQUIRED_HEADERS if name not in normalized_headers]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"missing required CSV columns: {', '.join(missing)}",
        )

    return CsvUploadPayload(text=text)


def _parse_iso8601_to_utc(value: str, fallback_timezone: Optional[str]) -> datetime:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("datetime is required")

    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"

    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("datetime must be ISO 8601") from exc

    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)

    if not fallback_timezone:
        raise ValueError("datetime has no timezone and device timezone is not configured")

    try:
        tz = ZoneInfo(fallback_timezone)
    except Exception as exc:
        raise ValueError(f"device timezone '{fallback_timezone}' is invalid") from exc

    return dt.replace(tzinfo=tz).astimezone(timezone.utc)


def _resolve_sensor_timezone(
    session,
    sensor_id: int,
    cache: dict[int, tuple[Optional[str], Optional[str]]],
) -> tuple[Optional[int], Optional[str], Optional[str]]:
    if sensor_id in cache:
        sensor_error = cache[sensor_id][1]
        return sensor_id if sensor_error is None else None, cache[sensor_id][0], sensor_error

    row = session.execute(
        select(models.Device.timezone)
        .join(models.Sensor, models.Sensor.device_id == models.Device.device_id)
        .where(models.Sensor.sensor_id == sensor_id)
        .limit(1)
    ).first()
    if not row:
        cache[sensor_id] = (None, "sensor not found")
        return None, None, "sensor not found"

    timezone_name = row[0]
    cache[sensor_id] = (timezone_name, None)
    return sensor_id, timezone_name, None


def import_measurements_csv_text(text: str) -> dict:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV header row is required")

    normalized_headers = {(header or "").strip().lower(): header for header in reader.fieldnames}
    missing = [name for name in CSV_REQUIRED_HEADERS if name not in normalized_headers]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"missing required CSV columns: {', '.join(missing)}",
        )

    total_records = 0
    inserted_records = 0
    failed_records = 0
    errors: list[str] = []
    sensor_cache: dict[int, tuple[Optional[str], Optional[str]]] = {}

    with SessionLocal() as session:
        for row_index, row in enumerate(reader, start=2):
            if not row:
                continue
            if not any((value or "").strip() for value in row.values()):
                continue

            total_records += 1

            try:
                raw_sensor_id = (row.get(normalized_headers["internalsensorid"]) or "").strip()
                raw_datetime = (row.get(normalized_headers["datetime"]) or "").strip()
                raw_value = (row.get(normalized_headers["value"]) or "").strip()

                if not raw_sensor_id:
                    raise ValueError("internalsensorid is required")
                if not raw_value:
                    raise ValueError("value is required")

                sensor_id = int(raw_sensor_id)
                value = float(raw_value)

                sensor_id, device_timezone, sensor_error = _resolve_sensor_timezone(
                    session, sensor_id, sensor_cache
                )
                if sensor_error or sensor_id is None:
                    raise ValueError(sensor_error or "unable to resolve sensor")

                observed_at = _parse_iso8601_to_utc(raw_datetime, device_timezone)

                try:
                    with session.begin_nested():
                        session.add(
                            models.Measurement(
                                sensor_id=sensor_id,
                                value=value,
                                observed_at=observed_at,
                                is_valid=True,
                            )
                        )
                        session.flush()
                except IntegrityError as exc:
                    raise ValueError("duplicate measurement for sensor and observed_at") from exc

                inserted_records += 1
            except Exception as exc:
                failed_records += 1
                if len(errors) < 20:
                    errors.append(f"row {row_index}: {exc}")

        session.commit()

    success = failed_records == 0
    if success:
        message = (
            f"Upload succeeded. Inserted {inserted_records}/{total_records} records "
            f"({failed_records} failed)."
        )
    else:
        message = (
            f"Upload completed with failures. Inserted {inserted_records}/{total_records} records "
            f"({failed_records} failed)."
        )

    return {
        "success": success,
        "message": message,
        "total_records": total_records,
        "inserted_records": inserted_records,
        "failed_records": failed_records,
        "errors": errors,
    }
