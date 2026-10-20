from __future__ import annotations

import argparse
import json
import os
import time
import sys
from contextlib import contextmanager
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from sqlalchemy import func, select

import models
from reference_data.regions import (
    validate_reference_coordinates,
    validate_south_america_reference_coordinates,
)
from qaqc import discovery
from services.device_locations import set_device_location, validate_coordinate_pair
from db import SessionLocal
from services.external_sources import require_task_source_runnable
from services.import_summaries import (
    merge_qc_counts,
    new_import_summary,
    write_import_summary,
)
from jobs.locking import postgres_advisory_lock
from sources.airgradient import map_history
from sources.airgradient.history_ingestion import import_location_history

try:
    from sources.openaq.openaq_upserts import upsert_measurement_with_policy_detailed
except Exception:
    upsert_measurement_with_policy_detailed = None

DEFAULT_BASE_URL = "https://api.airgradient.com/public/api/v1"


class AirGradientImporterError(Exception):
    """Raised for recoverable importer issues."""


class AirGradientRateLimit(AirGradientImporterError):
    """Raised when API returns 429."""


class AirGradientAuthenticationError(AirGradientImporterError):
    """Raised when AirGradient rejects the saved place token."""


class AirGradientProviderUnavailable(AirGradientImporterError):
    """Raised when AirGradient is unavailable or cannot be reached."""


class AirGradientNetworkError(AirGradientProviderUnavailable):
    """A connection failed before a provider response was received."""


class AirGradientTimeout(AirGradientNetworkError):
    """A bounded provider request timed out."""


class AirGradientMalformedResponse(AirGradientImporterError):
    """Raised when a successful response does not match the documented shape."""


@dataclass(frozen=True)
class AirGradientFieldDefinition:
    """One verified provider field mapped to canonical CompassAQ identity."""

    parameter_code: str
    unit_code: str


# AirGradient wire names are normalized here and nowhere downstream. The
# provider documents tvoc as a derived ppb estimate and tvocIndex/noxIndex as
# separate dimensionless indices. Raw SGP41 ticks are intentionally unsupported.
AIRGRADIENT_FIELD_DEFINITIONS: dict[str, AirGradientFieldDefinition] = {
    "pm01": AirGradientFieldDefinition("pm1", "ug_m3"),
    "pm01_corrected": AirGradientFieldDefinition("pm1", "ug_m3"),
    "pm02": AirGradientFieldDefinition("pm25", "ug_m3"),
    "pm02_corrected": AirGradientFieldDefinition("pm25", "ug_m3"),
    "pm02compensated": AirGradientFieldDefinition("pm25", "ug_m3"),
    "pm2.5": AirGradientFieldDefinition("pm25", "ug_m3"),
    "pm25": AirGradientFieldDefinition("pm25", "ug_m3"),
    "pm10": AirGradientFieldDefinition("pm10", "ug_m3"),
    "pm10_corrected": AirGradientFieldDefinition("pm10", "ug_m3"),
    "co2": AirGradientFieldDefinition("co2", "ppm"),
    "rco2": AirGradientFieldDefinition("co2", "ppm"),
    "rco2_corrected": AirGradientFieldDefinition("co2", "ppm"),
    "tvoc": AirGradientFieldDefinition("tvoc", "ppb"),
    "tvocindex": AirGradientFieldDefinition("tvoc_index", "index"),
    "noxindex": AirGradientFieldDefinition("nox_index", "index"),
    "temperature": AirGradientFieldDefinition("temperature", "celsius"),
    "temp": AirGradientFieldDefinition("temperature", "celsius"),
    "atmp": AirGradientFieldDefinition("temperature", "celsius"),
    "atmp_corrected": AirGradientFieldDefinition("temperature", "celsius"),
    "atmpcompensated": AirGradientFieldDefinition("temperature", "celsius"),
    "humidity": AirGradientFieldDefinition("relative_humidity", "percent"),
    "rhum": AirGradientFieldDefinition("relative_humidity", "percent"),
    "rhum_corrected": AirGradientFieldDefinition("relative_humidity", "percent"),
    "rhumcompensated": AirGradientFieldDefinition("relative_humidity", "percent"),
    "pres": AirGradientFieldDefinition("pressure", "hpa"),
    "pressure": AirGradientFieldDefinition("pressure", "hpa"),
}

# Retain the established public name for callers while making its values
# canonical database codes rather than provider shorthands or unit symbols.
PARAM_MAP: Dict[str, Tuple[str, str]] = {
    field_name: (definition.parameter_code, definition.unit_code)
    for field_name, definition in AIRGRADIENT_FIELD_DEFINITIONS.items()
}

# One provider field is selected for each CompassAQ parameter. Corrected fields
# are preferred when AirGradient supplies both corrected and raw values, which
# prevents two values at the same timestamp from competing for one Sensor row.
AIRGRADIENT_FIELD_PREFERENCES: dict[str, tuple[str, ...]] = {
    "pm1": ("pm01_corrected", "pm01"),
    "pm25": ("pm02_corrected", "pm02compensated", "pm02", "pm2.5", "pm25"),
    "pm10": ("pm10_corrected", "pm10"),
    "co2": ("rco2_corrected", "rco2", "co2"),
    "tvoc": ("tvoc",),
    "tvoc_index": ("tvocindex",),
    "nox_index": ("noxindex",),
    "temperature": (
        "atmp_corrected",
        "atmpcompensated",
        "atmp",
        "temperature",
        "temp",
    ),
    "relative_humidity": (
        "rhum_corrected",
        "rhumcompensated",
        "rhum",
        "humidity",
    ),
    "pressure": ("pres", "pressure"),
}

AIRGRADIENT_WIFI_EXPECTED_FREQUENCY_SECONDS = 60
AIRGRADIENT_CELLULAR_EXPECTED_FREQUENCY_SECONDS = 180
AIRGRADIENT_MEASUREMENT_DURATION_SECONDS = 12

AIRGRADIENT_AUTHENTICATED_PATH = "airgradient_authenticated"
AIRGRADIENT_PUBLIC_REFERENCE_PATH = "airgradient_public_reference"
AIRGRADIENT_PROVIDER_URL = "https://www.airgradient.com"
AIRGRADIENT_PUBLIC_LICENSE_CODE = "CC-BY-SA-4.0"
AIRGRADIENT_PUBLIC_LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"

AIRGRADIENT_REFERENCE_LOCATIONS_VERSION = "2026-09-15-v3"
_PRIOR_REFERENCE_LOCATION_IDS = {
    "2026-08-17-v1": {"58376", "175911", "160791"},
    "2026-09-11-v2": {"58376", "160791"},
}
# One-time catalog investigation: nearest active public South America site to
# Rio, not a station in Rio. Runtime requests remain limited to these fixed IDs.
AIRGRADIENT_UNAVAILABLE_REFERENCE_REGIONS: tuple[str, ...] = ()
AIRGRADIENT_REFERENCE_LOCATIONS = (
    {
        "code": "new_york",
        "label": "New York",
        "location_id": "58376",
        "timezone": "America/New_York",
    },
    {
        "code": "south_america_rio_reference",
        "label": "South America (nearest verified site to Rio)",
        "location_id": "175911",
        "timezone": "America/Sao_Paulo",
    },
    {
        "code": "metro_manila",
        "label": "Metro Manila",
        "location_id": "160791",
        "timezone": "Asia/Manila",
    },
)

