from __future__ import annotations

import csv
import io
import logging
import math
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import Header, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from db import SessionLocal
import models
from services.event_log import add_event
from sources.openaq.openaq_upserts import upsert_measurement_with_policy_detailed

CSV_UPLOAD_API_KEY_ENV = "COMPASSAQ_CSV_UPLOAD_API_KEY"
CSV_UPLOAD_MAX_BYTES_ENV = "COMPASSAQ_CSV_UPLOAD_MAX_BYTES"
DEFAULT_CSV_UPLOAD_MAX_BYTES = 5_000_000
CSV_UPLOAD_TOO_LARGE_ERROR_CODE = "csv_file_too_large"
CSV_REQUIRED_HEADERS = ("internalsensorid", "datetime", "value")
API_KEY_HEADER_NAME = "X-API-Key"
# CSV-only MVP policy: accommodate a small device clock error, not forecasts.
CSV_FUTURE_TOLERANCE = timedelta(minutes=5)
logger = logging.getLogger(__name__)


class CsvRowError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


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
    max_bytes = get_csv_upload_max_bytes()
    # Read one byte past the configured limit so the application can distinguish
    # an exactly-at-limit file from an oversized one without retaining an
    # unbounded request body in memory.
    payload = await file.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "error_code": CSV_UPLOAD_TOO_LARGE_ERROR_CODE,
                "message": f"Upload exceeds maximum size of {max_bytes} bytes",
                "error_context": {"max_bytes": max_bytes},
            },
        )

    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    if _looks_binary(payload):
        raise HTTPException(
            status_code=400, detail="Uploaded file must be a text-based CSV"
        )

    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400, detail="Uploaded file must be valid UTF-8 CSV text"
        ) from exc

    if "," not in text:
        raise HTTPException(
            status_code=400, detail="Uploaded file does not appear to be CSV"
        )

    preview_reader = csv.reader(io.StringIO(text))
    try:
        first_row = next(preview_reader)
    except StopIteration as exc:
        raise HTTPException(
            status_code=400, detail="CSV header row is required"
        ) from exc

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
        raise CsvRowError("datetime_required", "datetime is required")

    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"

    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CsvRowError("datetime_invalid", "datetime must be ISO 8601") from exc

    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)

    if not fallback_timezone:
        raise CsvRowError(
            "timezone_missing",
            "datetime has no timezone and device timezone is not configured",
        )

    try:
        tz = ZoneInfo(fallback_timezone)
    except Exception as exc:
        raise CsvRowError(
            "timezone_invalid", f"device timezone '{fallback_timezone}' is invalid"
        ) from exc

    return dt.replace(tzinfo=tz).astimezone(timezone.utc)


def import_measurements_csv_text(text: str, *, event_id: int | None = None) -> dict:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV header row is required")

    normalized_headers = {
        (header or "").strip().lower(): header for header in reader.fieldnames
    }
    missing = [name for name in CSV_REQUIRED_HEADERS if name not in normalized_headers]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"missing required CSV columns: {', '.join(missing)}",
        )

    total_records = 0
    inserted_records = 0
    updated_records = 0
    skipped_records = 0
    failed_records = 0
    errors: list[str] = []
    row_errors: list[dict] = []
    sensor_cache: dict[int, models.Sensor | None] = {}
    qc = {"evaluated": 0, "passed": 0, "flagged": 0, "indeterminate": 0}
    latest_allowed_timestamp = datetime.now(timezone.utc) + CSV_FUTURE_TOLERANCE

    with SessionLocal() as session:
        for row in reader:
            # DictReader tracks physical file lines, including the header and
            # blank/multiline records. Keep this indexing; call it a line.
            line_number = reader.line_num
            if not row:
                continue
            if all(
                value is None or isinstance(value, str) and not value.strip()
                for value in row.values()
            ):
                continue

            total_records += 1

            try:
                if None in row:
                    raise CsvRowError(
                        "extra_columns", "record has more fields than the CSV header"
                    )
                raw_sensor_id = (
                    row.get(normalized_headers["internalsensorid"]) or ""
                ).strip()
                raw_datetime = (row.get(normalized_headers["datetime"]) or "").strip()
                raw_value = (row.get(normalized_headers["value"]) or "").strip()

                if not raw_sensor_id:
                    raise CsvRowError("sensor_required", "internalsensorid is required")
                if not raw_value:
                    raise CsvRowError("value_required", "value is required")

                try:
                    sensor_id = int(raw_sensor_id)
                except ValueError as exc:
                    raise CsvRowError(
                        "sensor_invalid",
                        "internalsensorid must be an integer sensor ID",
                    ) from exc
                if not 1 <= sensor_id <= 2_147_483_647:
                    raise CsvRowError(
                        "sensor_invalid",
                        "internalsensorid must be a positive internal Sensor ID",
                    )

                try:
                    value = float(raw_value)
                except ValueError as exc:
                    raise CsvRowError(
                        "value_invalid", "value must be a finite number"
                    ) from exc
                if not math.isfinite(value):
                    raise CsvRowError("value_invalid", "value must be a finite number")

                if sensor_id not in sensor_cache:
                    sensor_cache[sensor_id] = session.get(models.Sensor, sensor_id)
                sensor = sensor_cache[sensor_id]
                if sensor is None:
                    raise CsvRowError("sensor_not_found", "sensor not found")
                device = sensor.device

                observed_at = _parse_iso8601_to_utc(raw_datetime, device.timezone)
                if observed_at > latest_allowed_timestamp:
                    raise CsvRowError(
                        "timestamp_future",
                        "timestamp is later than the allowed future tolerance (5 minutes)",
                    )

                try:
                    with session.begin_nested():
                        result = upsert_measurement_with_policy_detailed(
                            session,
                            models.Measurement(
                                sensor_id=sensor_id,
                                value=value,
                                observed_at=observed_at,
                                is_valid=True,
                            ),
                            sensor=sensor,
                            device=device,
                        )
                        session.flush()
                except IntegrityError as exc:
                    # An unexpected competing write is not a Keep decision.
                    raise CsvRowError(
                        "write_conflict",
                        "measurement changed during import; retry this line",
                    ) from exc

                if result.action == "insert":
                    inserted_records += 1
                elif result.action == "update":
                    updated_records += 1
                else:
                    skipped_records += 1
                if result.qc:
                    for key in qc:
                        qc[key] += result.qc[key]
            except Exception as exc:
                failed_records += 1
                if isinstance(exc, CsvRowError):
                    code, message = exc.code, str(exc)
                else:
                    logger.exception("CSV import failed at line %s", line_number)
                    code, message = (
                        "import_failed",
                        "measurement could not be saved; contact an administrator",
                    )
                if len(errors) < 20:
                    errors.append(f"Line {line_number}: {message}")
                    row_errors.append(
                        {"line": line_number, "code": code, "message": message}
                    )

        result = {
            "success": failed_records == 0,
            "message": (
                f"CSV processing completed: {inserted_records} inserted, {updated_records} updated, "
                f"{skipped_records} skipped, {failed_records} failed ({total_records} total)."
            ),
            "total_records": total_records,
            "inserted_records": inserted_records,
            "updated_records": updated_records,
            "skipped_records": skipped_records,
            "failed_records": failed_records,
            "errors": errors,
            "row_errors": row_errors,
            "qc": qc,
        }
        if event_id is not None:
            # Completion and measurements commit together. A later HTTP error
            # must not leave a successful import looking unfinished in Events.
            _update_csv_event(session, event_id, result)
        session.commit()
        return result


