"""Local-file reading and integrity checks for reference fixtures."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path

from pydantic import ValidationError

from reference_data.schema import FixtureMeasurement, ReferenceFixtureManifest


class ReferenceFixtureError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    """Hash a text fixture with repository line endings normalized to LF.

    Frozen fixtures are UTF-8 JSON or JSONL files. Checkout line endings are
    not provider evidence, but every other byte remains hash-significant.
    """

    content = path.read_bytes()
    normalized_content = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(normalized_content).hexdigest()


def read_fixture_manifest(fixture_root: Path) -> ReferenceFixtureManifest:
    manifest_path = fixture_root / "manifest.json"
    try:
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = ReferenceFixtureManifest.model_validate(raw_manifest)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ReferenceFixtureError(f"Invalid fixture manifest {manifest_path}: {exc}") from exc

    measurements_path = fixture_root / manifest.measurements_file
    actual_checksum = sha256_file(measurements_path)
    if actual_checksum.lower() != manifest.measurements_sha256.lower():
        raise ReferenceFixtureError(
            f"Measurement checksum mismatch: expected {manifest.measurements_sha256}, got {actual_checksum}"
        )
    return manifest


def read_fixture_measurements(
    fixture_root: Path,
    manifest: ReferenceFixtureManifest,
) -> list[FixtureMeasurement]:
    sensor_refs = {sensor.fixture_ref for sensor in manifest.sensors}
    measurements_path = fixture_root / manifest.measurements_file
    expanded: list[FixtureMeasurement] = []
    previous_by_sensor = {}

    with measurements_path.open("r", encoding="utf-8") as fixture_file:
        for line_number, line in enumerate(fixture_file, start=1):
            if not line.strip():
                continue
            try:
                compact = FixtureMeasurement.model_validate_json(line)
            except ValidationError as exc:
                raise ReferenceFixtureError(
                    f"Invalid measurement at line {line_number}: {exc}"
                ) from exc
            if compact.sensor_ref not in sensor_refs:
                raise ReferenceFixtureError(
                    f"Unknown sensor_ref '{compact.sensor_ref}' at line {line_number}"
                )
            for offset in range(compact.repeat_count):
                observed_at = compact.observed_at + timedelta(
                    seconds=(compact.interval_seconds or 0) * offset
                )
                prior = previous_by_sensor.get(compact.sensor_ref)
                if prior is not None and observed_at < prior:
                    raise ReferenceFixtureError(
                        f"Measurements for {compact.sensor_ref} are not sorted at line {line_number}"
                    )
                previous_by_sensor[compact.sensor_ref] = observed_at
                expanded.append(
                    compact.model_copy(
                        update={
                            "observed_at": observed_at,
                            "repeat_count": 1,
                            "interval_seconds": None,
                        }
                    )
                )
    if manifest.capture is not None:
        sensor_by_ref = {sensor.fixture_ref: sensor for sensor in manifest.sensors}
        provider_refs: set[str] = set()
        for measurement in expanded:
            if not (
                manifest.capture.window_start
                <= measurement.observed_at
                < manifest.capture.window_end
            ):
                raise ReferenceFixtureError(
                    f"Measurement {measurement.provider_observation_ref!r} is outside "
                    "the capture's half-open UTC window"
                )
            if measurement.provider_observation_ref is None:
                raise ReferenceFixtureError(
                    "Provider captures require provider_observation_ref on every measurement"
                )
            if measurement.provider_observation_ref in provider_refs:
                raise ReferenceFixtureError(
                    f"Duplicate provider_observation_ref {measurement.provider_observation_ref!r}"
                )
            provider_refs.add(measurement.provider_observation_ref)
            if (
                measurement.source_page is None
                or measurement.source_page > manifest.capture.max_pages_per_sensor
            ):
                raise ReferenceFixtureError(
                    f"Invalid source_page for {measurement.provider_observation_ref}"
                )
            sensor = sensor_by_ref[measurement.sensor_ref]
            provider_parameter = measurement.provider_parameter
            if not isinstance(provider_parameter, dict):
                raise ReferenceFixtureError(
                    f"Missing provider_parameter for {measurement.provider_observation_ref}"
                )
            if (
                provider_parameter.get("name") != sensor.provider_parameter_name
                or provider_parameter.get("units") != sensor.provider_unit
            ):
                raise ReferenceFixtureError(
                    f"Provider parameter/unit mismatch for {measurement.provider_observation_ref}"
                )
            if measurement.provider_period is not None:
                period_from = _provider_period_utc(
                    measurement.provider_period,
                    "datetimeFrom",
                    measurement.provider_observation_ref,
                )
                period_to = _provider_period_utc(
                    measurement.provider_period,
                    "datetimeTo",
                    measurement.provider_observation_ref,
                )
                if period_to <= period_from or period_to != measurement.observed_at:
                    raise ReferenceFixtureError(
                        f"Provider period mismatch for {measurement.provider_observation_ref}"
                    )
            elif measurement.provider_timestamp is not None:
                provider_observed_at = _provider_timestamp_utc(
                    measurement.provider_timestamp,
                    measurement.provider_observation_ref,
                )
                if provider_observed_at != measurement.observed_at:
                    raise ReferenceFixtureError(
                        f"Provider timestamp mismatch for {measurement.provider_observation_ref}"
                    )
                if measurement.provider_field != sensor.provider_parameter_name:
                    raise ReferenceFixtureError(
                        f"Provider field mismatch for {measurement.provider_observation_ref}"
                    )
            else:
                raise ReferenceFixtureError(
                    "Provider captures require provider_period or provider_timestamp "
                    f"for {measurement.provider_observation_ref}"
                )

        sensor_result_requests = sum(
            int(result.get("requests_executed", 0))
            for result in manifest.capture.sensor_results
        )
        if sensor_result_requests != manifest.capture.request_count:
            raise ReferenceFixtureError(
                "Capture sensor request totals do not match capture.request_count"
            )
        _validate_capture_row_totals(manifest, expanded)
    return expanded


def _provider_period_utc(
    provider_period: dict,
    field_name: str,
    provider_observation_ref: str,
) -> datetime:
    value = provider_period.get(field_name)
    if isinstance(value, dict):
        value = value.get("utc")
    if not isinstance(value, str):
        raise ReferenceFixtureError(
            f"Missing provider period {field_name}.utc for {provider_observation_ref}"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReferenceFixtureError(
            f"Invalid provider period {field_name}.utc for {provider_observation_ref}"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ReferenceFixtureError(
            f"Provider period {field_name}.utc is not UTC for {provider_observation_ref}"
        )
    return parsed.astimezone(timezone.utc)


def _provider_timestamp_utc(
    value: int | float | str,
    provider_observation_ref: str,
) -> datetime:
    try:
        timestamp = float(value)
    except (TypeError, ValueError) as exc:
        raise ReferenceFixtureError(
            f"Invalid provider timestamp for {provider_observation_ref}"
        ) from exc
    if not math.isfinite(timestamp):
        raise ReferenceFixtureError(
            f"Invalid provider timestamp for {provider_observation_ref}"
        )
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise ReferenceFixtureError(
            f"Invalid provider timestamp for {provider_observation_ref}"
        ) from exc


def _validate_capture_row_totals(
    manifest: ReferenceFixtureManifest,
    measurements: list[FixtureMeasurement],
) -> None:
    """Reconcile provider-specific capture summaries with preserved rows."""
    assert manifest.capture is not None
    measurement_count_by_ref = {
        sensor.fixture_ref: sum(
            measurement.sensor_ref == sensor.fixture_ref
            for measurement in measurements
        )
        for sensor in manifest.sensors
    }
    for result in manifest.capture.sensor_results:
        if "openaq_sensor_id" in result:
            provider_sensor_id = str(result["openaq_sensor_id"])
            actual = sum(
                measurement_count_by_ref[sensor.fixture_ref]
                for sensor in manifest.sensors
                if sensor.external_sensor_id == provider_sensor_id
            )
            expected = int(result.get("rows_preserved", 0))
        elif "provider_sensor_id" in result:
            provider_sensor_id = str(result["provider_sensor_id"])
            matching_sensors = [
                sensor
                for sensor in manifest.sensors
                if isinstance(sensor.capture_statistics, dict)
                and str(sensor.capture_statistics.get("provider_sensor_id"))
                == provider_sensor_id
            ]
            actual = sum(
                measurement_count_by_ref[sensor.fixture_ref]
                for sensor in matching_sensors
            )
            expected = int(result.get("measurement_rows_preserved", 0))
        else:
            raise ReferenceFixtureError(
                "Capture sensor result is missing a supported provider sensor ID"
            )
        if actual != expected:
            raise ReferenceFixtureError(
                "Capture sensor row totals do not match measurements.jsonl for "
                f"provider sensor {provider_sensor_id}: expected {expected}, got {actual}"
            )