_LEGACY_REFERENCE_PARAM_KEYS = (
    "reference_discovery_version",
    "reference_regions_selected",
    "reference_regions_missing",
)
_INITIALIZED_REFERENCE_LOCATION_IDS_PARAM = "reference_locations_initialized_ids"


def _validate_public_reference_location(api_device: dict, location_id: str) -> None:
    reference = next(
        (item for item in AIRGRADIENT_REFERENCE_LOCATIONS
         if item["location_id"] == location_id),
        None,
    )
    if reference is None:
        raise AirGradientImporterError(
            f"AirGradient public reference {location_id} is not in the approved regional set"
        )
    try:
        if reference["code"] == "south_america_rio_reference":
            validate_south_america_reference_coordinates(
                location_id, api_device.get("latitude"), api_device.get("longitude")
            )
        else:
            validate_reference_coordinates(
                reference["code"], api_device.get("latitude"), api_device.get("longitude")
            )
    except ValueError as exc:
        raise AirGradientImporterError(str(exc)) from exc


def _emit_event(
    event_type: str,
    severity: str = "info",
    device_id: Optional[int] = None,
    sensor_id: Optional[int] = None,
    message: Optional[str] = None,
    payload: Optional[dict] = None,
) -> None:
    """Emit structured Event row and stdout line."""
    data = {
        "event_type": event_type,
        "source": "airgradient_importer",
        "severity": severity,
        "device_id": device_id,
        "sensor_id": sensor_id,
        "message": message,
        "payload": payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        print("EVENT:" + json.dumps(data, ensure_ascii=False), flush=True)
    except Exception:
        pass
    try:
        from db import SessionLocal as _SessionLocal
        with _SessionLocal() as s:
            evt = models.Event(
                event_type=event_type,
                source="airgradient_importer",
                severity=severity,
                device_id=device_id,
                sensor_id=sensor_id,
                message=message,
                raw_snippet=json.dumps(payload)[:2000] if payload else None,
            )
            s.add(evt)
            s.commit()
    except Exception:
        pass


def _get_api_key(session) -> Optional[str]:
    try:
        row = session.scalars(
            select(models.ExternalAPI.api_key).where(
                models.ExternalAPI.provider_code == "airgradient"
            ).limit(1)
        ).one_or_none()
        if row:
            return row
    except Exception:
        pass
    return os.getenv("AIRGRADIENT_API_KEY")


def _api_get(path: str, api_key: str, params: Optional[dict] = None, include_token: bool = True) -> Any:
    url = path if path.startswith("http") else f"{DEFAULT_BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    query = params.copy() if params else {}
                                                                              
    if include_token:
        query.setdefault("token", api_key)
    try:
        resp = requests.get(url, params=query, timeout=30)
    except requests.Timeout as exc:
        raise AirGradientTimeout("AirGradient request timed out") from exc
    except requests.RequestException as exc:
        # requests exceptions may include the prepared URL and query string.
        # Never copy them into JobRun/Event diagnostics because the token is a
        # query parameter in AirGradient's documented authentication scheme.
        raise AirGradientNetworkError(
            "AirGradient could not be reached"
        ) from exc
    if resp.status_code in {401, 403}:
        raise AirGradientAuthenticationError(
            "AirGradient rejected the saved API token"
        )
    if resp.status_code == 429:
        raise AirGradientRateLimit("AirGradient rate limit reached")
    if resp.status_code >= 500:
        raise AirGradientProviderUnavailable(
            f"AirGradient is unavailable (HTTP {resp.status_code})"
        )
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        raise AirGradientImporterError(
            f"AirGradient request failed (HTTP {resp.status_code})"
        ) from exc
    try:
        return resp.json()
    except Exception as exc:
        raise AirGradientMalformedResponse(
            "AirGradient returned malformed JSON"
        ) from exc


def _apply_public_reference_attribution(
    device: models.Device, api_device: dict
) -> None:
    """Apply AirGradient's published public-API attribution terms."""

    device.acquisition_path = AIRGRADIENT_PUBLIC_REFERENCE_PATH
    device.hardware_provider_name = "AirGradient"
    device.provider_url = AIRGRADIENT_PROVIDER_URL
    device.contributor_name = api_device.get("publicContributorName") or None
    device.contributor_url = api_device.get("publicPlaceUrl") or None
    device.license_code = AIRGRADIENT_PUBLIC_LICENSE_CODE
    device.license_url = AIRGRADIENT_PUBLIC_LICENSE_URL
    device.license_share_alike = True


def _apply_authenticated_attribution(
    device: models.Device, api_device: dict, place: dict
) -> None:
    """Preserve owner/place attribution without inventing a public license.

    AirGradient states that monitor owners own their data. The authenticated
    endpoint does not state that a private location has been published under
    the public API's CC-BY-SA license, so license fields remain explicitly
    unavailable unless a later provider payload supplies that fact.
    """

    device.acquisition_path = AIRGRADIENT_AUTHENTICATED_PATH
    device.hardware_provider_name = "AirGradient"
    device.provider_url = AIRGRADIENT_PROVIDER_URL
    device.contributor_name = (
        api_device.get("publicContributorName")
        or place.get("publicName")
        or None
    )
    device.contributor_url = (
        api_device.get("publicPlaceUrl") or place.get("publicUrl") or None
    )
    device.license_code = None
    device.license_url = None
    device.license_share_alike = None


def _parse_ts(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(float(val), tz=timezone.utc)
        except Exception:
            return None
    if isinstance(val, str):
        try:
            s = val.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _ensure_aggregation_period(session, code: str = "1m", display_name: str = "1 Minute") -> Optional[int]:
    ap = session.scalars(
        select(models.AggregationPeriod).where(func.lower(models.AggregationPeriod.code) == code.lower())
    ).one_or_none()
    if ap:
        return ap.aggregation_period_id
    ap = models.AggregationPeriod(code=code, display_name=display_name)
    session.add(ap)
    session.flush()
    return ap.aggregation_period_id


def _lookup_unit_id(session, code_or_symbol: Optional[str]) -> Optional[int]:
    if not code_or_symbol:
        return None
    val = code_or_symbol.lower()
    unit = session.scalars(select(models.Unit).where(func.lower(models.Unit.code) == val)).one_or_none()
    if unit:
        return unit.unit_id
    unit = session.scalars(select(models.Unit).where(func.lower(models.Unit.symbol) == val)).one_or_none()
    return unit.unit_id if unit else None


def _lookup_param_id(session, code: Optional[str]) -> Optional[int]:
    if not code:
        return None
    param = session.scalars(select(models.Parameter).where(func.lower(models.Parameter.code) == code.lower())).one_or_none()
    return param.parameter_id if param else None


def _normalize_param(key: str) -> Tuple[str, Optional[str]]:
    k = (key or "").strip().lower()
    mapped = PARAM_MAP.get(k)
    if mapped:
        return mapped[0], mapped[1]
    return k, None


def _canonical_catalog(session) -> tuple[dict[str, models.Parameter], dict[str, models.Unit]]:
    """Load every supported canonical identity or fail before persistence."""

    required_parameter_codes = {
        definition.parameter_code
        for definition in AIRGRADIENT_FIELD_DEFINITIONS.values()
    }
    required_unit_codes = {
        definition.unit_code
        for definition in AIRGRADIENT_FIELD_DEFINITIONS.values()
    }
    parameters = {
        parameter.code.lower(): parameter
        for parameter in session.scalars(
            select(models.Parameter).where(
                func.lower(models.Parameter.code).in_(required_parameter_codes)
            )
        ).all()
    }
    units = {
        unit.code.lower(): unit
        for unit in session.scalars(
            select(models.Unit).where(func.lower(models.Unit.code).in_(required_unit_codes))
        ).all()
    }
    missing_parameters = sorted(required_parameter_codes.difference(parameters))
    missing_units = sorted(required_unit_codes.difference(units))
    missing_supported_pairs: list[str] = []
    if not missing_parameters and not missing_units:
        registered_pairs = set(
            session.execute(
                select(
                    models.ParameterSupportedUnit.parameter_id,
                    models.ParameterSupportedUnit.unit_id,
                )
            ).all()
        )
        required_pairs = {
            (definition.parameter_code, definition.unit_code)
            for definition in AIRGRADIENT_FIELD_DEFINITIONS.values()
        }
        missing_supported_pairs = sorted(
            f"{parameter_code}/{unit_code}"
            for parameter_code, unit_code in required_pairs
            if (
                parameters[parameter_code].parameter_id,
                units[unit_code].unit_id,
            )
            not in registered_pairs
        )
    if missing_parameters or missing_units or missing_supported_pairs:
        missing_parts = []
        if missing_parameters:
            missing_parts.append(f"parameters={','.join(missing_parameters)}")
        if missing_units:
            missing_parts.append(f"units={','.join(missing_units)}")
        if missing_supported_pairs:
            missing_parts.append(
                f"supported_pairs={','.join(missing_supported_pairs)}"
            )
        raise AirGradientImporterError(
            "AirGradient canonical catalog is incomplete: " + "; ".join(missing_parts)
        )
    return parameters, units


def _expected_frequency_seconds(api_device: dict) -> int:
    model = str(api_device.get("model") or "").strip().upper()
    if model.endswith("-CE"):
        return AIRGRADIENT_CELLULAR_EXPECTED_FREQUENCY_SECONDS
    return AIRGRADIENT_WIFI_EXPECTED_FREQUENCY_SECONDS


def _apply_airgradient_measurement_metadata(
    sensor: models.Sensor,
    api_device: dict,
    aggregation_period_id: Optional[int],
) -> None:
    """Apply provider-documented current-measure timing without inference."""

    expected_frequency_seconds = _expected_frequency_seconds(api_device)
    sensor.aggregation_period_id = (
        aggregation_period_id
        if expected_frequency_seconds == AIRGRADIENT_WIFI_EXPECTED_FREQUENCY_SECONDS
        else None
    )
    sensor.expected_frequency_seconds = expected_frequency_seconds
    sensor.measurement_duration_seconds = AIRGRADIENT_MEASUREMENT_DURATION_SECONDS
    sensor.source_aggregation_duration_seconds = AIRGRADIENT_MEASUREMENT_DURATION_SECONDS
    sensor.measurement_timestamp_semantics = "observation_instant"
    sensor.measurement_metadata_status = "provider_documented"
    sensor.measurement_metadata_managed_by = "airgradient_importer"
    sensor.acquisition_metadata = {
        "provider": "AirGradient",
        "acquisition_method": "dashboard_current_snapshot",
        "dashboard_location_id": str(api_device["locationId"]),
        "timestamp_semantics": "observation_instant",
    }


def _ensure_reference_device(
    session,
    api_device: dict,
    external_api_id: Optional[int],
    expected_location_id: str,
    expected_timezone: str,
) -> models.Device:
    """Create or refresh a fixed reference device using approved site identity."""
    returned_location_id = api_device.get("locationId")
    if returned_location_id is None:
        raise AirGradientImporterError(
            f"AirGradient reference location {expected_location_id} did not return a locationId"
        )
    ext_id = str(returned_location_id)
    if ext_id != expected_location_id:
        raise AirGradientImporterError(
            "AirGradient reference location "
            f"{expected_location_id} returned mismatched locationId {ext_id}"
        )

    _validate_public_reference_location(api_device, expected_location_id)

    name = (
        api_device.get("locationName")
        or api_device.get("publicLocationName")
        or api_device.get("displayName")
        or api_device.get("name")
    )
    if not isinstance(name, str) or not name.strip():
        # Device.name is required by the database, so missing provider naming is
        # an explicit initialization failure rather than a fabricated fallback.
        raise AirGradientImporterError(
            f"AirGradient reference location {expected_location_id} did not return a name"
        )
    name = name.strip()
    friendly_name = api_device.get("friendlyName") or api_device.get("customName")
    lat = api_device.get("latitude")
    lon = api_device.get("longitude")
    # AirGradient has returned a geographically incorrect IANA name for the
    # Manila reference site. The approved reference definition owns this fixed
    # site's local timezone; provider metadata still owns its name and location.
    tz = expected_timezone
    try:
        coordinate_pair = validate_coordinate_pair(lat, lon)
    except ValueError as exc:
        raise AirGradientImporterError(
            f"AirGradient reference location {expected_location_id} returned invalid coordinates"
        ) from exc
    lat, lon = coordinate_pair if coordinate_pair is not None else (None, None)

    existing = session.scalars(
        select(models.Device).where(
            models.Device.external_api_id == external_api_id,
            models.Device.external_id == ext_id,
            models.Device.acquisition_path == AIRGRADIENT_PUBLIC_REFERENCE_PATH,
        ).limit(1)
    ).first()
    if existing:
        changed = False
        for attr, val in (
            ("name", name),
            ("friendly_name", friendly_name),
            ("timezone", tz),
        ):
            if val is not None and getattr(existing, attr, None) != val:
                setattr(existing, attr, val)
                changed = True
        if lat is not None or lon is not None:
            location_changed = set_device_location(
                session,
                existing,
                latitude=lat,
                longitude=lon,
            )
            changed = location_changed or changed
        if external_api_id and getattr(existing, "external_api_id", None) is None:
            existing.external_api_id = external_api_id
            changed = True
        _apply_public_reference_attribution(existing, api_device)
        changed = True
        if changed:
            session.add(existing)
            session.flush()
        return existing

    device = models.Device(
        name=name,
        friendly_name=friendly_name,
        external_id=ext_id,
        external_api_id=external_api_id,
        acquisition_path=AIRGRADIENT_PUBLIC_REFERENCE_PATH,
        timezone=tz,
        allow_updates=models.UpdatePolicy.INHERIT,
    )
    _apply_public_reference_attribution(device, api_device)
    session.add(device)
    set_device_location(
        session,
        device,
        latitude=lat,
        longitude=lon,
    )
    return device


def _preferred_present_supported_fields(api_device: dict) -> dict[str, str]:
    """Map each supported parameter to its preferred provider-present field.

    Field presence describes provider capability. Current value validity is a
    separate measurement-ingest decision, so a temporarily null field can still
    establish the stable Sensor identity used by later numeric readings.
    """
    fields_by_lower_name = {str(key).lower(): key for key in api_device}
    selected_fields: dict[str, str] = {}
    for parameter_code, field_preferences in AIRGRADIENT_FIELD_PREFERENCES.items():
        for preferred_field in field_preferences:
            original_field = fields_by_lower_name.get(preferred_field)
            if original_field is None:
                continue
            selected_fields[parameter_code] = str(original_field)
            break
    return selected_fields


def _ensure_airgradient_sensors(
    session,
    device: models.Device,
    api_device: dict,
) -> int:
    """Create Sensor rows from provider location and measurement-field identities."""
    parameters, units = _canonical_catalog(session)
    aggregation_period_id = _ensure_aggregation_period(session)
    provider_location_id = str(api_device["locationId"])
    sensors_created = 0
    for parameter_code, provider_field in _preferred_present_supported_fields(
        api_device
    ).items():
        parameter = parameters.get(parameter_code)
        mapped_parameter, unit_code = _normalize_param(provider_field)
        unit = units.get((unit_code or "").lower())
        if parameter is None or unit is None or mapped_parameter != parameter_code:
            raise AirGradientImporterError(
                "AirGradient field did not resolve to its canonical catalog identity: "
                f"{provider_field}"
            )
        external_sensor_id = f"{provider_location_id}:{provider_field}"
        existing_sensor = session.scalar(
            select(models.Sensor).where(
                models.Sensor.device_id == device.device_id,
                models.Sensor.external_sensor_id == external_sensor_id,
            )
        )
        if existing_sensor is not None:
            existing_sensor.parameter_id = parameter.parameter_id
            existing_sensor.unit_id = unit.unit_id
            _apply_airgradient_measurement_metadata(
                existing_sensor, api_device, aggregation_period_id
            )
            session.add(existing_sensor)
            continue
        sensor = models.Sensor(
            device_id=device.device_id,
            parameter_id=parameter.parameter_id,
            unit_id=unit.unit_id,
            external_sensor_id=external_sensor_id,
        )
        _apply_airgradient_measurement_metadata(
            sensor, api_device, aggregation_period_id
        )
        session.add(sensor)
        sensors_created += 1
    session.flush()
    return sensors_created


def _sensor_lookup_for_measurements(
    session,
    device: models.Device,
    measurements: List[dict],
) -> dict[tuple[str, str], models.Sensor]:
    """Resolve each selected provider field to its exact stable Sensor row."""

    selected_sensor_keys: dict[tuple[str, str], str] = {}
    provider_location_id = str(device.external_id)
    for measurement in measurements:
        for parameter_code, provider_field in _preferred_present_supported_fields(
            measurement
        ).items():
            selected_sensor_keys[(parameter_code, provider_field.lower())] = (
                f"{provider_location_id}:{provider_field}"
            )
    if not selected_sensor_keys:
        return {}

    sensors_by_external_id = {
        sensor.external_sensor_id: sensor
        for sensor in session.scalars(
            select(models.Sensor).where(
                models.Sensor.device_id == device.device_id,
                models.Sensor.external_sensor_id.in_(selected_sensor_keys.values()),
            )
        ).all()
    }
    return {
        sensor_key: sensors_by_external_id[external_sensor_id]
        for sensor_key, external_sensor_id in selected_sensor_keys.items()
        if external_sensor_id in sensors_by_external_id
    }


def _reference_location_payload(raw: Any, expected_location_id: str) -> dict:
    """Return the one direct-location record and verify its provider identity."""
    return _location_measurement_payload(
        raw, expected_location_id, "reference location"
    )


def _location_measurement_payload(
    raw: Any, expected_location_id: str, path_label: str
) -> dict:
    """Return one current-measure record with the requested location identity."""

    measurements = _extract_measurements(raw)
    matching_measurements = [
        measurement
        for measurement in measurements
        if isinstance(measurement, dict)
        and str(measurement.get("locationId")) == expected_location_id
    ]
    if len(matching_measurements) != 1:
        raise AirGradientMalformedResponse(
            f"AirGradient {path_label} "
            f"{expected_location_id} returned unexpected location IDs (expected one matching location)"
        )
    return matching_measurements[0]


def _authenticated_place_payload(raw: Any) -> dict:
    """Validate the documented GET /place response used for discovery."""

    if not isinstance(raw, dict):
        raise AirGradientMalformedResponse(
            "AirGradient authenticated place response was not an object"
        )
    if raw.get("id") is None:
        raise AirGradientMalformedResponse(
            "AirGradient authenticated place response omitted id"
        )
    place_name = raw.get("name")
    if not isinstance(place_name, str) or not place_name.strip():
        raise AirGradientMalformedResponse(
            "AirGradient authenticated place response omitted name"
        )
    return raw


def _authenticated_location_payloads(raw: Any) -> list[dict]:
    """Validate all locations returned by GET /locations/measures/current."""

    if not isinstance(raw, list):
        raise AirGradientMalformedResponse(
            "AirGradient authenticated locations response was not an array"
        )
    locations: list[dict] = []
    seen_location_ids: set[str] = set()
    for index, api_location in enumerate(raw):
        if not isinstance(api_location, dict):
            raise AirGradientMalformedResponse(
                f"AirGradient authenticated location at index {index} was not an object"
            )
        location_id = api_location.get("locationId")
        location_name = api_location.get("locationName")
        if isinstance(location_id, bool) or not isinstance(location_id, (int, str)) or not str(location_id).strip():
            raise AirGradientMalformedResponse(
                f"AirGradient authenticated location at index {index} omitted locationId"
            )
        if not isinstance(location_name, str) or not location_name.strip():
            raise AirGradientMalformedResponse(
                f"AirGradient authenticated location {location_id} omitted locationName"
            )
        normalized_location_id = str(location_id)
        if normalized_location_id in seen_location_ids:
            raise AirGradientMalformedResponse(
                f"AirGradient authenticated locations repeated locationId {normalized_location_id}"
            )
        seen_location_ids.add(normalized_location_id)
        locations.append(api_location)
    return locations


def _ensure_authenticated_device(
    session,
    api_device: dict,
    place: dict,
    external_api_id: int,
) -> tuple[models.Device, bool]:
    """Create or update one user-owned location without overwriting admin labels."""

    external_id = str(api_device["locationId"])
    name = str(api_device["locationName"]).strip()
    timezone_name = api_device.get("timezone") or place.get("timezoneId")
    latitude = api_device.get("latitude", api_device.get("lat"))
    longitude = api_device.get("longitude", api_device.get("lng"))
    try:
        coordinate_pair = validate_coordinate_pair(latitude, longitude)
    except ValueError as exc:
        raise AirGradientMalformedResponse(
            f"AirGradient authenticated location {external_id} returned invalid coordinates"
        ) from exc

    device = session.scalar(
        select(models.Device).where(
            models.Device.external_api_id == external_api_id,
            models.Device.external_id == external_id,
            models.Device.acquisition_path == AIRGRADIENT_AUTHENTICATED_PATH,
        )
    )
    created = device is None
    if device is None:
        device = models.Device(
            name=name,
            external_id=external_id,
            external_api_id=external_api_id,
            acquisition_path=AIRGRADIENT_AUTHENTICATED_PATH,
            timezone=timezone_name,
            allow_updates=models.UpdatePolicy.INHERIT,
        )
        session.add(device)
    else:
        # name is provider-owned identity. friendly_name remains administrator-
        # owned and is deliberately never changed during discovery.
        device.name = name
        if timezone_name:
            device.timezone = timezone_name

    if coordinate_pair is not None:
        set_device_location(
            session,
            device,
            latitude=coordinate_pair[0],
            longitude=coordinate_pair[1],
        )
    _apply_authenticated_attribution(device, api_device, place)
    session.add(device)
    session.flush()
    return device, created


def fetch_authenticated_locations(api_key: str, base_url: str) -> tuple[dict, list[dict]]:
    """Read the token's place and locations without importing or changing settings."""
    place = _authenticated_place_payload(
        _api_get(f"{base_url.rstrip('/')}/place", api_key)
    )
    locations = _authenticated_location_payloads(
        _api_get(f"{base_url.rstrip('/')}/locations/measures/current", api_key)
    )
    return place, locations


def _discover_authenticated_locations(
    session,
    source: models.ExternalAPI,
    api_key: str,
    base_url: str,
) -> dict:
    """Discover every location belonging to the authenticated AirGradient place.

    Primary contract verified against AirGradient's v1 Swagger document:
    GET /public/api/v1/place identifies the token's place, while
    GET /public/api/v1/locations/measures/current enumerates its locations.
    """

    if not _authenticated_import_enabled(source):
        return {"place_id": None, "locations_discovered": 0, "location_ids": [],
                "devices_created": 0, "sensors_created": 0}

    place, locations = fetch_authenticated_locations(api_key, base_url)

    devices_created = 0
    sensors_created = 0
    discovered_location_ids: list[str] = []
    for api_location in locations:
        device, created = _ensure_authenticated_device(
            session, api_location, place, source.external_api_id
        )
        if created:
            devices_created += 1
        sensors_created += _ensure_airgradient_sensors(
            session, device, api_location
        )
        discovered_location_ids.append(str(api_location["locationId"]))

    if not locations:
        _emit_event(
            "airgradient_authenticated_no_locations",
            "warning",
            message="AirGradient returned no locations for the authenticated place",
            payload={"place_id": str(place["id"])},
        )
    else:
        _emit_event(
            "airgradient_authenticated_discovery",
            message=(
                f"Discovered {len(locations)} authenticated AirGradient "
                f"location{'s' if len(locations) != 1 else ''}"
            ),
            payload={
                "place_id": str(place["id"]),
                "location_count": len(locations),
                "location_ids": discovered_location_ids,
                "devices_created": devices_created,
                "sensors_created": sensors_created,
            },
        )
    return {
        "place_id": str(place["id"]),
        "locations_discovered": len(locations),
        "location_ids": discovered_location_ids,
        "devices_created": devices_created,
        "sensors_created": sensors_created,
    }


def _approved_reference_location_ids() -> set[str]:
    return {
        str(reference_location["location_id"])
        for reference_location in AIRGRADIENT_REFERENCE_LOCATIONS
    }


def _authenticated_import_enabled(source: models.ExternalAPI) -> bool:
    # Absence preserves existing installations. Setup explicitly saves false
    # unless the administrator chooses to import their token-owned locations.
    enabled = (source.params or {}).get("import_authenticated_locations", bool(source.api_key or os.getenv("AIRGRADIENT_API_KEY")))
    if not isinstance(enabled, bool):
        raise AirGradientImporterError("import_authenticated_locations must be a boolean")
    return enabled


def _classify_legacy_airgradient_devices(
    session, source: models.ExternalAPI
) -> None:
    """Classify pre-migration AirGradient rows before path-specific upserts."""

    approved_reference_ids = _approved_reference_location_ids() | {"175911"}
    legacy_devices = session.scalars(
        select(models.Device).where(
            models.Device.external_api_id == source.external_api_id,
            models.Device.acquisition_path == "unspecified",
        )
    ).all()
    for device in legacy_devices:
        if str(device.external_id) in approved_reference_ids:
            device.acquisition_path = AIRGRADIENT_PUBLIC_REFERENCE_PATH
            device.license_code = AIRGRADIENT_PUBLIC_LICENSE_CODE
            device.license_url = AIRGRADIENT_PUBLIC_LICENSE_URL
            device.license_share_alike = True
        else:
            device.acquisition_path = AIRGRADIENT_AUTHENTICATED_PATH
        device.hardware_provider_name = "AirGradient"
        device.provider_url = AIRGRADIENT_PROVIDER_URL
        session.add(device)
    if legacy_devices:
        session.flush()


def _initialized_location_ids_from_prior_job_runs(
    session,
) -> tuple[set[str], bool]:
    """Recover per-location success from summaries written by the prior version.

    Commit 556869e wrote a global version marker but recorded per-location
    success only in JobRun summaries. Reading those summaries once prevents an
    already successful, later deleted location from being mistaken for a failed
    location during the params-state upgrade.
    """
    approved_location_ids = _approved_reference_location_ids()
    initialized_location_ids: set[str] = set()
    found_reference_initialization_summary = False
    summaries = session.scalars(
        select(models.JobRun.summary)
        .join(
            models.JobSchedule,
            models.JobRun.job_schedule_id == models.JobSchedule.job_schedule_id,
        )
        .where(models.JobSchedule.task == "airgradient_import")
    ).all()
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        if (
            "reference_locations_initialized" not in summary
            and "reference_locations_failed" not in summary
        ):
            continue
        found_reference_initialization_summary = True
        initialized_locations = summary.get("reference_locations_initialized")
        if not isinstance(initialized_locations, list):
            continue
        for initialized_location in initialized_locations:
            if not isinstance(initialized_location, dict):
                continue
            location_id = str(initialized_location.get("location_id") or "")
            if location_id in approved_location_ids:
                initialized_location_ids.add(location_id)
    return initialized_location_ids, found_reference_initialization_summary


def _initialized_reference_location_ids(
    session,
    source_params: dict,
) -> set[str]:
    """Load explicit success state, upgrading params from the prior version."""
    approved_location_ids = _approved_reference_location_ids()
    version = source_params.get("reference_locations_version")
    if (
        version != AIRGRADIENT_REFERENCE_LOCATIONS_VERSION
        and version not in _PRIOR_REFERENCE_LOCATION_IDS
    ):
        return set()

    stored_location_ids = source_params.get(
        _INITIALIZED_REFERENCE_LOCATION_IDS_PARAM
    )
    if isinstance(stored_location_ids, list):
        return {
            str(location_id)
            for location_id in stored_location_ids
            if str(location_id) in approved_location_ids
        }

    historical_location_ids, found_historical_summary = (
        _initialized_location_ids_from_prior_job_runs(session)
    )
    if found_historical_summary:
        return historical_location_ids

    # Without a prior summary, the old global marker cannot distinguish a
    # failed location from an administrator deletion. Conservatively treating
    # the prior version's approved locations as initialized preserves deletion ownership. The
    # explicit restore command remains available for this ambiguous legacy case.
    return approved_location_ids.intersection(
        _PRIOR_REFERENCE_LOCATION_IDS.get(version, approved_location_ids)
    )


def _ordered_initialized_reference_location_ids(
    initialized_location_ids: set[str],
) -> list[str]:
    """Persist successful IDs in the same readable order as the fixed config."""
    return [
        str(reference_location["location_id"])
        for reference_location in AIRGRADIENT_REFERENCE_LOCATIONS
        if str(reference_location["location_id"]) in initialized_location_ids
    ]


def _initialize_reference_locations(
    session,
    source: models.ExternalAPI,
    api_key: str,
    base_url: str,
    *,
    force: bool = False,
) -> dict:
    """Initialize fixed locations that have not previously succeeded."""
    source_params = dict(source.params or {})
    if force or source_params.get("reference_locations_version") != AIRGRADIENT_REFERENCE_LOCATIONS_VERSION:
        for region_code in AIRGRADIENT_UNAVAILABLE_REFERENCE_REGIONS:
            _emit_event(
                "airgradient_reference_region_unavailable",
                "warning",
                message=(f"No verified AirGradient public reference is configured for {region_code}; "
                         "no substitute device will be created"),
                payload={"region": region_code, "reason": "no_verified_public_location"},
            )
    initialized_location_ids = _initialized_reference_location_ids(
        session, source_params
    )
    for legacy_key in _LEGACY_REFERENCE_PARAM_KEYS:
        source_params.pop(legacy_key, None)

    locations_to_initialize = [
        reference_location
        for reference_location in AIRGRADIENT_REFERENCE_LOCATIONS
        if force
        or str(reference_location["location_id"])
        not in initialized_location_ids
    ]
    if not locations_to_initialize:
        source_params["reference_locations_version"] = (
            AIRGRADIENT_REFERENCE_LOCATIONS_VERSION
        )
        source_params[_INITIALIZED_REFERENCE_LOCATION_IDS_PARAM] = (
            _ordered_initialized_reference_location_ids(initialized_location_ids)
        )
        if source.params != source_params:
            source.params = source_params
            session.add(source)
            session.flush()
        return {
            "attempted": False,
            "devices_created": 0,
            "sensors_created": 0,
            "locations_initialized": [],
            "locations_failed": [],
            "measurements_by_location_id": {},
        }

    devices_created = 0
    sensors_created = 0
    locations_initialized: list[dict[str, str]] = []
    locations_failed: list[dict[str, str]] = []
    measurements_by_location_id: dict[str, list[dict]] = {}

    for reference_location in locations_to_initialize:
        region_code = str(reference_location["code"])
        region_label = str(reference_location["label"])
        location_id = str(reference_location["location_id"])
        try:
            current_payload = _api_get(
                f"{base_url.rstrip('/')}/world/locations/{location_id}/measures/current",
                api_key,
                include_token=False,
            )
            api_device = _reference_location_payload(current_payload, location_id)
            existing_device = session.scalar(
                select(models.Device).where(
                    models.Device.external_api_id == source.external_api_id,
                    models.Device.external_id == location_id,
                    models.Device.acquisition_path
                    == AIRGRADIENT_PUBLIC_REFERENCE_PATH,
                )
            )
            device = _ensure_reference_device(
                session,
                api_device,
                source.external_api_id,
                location_id,
                str(reference_location["timezone"]),
            )
            if existing_device is None:
                devices_created += 1
            sensors_created += _ensure_airgradient_sensors(
                session, device, api_device
            )
        except AirGradientImporterError as exc:
            failure = {
                "region": region_code,
                "location_id": location_id,
                "reason": str(exc),
            }
            locations_failed.append(failure)
            _emit_event(
                "airgradient_reference_location_error",
                "warning",
                message=(
                    f"AirGradient reference location {location_id} "
                    f"({region_label}) could not be loaded: {exc}"
                ),
                payload=failure,
            )
            continue

        locations_initialized.append(
            {
                "region": region_code,
                "location_id": location_id,
            }
        )
        initialized_location_ids.add(location_id)
        measurements_by_location_id[location_id] = [api_device]

    source_params["reference_locations_version"] = (
        AIRGRADIENT_REFERENCE_LOCATIONS_VERSION
    )
    source_params[_INITIALIZED_REFERENCE_LOCATION_IDS_PARAM] = (
        _ordered_initialized_reference_location_ids(initialized_location_ids)
    )
    if source.params != source_params:
        source.params = source_params
        session.add(source)
        session.flush()
    return {
        "attempted": True,
        "devices_created": devices_created,
        "sensors_created": sensors_created,
        "locations_initialized": locations_initialized,
        "locations_failed": locations_failed,
        "measurements_by_location_id": measurements_by_location_id,
    }


def _extract_measurements(raw: Any) -> List[dict]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        if "measurements" in raw and isinstance(raw["measurements"], list):
            return raw["measurements"]
        if "results" in raw and isinstance(raw["results"], list):
            return raw["results"]
                                   
        return [raw]
    if isinstance(raw, list):
        return raw
    return []


def _store_measurements(
    session,
    device: models.Device,
    measurements: List[dict],
    aggregation_period_id: Optional[int],
    sensor_lookup: Optional[dict] = None,
) -> Tuple[dict, dict, int, dict | None]:
    per_param = defaultdict(lambda: {"insert": 0, "update": 0, "skip": 0})
    overall = {"insert": 0, "update": 0, "skip": 0}
    measurements_received = 0
    qc_summary: dict = {}

    for m in measurements:
        observed_at = None
        for ts_key in ("timestamp", "time", "datetime", "createdAt", "created_at", "at"):
            observed_at = _parse_ts(m.get(ts_key))
            if observed_at:
                break
        selected_fields = _preferred_present_supported_fields(m)
        for param_code, provider_field in selected_fields.items():
            measurements_received += 1
            try:
                valf = float(m[provider_field])
            except (TypeError, ValueError):
                per_param[param_code]["skip"] += 1
                overall["skip"] += 1
                continue
            if observed_at is None:
                per_param[param_code]["skip"] += 1
                overall["skip"] += 1
                continue
            sensor = (
                sensor_lookup.get((param_code.lower(), provider_field.lower()))
                if sensor_lookup
                else None
            )
            if sensor is None:
                per_param[param_code]["skip"] += 1
                overall["skip"] += 1
                continue

            measurement = models.Measurement(
                sensor_id=sensor.sensor_id,
                value=valf,
                observed_at=observed_at,
            )
            if upsert_measurement_with_policy_detailed:
                upsert_result = upsert_measurement_with_policy_detailed(
                    session,
                    measurement,
                    device=device,
                    sensor=sensor,
                )
                action = upsert_result.action
                merge_qc_counts(qc_summary, upsert_result.qc)
            else:
                                                       
                existing = session.scalar(
                    select(models.Measurement.measurement_id).where(
                        models.Measurement.sensor_id == sensor.sensor_id,
                        models.Measurement.observed_at == observed_at,
                    )
                )
                if existing:
                    action = "skip"
                else:
                    session.add(measurement)
                    action = "insert"

            per_param[param_code][action] += 1
            overall[action] = overall.get(action, 0) + 1

    return per_param, overall, measurements_received, qc_summary.get("qc")


def _load_airgradient_config(
    session,
) -> Tuple[models.ExternalAPI, str, str]:
    row = session.scalars(
        select(models.ExternalAPI).where(
            models.ExternalAPI.provider_code == "airgradient"
        )
    ).one_or_none()
    if not row:
        raise AirGradientImporterError("ExternalAPI configuration for AirGradient not found")
    base_url = row.base_url if row and row.base_url else DEFAULT_BASE_URL
                                                                                                  
    if base_url.rstrip("/").endswith("/public/api"):
        base_url = base_url.rstrip("/") + "/v1"
    api_key = _get_api_key(session)
    if not api_key and _authenticated_import_enabled(row):
        raise AirGradientImporterError("AirGradient API key not configured in external_api or AIRGRADIENT_API_KEY env")
    return row, base_url, api_key or ""


def restore_airgradient_reference_locations(session) -> dict:
    """Explicitly restore the approved fixed AirGradient reference locations."""
    require_task_source_runnable(session, "airgradient_import")
    source, base_url, api_key = _load_airgradient_config(session)
    return _initialize_reference_locations(
        session, source, api_key, base_url, force=True
    )


@contextmanager
def _airgradient_run_lock(session):
    """Reuse PostgreSQL advisory locking for manual and scheduled subprocesses.

    A source-specific namespace avoids taking the scheduler's already-held
    schedule lock. SQLite is supported only for offline persistence tests.
    """
    engine = session.get_bind()
    if engine.dialect.name == "sqlite":
        yield
        return
    with postgres_advisory_lock(engine, 0x414752414449454E) as acquired:
        if not acquired:
            raise AirGradientImporterError("Another AirGradient import is already running")
        yield


def run_import(summary_json: Optional[str] = None, location_ids: Optional[List[int]] = None) -> dict:
    summary = new_import_summary()
    summary["per_parameter"] = {}
    summary["snapshot_locations_succeeded"] = 0
    summary["snapshot_locations_failed"] = 0
    try:
        _run_import(summary, location_ids)
    except AirGradientImporterError as exc:
        # Essential configuration/discovery failures still raise for direct
        # callers, but the subprocess must retain its diagnostics and progress.
        summary["acquisition_essential_failure"] = True
        summary.setdefault("errors", []).append(str(exc))
        raise
    except Exception as exc:
        summary["acquisition_essential_failure"] = True
        reason = f"AirGradient acquisition could not complete ({type(exc).__name__})"
        summary.setdefault("errors", []).append(reason)
        _emit_event("airgradient_fetch_error", "error", message=reason)
        raise
    finally:
        _finalize_acquisition_outcome(summary)
        write_import_summary(summary, summary_json)
    return summary


def _finalize_acquisition_outcome(summary: dict) -> None:
    """Use existing failed JobRuns for both complete and partial failures.

    Count completed acquisition work, never inserted rows: empty intervals and
    duplicate-only retrievals are successful. Bounded/deferred work is separate.
    """
    failed = (
        summary["snapshot_locations_failed"]
        + summary.get("history_intervals_failed", 0)
        + summary.get("history_location_failures", 0)
        + int(summary.get("acquisition_essential_failure", False))
    )
    succeeded = (
        summary["snapshot_locations_succeeded"]
        + summary.get("history_intervals_examined", 0)
        + int(summary.get("authenticated_empty_place", False))
    )
    if failed:
        outcome = "partial_failure" if succeeded else "failed"
    else:
        outcome = "success"
    summary["acquisition_outcome"] = outcome
    if outcome != "success":
        label = "partially failed" if outcome == "partial_failure" else "failed"
        reasons = list(dict.fromkeys(summary.get("errors", [])))
        summary["acquisition_error_message"] = (
            f"AirGradient acquisition {label}: {succeeded} completed, {failed} failed targets/windows. "
            + "; ".join(reasons)
        )[:1800]


def _run_import(summary: dict, location_ids: Optional[List[int]]) -> None:
    history_deadline = time.monotonic() + map_history.MAX_RUN_SECONDS
    history_now = datetime.now(timezone.utc)
    history_rate_limited = False
    with SessionLocal() as session, _airgradient_run_lock(session):
        require_task_source_runnable(session, "airgradient_import")
        try:
            source, base_url, api_key = _load_airgradient_config(session)
            authenticated_import_enabled = _authenticated_import_enabled(source)
        except AirGradientImporterError as exc:
            _emit_event("airgradient_config_error", "error", message=str(exc))
            raise

        try:
            _classify_legacy_airgradient_devices(session, source)
            initialization = _initialize_reference_locations(
                session, source, api_key, base_url
            )
            if initialization["attempted"]:
                summary["reference_regions_unavailable"] = list(AIRGRADIENT_UNAVAILABLE_REFERENCE_REGIONS)
                summary["devices_created"] += initialization["devices_created"]
                summary["sensors_created"] += initialization["sensors_created"]
                summary["reference_locations_initialized"] = initialization[
                    "locations_initialized"
                ]
                if initialization["locations_failed"]:
                    summary["reference_locations_failed"] = initialization[
                        "locations_failed"
                    ]
                    summary["snapshot_locations_failed"] += len(initialization["locations_failed"])
                    summary.setdefault("errors", []).extend(
                        f"Public location {failure['location_id']}: {failure['reason']}"
                        for failure in initialization["locations_failed"]
                    )
            session.commit()

            try:
                authenticated_discovery = _discover_authenticated_locations(
                    session, source, api_key, base_url
                )
            except AirGradientAuthenticationError as exc:
                session.rollback()
                _emit_event(
                    "airgradient_authentication_error",
                    "error",
                    message=str(exc),
                )
                raise
            except AirGradientRateLimit as exc:
                session.rollback()
                _emit_event(
                    "airgradient_rate_limit",
                    "warning",
                    message=str(exc),
                )
                raise
            except AirGradientProviderUnavailable as exc:
                session.rollback()
                _emit_event(
                    "airgradient_provider_unavailable",
                    "error",
                    message=str(exc),
                )
                raise
            except AirGradientMalformedResponse as exc:
                session.rollback()
                _emit_event(
                    "airgradient_malformed_response",
                    "error",
                    message=str(exc),
                )
                raise
            summary["import_authenticated_locations"] = authenticated_import_enabled
            summary["authenticated_place_id"] = authenticated_discovery["place_id"]
            summary["authenticated_locations_discovered"] = authenticated_discovery[
                "locations_discovered"
            ]
            if authenticated_import_enabled and not authenticated_discovery["locations_discovered"]:
                summary["authenticated_empty_place"] = True
            summary["authenticated_location_ids"] = authenticated_discovery[
                "location_ids"
            ]
            summary["devices_created"] += authenticated_discovery["devices_created"]
            summary["sensors_created"] += authenticated_discovery["sensors_created"]
            session.commit()

            initialization_measurements = initialization[
                "measurements_by_location_id"
            ]

            device_query = select(models.Device).where(
                models.Device.external_api_id == source.external_api_id
            )
            if location_ids:
                ids_as_str = [str(i) for i in location_ids]
                device_query = device_query.where(models.Device.external_id.in_(ids_as_str))
            devices = session.scalars(device_query).all()
            if not devices:
                _emit_event("airgradient_fetch_error", "warning", message="No AirGradient devices found in database")
                return

            for device in devices:
                if device.acquisition_path == AIRGRADIENT_AUTHENTICATED_PATH and not authenticated_import_enabled:
                    continue
                # Preserve the existing refresh of stored devices even when
                # initialization failed. Its final result replaces that target's
                # provisional failure, rather than counting the location twice.
                if device.acquisition_path == AIRGRADIENT_PUBLIC_REFERENCE_PATH:
                    for failure in initialization["locations_failed"]:
                        if failure["location_id"] == str(device.external_id):
                            summary["snapshot_locations_failed"] -= 1
                            summary["errors"].remove(
                                f"Public location {failure['location_id']}: {failure['reason']}"
                            )
                if not device.external_id:
                    _emit_event("airgradient_device_error", "error", device_id=device.device_id, message="Device missing external_id; skipping")
                    _record_snapshot_failure(summary, "Device missing external_id")
                    continue

                summary["devices_processed"] += 1

                try:
                    if (
                        device.acquisition_path == AIRGRADIENT_PUBLIC_REFERENCE_PATH
                        and device.external_id in initialization_measurements
                    ):
                        measurements = initialization_measurements[device.external_id]
                    elif device.acquisition_path == AIRGRADIENT_AUTHENTICATED_PATH:
                        mraw = _api_get(
                            f"{base_url}/locations/{device.external_id}/measures/current",
                            api_key,
                        )
                        measurements = [
                            _location_measurement_payload(
                                mraw,
                                str(device.external_id),
                                "authenticated location",
                            )
                        ]
                    elif device.acquisition_path == AIRGRADIENT_PUBLIC_REFERENCE_PATH:
                        # Retired references remain stored for administrator review,
                        # but cannot receive further observations as approved sites.
                        if str(device.external_id) not in _approved_reference_location_ids():
                            raise AirGradientImporterError(
                                f"AirGradient public reference {device.external_id} is no longer approved"
                            )
                        mraw = _api_get(
                            f"{base_url}/world/locations/{device.external_id}/measures/current",
                            api_key,
                            include_token=False,
                        )
                        measurements = [
                            _location_measurement_payload(
                                mraw,
                                str(device.external_id),
                                "reference location",
                            )
                        ]
                        _validate_public_reference_location(measurements[0], str(device.external_id))
                    else:
                        raise AirGradientImporterError(
                            "AirGradient device has unsupported acquisition path "
                            f"{device.acquisition_path}"
                        )
                except AirGradientRateLimit as exc:
                    _emit_event("airgradient_rate_limit", "warning", device_id=device.device_id, message=str(exc))
                    _record_snapshot_failure(summary, f"Location {device.external_id}: {exc}")
                    continue
                except AirGradientAuthenticationError as exc:
                    _emit_event(
                        "airgradient_authentication_error",
                        "error",
                        device_id=device.device_id,
                        message=str(exc),
                    )
                    _record_snapshot_failure(summary, f"Location {device.external_id}: {exc}")
                    continue
                except AirGradientProviderUnavailable as exc:
                    _emit_event(
                        "airgradient_provider_unavailable",
                        "error",
                        device_id=device.device_id,
                        message=str(exc),
                    )
                    _record_snapshot_failure(summary, f"Location {device.external_id}: {exc}")
                    continue
                except AirGradientMalformedResponse as exc:
                    _emit_event(
                        "airgradient_malformed_response",
                        "error",
                        device_id=device.device_id,
                        message=str(exc),
                    )
                    _record_snapshot_failure(summary, f"Location {device.external_id}: {exc}")
                    continue
                except AirGradientImporterError as exc:
                    event_type = (
                        "airgradient_reference_location_error"
                        if device.acquisition_path == AIRGRADIENT_PUBLIC_REFERENCE_PATH
                        else "airgradient_authenticated_location_import_error"
                    )
                    _emit_event(event_type, "error", device_id=device.device_id, message=str(exc))
                    _record_snapshot_failure(summary, f"Location {device.external_id}: {exc}")
                    continue

                for measurement_payload in measurements:
                    summary["sensors_created"] += _ensure_airgradient_sensors(
                        session, device, measurement_payload
                    )
                sensor_lookup = _sensor_lookup_for_measurements(
                    session, device, measurements
                )
                summary["sensors_processed"] += len(sensor_lookup)

                per_param, overall, measurements_received, qc_counts = _store_measurements(
                    session,
                    device,
                    measurements,
                    aggregation_period_id=None,
                    sensor_lookup=sensor_lookup,
                )
                session.commit()

                summary["measurements_received"] += measurements_received
                summary["snapshot_locations_succeeded"] += 1
                summary["measurements_inserted"] += overall.get("insert", 0)
                summary["measurements_updated"] += overall.get("update", 0)
                summary["measurements_skipped"] += overall.get("skip", 0)
                merge_qc_counts(summary, qc_counts)
                                 
                for p, ctr in per_param.items():
                    existing = summary["per_parameter"].get(p, {"insert": 0, "update": 0, "skip": 0})
                    for k in ("insert", "update", "skip"):
                        existing[k] = existing.get(k, 0) + ctr.get(k, 0)
                    summary["per_parameter"][p] = existing

                if device.acquisition_path == AIRGRADIENT_PUBLIC_REFERENCE_PATH and not history_rate_limited:
                    if time.monotonic() >= history_deadline:
                        summary["history_work_remaining"] = True
                        continue
                    failed_intervals_before = summary.get("history_intervals_failed", 0)
                    history_failures_before = len(summary.get("history_failures", []))
                    try:
                        import_location_history(session, device, measurements[0], summary,
                                                deadline=history_deadline, now=history_now)
                    except map_history.MapHistoryError as exc:
                        session.rollback()
                        if summary.get("history_intervals_failed", 0) == failed_intervals_before:
                            summary["history_location_failures"] = summary.get("history_location_failures", 0) + 1
                        summary.setdefault("errors", []).append(f"Public history {device.external_id}: {exc}")
                        _emit_event("airgradient_history_error", "warning", device_id=device.device_id, message=str(exc))
                        if isinstance(exc, map_history.MapHistoryRateLimit):
                            history_rate_limited = True
                            summary["history_work_remaining"] = True
                    for failure in summary.get("history_failures", [])[history_failures_before:]:
                        _emit_event(
                            "airgradient_history_error", "warning", device_id=device.device_id,
                            message=f"Map {failure['map_location_id']} {failure['parameter']}: {failure['reason']}",
                        )

        except (
            AirGradientAuthenticationError,
            AirGradientRateLimit,
            AirGradientProviderUnavailable,
            AirGradientMalformedResponse,
        ):
            raise
        except AirGradientImporterError as exc:
            _emit_event("airgradient_fetch_error", "error", message=str(exc))
            raise


def _record_snapshot_failure(summary: dict, reason: str) -> None:
    summary["snapshot_locations_failed"] += 1
    summary.setdefault("errors", []).append(reason)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AirGradient importer")
    parser.add_argument("--summary-json", dest="summary_json", default=None, help="Write summary JSON to this path")
    parser.add_argument("--location-id", dest="location_ids", action="append", type=int, default=None, help="Limit import to specific AirGradient location id (can be provided multiple times)")
    args = parser.parse_args()
    discovery.load_plugins()
    try:
        summary = run_import(summary_json=args.summary_json, location_ids=args.location_ids)
        print(json.dumps(summary, indent=2))
        if summary["acquisition_outcome"] != "success":
            # The JobRun retains committed progress in its summary and reports
            # this partial execution as failed so administrators can act on it.
            print(summary["acquisition_error_message"], file=sys.stderr)
            raise SystemExit(1)
    except AirGradientRateLimit as exc:
        print(f"AirGradient importer rate limited: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except AirGradientImporterError as exc:
        print(f"AirGradient importer failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        # Unexpected HTTP/database errors may contain request URLs or bound
        # values. Preserve their type and the saved summary, never their text.
        print(f"AirGradient importer failed ({type(exc).__name__}); see JobRun summary and System events.", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