def _start_csv_event(
    filename: str | None, endpoint: str, actor_user_id, actor_email
) -> int:
    with SessionLocal() as session:
        event = add_event(
            session,
            event_type="csv.upload",
            source="CSV upload",
            message="CSV upload started",
            endpoint=endpoint,
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            params={
                "outcome": "running",
                "filename": (filename or "")[:255],
                "started_at": datetime.now(timezone.utc).isoformat(),
                "total_records": 0,
                "inserted_records": 0,
                "updated_records": 0,
                "skipped_records": 0,
                "failed_records": 0,
            },
        )
        session.commit()
        return event.event_id


def _finish_csv_event(
    event_id: int, result: dict | None, error_code: str | None = None
):
    with SessionLocal() as session:
        _update_csv_event(session, event_id, result, error_code)
        session.commit()


def _update_csv_event(
    session, event_id: int, result: dict | None, error_code: str | None = None
):
    event = session.get(models.Event, event_id)
    counts = {
        key: (result or {}).get(key, 0)
        for key in (
            "total_records",
            "inserted_records",
            "updated_records",
            "skipped_records",
            "failed_records",
        )
    }
    completed_records = sum(
        counts[key]
        for key in ("inserted_records", "updated_records", "skipped_records")
    )
    if result is None or (counts["failed_records"] and not completed_records):
        outcome = "failed"
    elif counts["failed_records"]:
        outcome = "partial"
    else:
        outcome = "success"
    event.severity = {"success": "info", "partial": "warning", "failed": "error"}[
        outcome
    ]
    event.message = (result or {}).get(
        "message", "CSV upload rejected or import failed"
    )
    event.params = {
        **event.params,
        **counts,
        "outcome": outcome,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "qc": (result or {}).get("qc"),
        "error_code": error_code,
    }


async def import_measurements_csv_upload(
    file: UploadFile,
    *,
    endpoint: str,
    actor_user_id=None,
    actor_email: str | None = None,
) -> dict:
    """Keep one existing Event per authenticated upload, including rejected files.

    CSV has no schedule, so a JobRun (which requires a JobSchedule) would invent
    scheduler state. QC failures remain in MeasurementQCResult, not row Events.
    """
    event_id = await run_in_threadpool(
        _start_csv_event, file.filename, endpoint, actor_user_id, actor_email
    )
    try:
        upload = await validate_csv_upload_file(file)
        result = await run_in_threadpool(
            import_measurements_csv_text, upload.text, event_id=event_id
        )
    except Exception as exc:
        code = "csv_import_failed"
        if isinstance(exc, HTTPException):
            code = (
                exc.detail.get("error_code", "csv_file_invalid")
                if isinstance(exc.detail, dict)
                else "csv_file_invalid"
            )
        await run_in_threadpool(_finish_csv_event, event_id, None, code)
        raise
    return {**result, "event_id": event_id}
