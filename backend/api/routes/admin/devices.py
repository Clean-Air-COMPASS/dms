from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from db import get_session
from models import Device, ExternalAPI, Measurement, Sensor, Parameter, Unit, AggregationPeriod, UpdatePolicy
from services.device_operational_status import (
  derive_device_operational_status,
)
from services.device_locations import (
  InvalidDeviceLocation,
  set_device_location,
  validate_coordinate_pair,
)
from services.external_sources import (
    ExternalSourceNotRunnable,
    require_task_source_runnable,
)
from services.provider_safety import (
    ProviderSafetyDenied,
    assert_paid_provider_http_authorized,
    paid_provider_request_scope,
    require_paid_provider_authorization,
)
from services.data_attribution import serialize_device_data_attribution

logger = logging.getLogger("admin.devices")

router = APIRouter(prefix="/admin", tags=["admin"])
OTHER_DATA_SOURCE_FILTER = "__other__"
OPENAQ_PROVIDER_URL = "https://openaq.org"
AIRGRADIENT_PROVIDER_URL = "https://www.airgradient.com"
CC_BY_4_LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"

                                                        
PA_DEVICE_FIELDS = ["name", "latitude", "longitude"]
PA_MEASUREMENT_FIELDS = ["pm2.5_atm", "pm10.0_atm"]


def _none_if_blank(val: Optional[object]) -> Optional[str]:
  if val is None:
    return None
  s = str(val).strip()
  return s if s else None


def _coerce_policy(val: Optional[str]) -> UpdatePolicy:
  """
  Convert user-supplied string to UpdatePolicy; default to INHERIT.
  """
  if not val:
    return UpdatePolicy.INHERIT
  try:
    return UpdatePolicy(val)
  except Exception:
    return UpdatePolicy.INHERIT


def _resolve_default_external_api_id(session: Session) -> int:
  """
  Resolve the default ExternalAPI FK for manual devices.
  Prefer a source named "Local" when present, otherwise use the first available row.
  """
  local_api_id = session.execute(
    select(ExternalAPI.external_api_id)
    .where(func.lower(ExternalAPI.name) == "local")
    .limit(1)
  ).scalar_one_or_none()
  if local_api_id is not None:
    return local_api_id

  fallback = session.execute(
    select(ExternalAPI.external_api_id)
    .order_by(ExternalAPI.external_api_id.asc())
    .limit(1)
  ).scalar_one_or_none()
  if fallback is None:
    raise HTTPException(status_code=400, detail="No ExternalAPI records available; seed at least one first.")
  return fallback


def _resolve_device_data_source(
  session: Session,
  external_api_id: Optional[int],
  network: Optional[str],
  current_external_api_id: Optional[int] = None,
) -> tuple[int, Optional[str]]:
  """
  Resolve the managed ExternalAPI FK plus optional device-level custom source label.
  - explicit external_api_id: use that managed source and clear custom label
  - network matching an existing ExternalAPI name: use that managed source and clear custom label
  - network not matching a managed source: preserve current FK when available, otherwise use default FK,
    and store the network value as manual device metadata
  - neither provided: use default managed source and clear custom label
  """
  if external_api_id:
    exists = session.execute(
      select(ExternalAPI.external_api_id).where(ExternalAPI.external_api_id == external_api_id)
    ).scalar_one_or_none()
    if not exists:
      raise HTTPException(status_code=400, detail=f"external_api_id {external_api_id} not found")
    return external_api_id, None

  normalized_network = _none_if_blank(network)
  if normalized_network:
    match = session.execute(
      select(ExternalAPI.external_api_id).where(func.lower(ExternalAPI.name) == normalized_network.lower())
    ).scalar_one_or_none()
    if match is not None:
      return match, None
    return current_external_api_id or _resolve_default_external_api_id(session), normalized_network

  return current_external_api_id or _resolve_default_external_api_id(session), None


def _serialize_device(
  device: Device,
  external_api_name: Optional[str] = None,
  last_seen_at: Optional[datetime] = None,
  expected_frequency_seconds: Optional[int] = None,
  evaluated_at: Optional[datetime] = None,
) -> dict:
                                                                                    
  is_external = bool(getattr(device, "external_id", None))
  resolved_network = getattr(device, "manual_data_source_name", None) or external_api_name
  return {
    "device_id": device.device_id,
    "name": device.name,
    "friendly_name": getattr(device, "friendly_name", None),
    "external_id": getattr(device, "external_id", None),
    "external_api_id": getattr(device, "external_api_id", None),
    "external_api_name": external_api_name,
    "manual_data_source_name": getattr(device, "manual_data_source_name", None),
    "network": resolved_network,
    "acquisition_path": getattr(device, "acquisition_path", "unspecified"),
    "hardware_provider_name": getattr(device, "hardware_provider_name", None),
    "provider_url": getattr(device, "provider_url", None),
    "contributor_name": getattr(device, "contributor_name", None),
    "contributor_url": getattr(device, "contributor_url", None),
    "license_code": getattr(device, "license_code", None),
    "license_url": getattr(device, "license_url", None),
    "license_share_alike": getattr(device, "license_share_alike", None),
    "data_attribution": serialize_device_data_attribution(device, resolved_network),
    "latitude": getattr(device, "latitude", None),
    "longitude": getattr(device, "longitude", None),
    "timezone": getattr(device, "timezone", None),
    "allow_updates": getattr(device, "allow_updates", UpdatePolicy.INHERIT).value if getattr(device, "allow_updates", None) else UpdatePolicy.INHERIT.value,
    "created_at": device.created_at.isoformat() if getattr(device, "created_at", None) else None,
    "status": derive_device_operational_status(
      last_seen_at,
      expected_frequency_seconds,
      evaluated_at=evaluated_at,
    ),
    "last_seen_at": last_seen_at.isoformat() if last_seen_at else None,
    "is_external": is_external,
  }


def _latest_device_measurement_subquery():
  """Return one latest observation and its sensor cadence per measured device."""
  latest_observation_by_sensor = (
    select(
      Sensor.device_id.label("device_id"),
      Sensor.sensor_id.label("sensor_id"),
      Sensor.expected_frequency_seconds.label("expected_frequency_seconds"),
      func.max(Measurement.observed_at).label("last_seen_at"),
    )
    .join(Measurement, Measurement.sensor_id == Sensor.sensor_id)
    .group_by(
      Sensor.device_id,
      Sensor.sensor_id,
      Sensor.expected_frequency_seconds,
    )
    .having(func.max(Measurement.observed_at).is_not(None))
    .subquery("latest_observation_by_sensor")
  )

  ranked_sensor_observations = select(
    latest_observation_by_sensor.c.device_id,
    latest_observation_by_sensor.c.last_seen_at,
    latest_observation_by_sensor.c.expected_frequency_seconds,
    func.row_number().over(
      partition_by=latest_observation_by_sensor.c.device_id,
      order_by=(
        latest_observation_by_sensor.c.last_seen_at.desc(),
        latest_observation_by_sensor.c.sensor_id.asc(),
      ),
    ).label("freshness_rank"),
  ).subquery("ranked_sensor_observations")

  return (
    select(
      ranked_sensor_observations.c.device_id,
      ranked_sensor_observations.c.last_seen_at,
      ranked_sensor_observations.c.expected_frequency_seconds,
    )
    .where(ranked_sensor_observations.c.freshness_rank == 1)
    .subquery("latest_device_measurement")
  )


def _device_record_query():
  latest_device_measurement = _latest_device_measurement_subquery()
  return (
    select(
      Device,
      ExternalAPI.name.label("external_api_name"),
      latest_device_measurement.c.last_seen_at,
      latest_device_measurement.c.expected_frequency_seconds,
    )
    .join(ExternalAPI, ExternalAPI.external_api_id == Device.external_api_id, isouter=True)
    .join(
      latest_device_measurement,
      latest_device_measurement.c.device_id == Device.device_id,
      isouter=True,
    )
  )


def _serialize_sensor_admin(
  sensor: Sensor,
  parameter: Optional[Parameter] = None,
  aggregation_period: Optional[AggregationPeriod] = None,
) -> dict:
  return {
    "sensor_id": sensor.sensor_id,
    "device_id": sensor.device_id,
    "parameter_code": parameter.code if parameter else None,
    "parameter_name": parameter.display_name if parameter else None,
    "external_sensor_id": sensor.external_sensor_id,
    "aggregation_code": aggregation_period.code if aggregation_period else None,
    "hourly_concentration_provenance": sensor.hourly_concentration_provenance,
    "hourly_timestamp_semantics": sensor.hourly_timestamp_semantics,
    "expected_frequency_seconds": sensor.expected_frequency_seconds,
    "measurement_duration_seconds": sensor.measurement_duration_seconds,
    "source_aggregation_duration_seconds": sensor.source_aggregation_duration_seconds,
    "measurement_timestamp_semantics": sensor.measurement_timestamp_semantics,
    "measurement_metadata_status": sensor.measurement_metadata_status,
    "measurement_metadata_managed_by": sensor.measurement_metadata_managed_by,
    "acquisition_metadata": sensor.acquisition_metadata,
    "unit_id": sensor.unit_id,
  }


IMPORTER_MANAGED_MEASUREMENT_METADATA_FIELDS = {
  "expected_frequency_seconds",
  "measurement_duration_seconds",
  "source_aggregation_duration_seconds",
  "measurement_timestamp_semantics",
  "measurement_metadata_status",
  "measurement_metadata_managed_by",
  "acquisition_metadata",
  "acquisition_examined_until",
}


def _reject_importer_managed_measurement_metadata(payload: dict) -> None:
  requested_fields = sorted(
    IMPORTER_MANAGED_MEASUREMENT_METADATA_FIELDS.intersection(payload)
  )
  if requested_fields:
    raise HTTPException(
      status_code=400,
      detail=(
        "Provider measurement metadata is read-only and importer-managed. "
        f"Remove these fields: {', '.join(requested_fields)}"
      ),
    )


@router.get("/devices")
def list_devices_admin(
  name: Optional[str] = Query(None),
  search: Optional[str] = Query(None, max_length=200),
  network: Optional[str] = Query(None),
  external_device_id: Optional[str] = Query(None),
  external_sensor_id: Optional[str] = Query(None),
  sensor_id: Optional[int] = Query(None),
  status: Optional[Literal["active", "inactive", "unknown"]] = Query(None),
  page: Optional[int] = Query(None),
  page_size: Optional[int] = Query(None),
  session: Session = Depends(get_session),
):
  """
  Lightweight admin listing of devices. Supports basic filters used by the frontend.
  """
  stmt = _device_record_query().order_by(Device.created_at.desc())

  if name:
    stmt = stmt.where(Device.name.ilike(f"%{name}%"))
  # CSV destination lookup: search before pagination. Keep the established
  # individual filters intact for existing administration callers.
  if search and search.strip():
    term = search.strip()
    internal_id = int(term) if term.isascii() and term.isdecimal() and len(term) <= 10 else None
    if internal_id is not None and not 1 <= internal_id <= 2_147_483_647:
      internal_id = None
    sensor_matches = select(Sensor.device_id).outerjoin(Parameter).where(or_(
      Sensor.external_sensor_id.ilike(f"%{term}%"),
      Parameter.display_name.ilike(f"%{term}%"),
      Parameter.code.ilike(f"%{term}%"),
      Sensor.sensor_id == internal_id if internal_id is not None else False,
    ))
    stmt = stmt.where(or_(
      Device.name.ilike(f"%{term}%"),
      Device.friendly_name.ilike(f"%{term}%"),
      Device.external_id.ilike(f"%{term}%"),
      Device.device_id == internal_id if internal_id is not None else False,
      Device.device_id.in_(sensor_matches),
    ))
  if network:
    if network == OTHER_DATA_SOURCE_FILTER:
      stmt = stmt.where(Device.manual_data_source_name.is_not(None))
    else:
      stmt = stmt.where(
        func.lower(
          func.coalesce(Device.manual_data_source_name, ExternalAPI.name)
        ) == network.lower()
      )

                                              
  if external_device_id:
    stmt = stmt.where(Device.external_id == external_device_id.strip())

                                
  if sensor_id is not None:
    stmt = stmt.where(
      Device.device_id.in_(
        select(Sensor.device_id).where(Sensor.sensor_id == sensor_id)
      )
    )

                                              
  if external_sensor_id:
    sensor_val = external_sensor_id.strip()
    if sensor_val:
      stmt = stmt.where(
        Device.device_id.in_(
          select(Sensor.device_id).where(Sensor.external_sensor_id == sensor_val)
        )
      )

  rows = session.execute(stmt).all()
  evaluated_at = datetime.now(timezone.utc)
  records = [
    _serialize_device(row[0], row[1], row[2], row[3], evaluated_at)
    for row in rows
  ]
  if status:
    records = [record for record in records if record["status"] == status]

  if page_size:
    safe_size = max(page_size, 1)
    start = max(page or 0, 0) * safe_size
    records = records[start:start + safe_size]
  return records


@router.get("/devices/{device_id}")
def get_device_admin(device_id: int, session: Session = Depends(get_session)):
  row = session.execute(
    _device_record_query()
    .where(Device.device_id == device_id)
  ).first()
  if not row:
    raise HTTPException(status_code=404, detail="Device not found")
  return _serialize_device(row[0], row[1], row[2], row[3])


@router.post("/devices")
def create_device_admin(payload: dict, session: Session = Depends(get_session)):
  name = (payload.get("name") or "").strip()
  if not name:
    raise HTTPException(status_code=400, detail="Name is required")

  ext_api_id, manual_data_source_name = _resolve_device_data_source(
    session,
    payload.get("external_api_id"),
    payload.get("network"),
  )

  device = Device(
    name=name,
    friendly_name=_none_if_blank(payload.get("friendly_name")),
    external_id=_none_if_blank(payload.get("external_id")),
    external_api_id=ext_api_id,
    manual_data_source_name=manual_data_source_name,
    timezone=_none_if_blank(payload.get("timezone")),
    allow_updates=_coerce_policy(payload.get("allow_updates")),
  )

  session.add(device)
  try:
    set_device_location(
      session,
      device,
      latitude=payload.get("latitude"),
      longitude=payload.get("longitude"),
    )
    session.commit()
  except InvalidDeviceLocation as exc:
    session.rollback()
    raise HTTPException(
      status_code=400,
      detail={"reason": exc.reason, "message": str(exc)},
    ) from exc
  except IntegrityError as exc:
    session.rollback()
    raise HTTPException(status_code=409, detail=f"Database constraint error while creating device: {exc.orig}")
  session.refresh(device)

  api_name = session.execute(
    select(ExternalAPI.name).where(ExternalAPI.external_api_id == device.external_api_id)
  ).scalar_one_or_none()
  return _serialize_device(device, api_name)


@router.put("/devices/{device_id}")
def update_device_admin(device_id: int, payload: dict, session: Session = Depends(get_session)):
  device = session.get(Device, device_id)
  if not device:
    raise HTTPException(status_code=404, detail="Device not found")

                                                           
  is_external = bool(device.external_id)

                                    
  if "friendly_name" in payload:
    device.friendly_name = _none_if_blank(payload.get("friendly_name"))

                                                                   
  if not is_external:
    if "name" in payload:
      name = (payload.get("name") or "").strip()
      if not name:
        raise HTTPException(status_code=400, detail="Name is required")
      device.name = name

    if "external_id" in payload:
      requested_external_id = _none_if_blank(payload.get("external_id"))
      if requested_external_id != device.external_id:
        raise HTTPException(
          status_code=400,
          detail="external_id is immutable; delete and recreate the device to change provider identity",
        )

    if "latitude" in payload or "longitude" in payload:
      try:
        set_device_location(
          session,
          device,
          latitude=payload.get("latitude", device.latitude),
          longitude=payload.get("longitude", device.longitude),
        )
      except InvalidDeviceLocation as exc:
        session.rollback()
        raise HTTPException(
          status_code=400,
          detail={"reason": exc.reason, "message": str(exc)},
        ) from exc

    if "timezone" in payload:
      device.timezone = _none_if_blank(payload.get("timezone"))

    if "external_api_id" in payload or "network" in payload:
      requested_external_api_id, requested_manual_source_name = _resolve_device_data_source(
        session,
        payload.get("external_api_id"),
        payload.get("network"),
        current_external_api_id=device.external_api_id,
      )
      if requested_external_api_id != device.external_api_id:
        raise HTTPException(
          status_code=400,
          detail="external_api_id is immutable; delete and recreate the device to change provider identity",
        )
      device.manual_data_source_name = requested_manual_source_name

                                                   
  if "allow_updates" in payload:
    device.allow_updates = _coerce_policy(payload.get("allow_updates"))

  try:
    session.commit()
  except InvalidDeviceLocation as exc:
    session.rollback()
    raise HTTPException(
      status_code=400,
      detail={"reason": exc.reason, "message": str(exc)},
    ) from exc
  except IntegrityError as exc:
    session.rollback()
    raise HTTPException(status_code=409, detail=f"Database constraint error while updating device: {exc.orig}")

  updated_record = session.execute(
    _device_record_query().where(Device.device_id == device_id)
  ).one()
  return _serialize_device(
    updated_record[0],
    updated_record[1],
    updated_record[2],
    updated_record[3],
  )


@router.delete("/devices/{device_id}")
def delete_device_admin(device_id: int, session: Session = Depends(get_session)):
  device = session.get(Device, device_id)
  if not device:
    raise HTTPException(status_code=404, detail="Device not found")
  session.delete(device)
  session.commit()
  return {"status": "deleted"}


@router.post("/devices/{device_id}/sensors")
def create_device_sensor_admin(device_id: int, payload: dict, session: Session = Depends(get_session)):
  """
  Create a sensor for an existing device (manual admin workflow).
  Payload:
  - parameter_code: required canonical parameter code (e.g., 'pm25')
  - external_sensor_id: optional provider/alias id
  - aggregation_code: optional aggregation period code (e.g., '1m', '1h')
  """
  device = session.get(Device, device_id)
  if not device:
    raise HTTPException(status_code=404, detail="Device not found")
  _reject_importer_managed_measurement_metadata(payload)

  parameter_code = str(payload.get("parameter_code") or "").strip().lower()
  if not parameter_code:
    raise HTTPException(status_code=400, detail="parameter_code is required")

  parameter = session.execute(
    select(Parameter).where(func.lower(Parameter.code) == parameter_code)
  ).scalar_one_or_none()
  if not parameter:
    raise HTTPException(status_code=400, detail=f"Unknown parameter_code '{parameter_code}'")

  aggregation_period_id: Optional[int] = None
  aggregation_code = payload.get("aggregation_code")
  if aggregation_code is not None and str(aggregation_code).strip() != "":
    agg = session.execute(
      select(AggregationPeriod).where(func.lower(AggregationPeriod.code) == str(aggregation_code).strip().lower())
    ).scalar_one_or_none()
    if not agg:
      raise HTTPException(status_code=400, detail=f"Unknown aggregation_code '{aggregation_code}'")
    aggregation_period_id = agg.aggregation_period_id

  sensor = Sensor(
    device_id=device_id,
    parameter_id=parameter.parameter_id,
    unit_id=parameter.default_unit_id,
    external_sensor_id=(str(payload.get("external_sensor_id") or "").strip() or None),
    aggregation_period_id=aggregation_period_id,
    hourly_concentration_provenance=_none_if_blank(
      payload.get("hourly_concentration_provenance")
    ),
    hourly_timestamp_semantics=_none_if_blank(
      payload.get("hourly_timestamp_semantics")
    ),
    allow_updates=UpdatePolicy.INHERIT,
  )
  session.add(sensor)
  session.commit()
  session.refresh(sensor)

  return _serialize_sensor_admin(sensor, parameter, agg if aggregation_code else None)


@router.put("/devices/{device_id}/sensors/{sensor_id}")
def update_device_sensor_admin(device_id: int, sensor_id: int, payload: dict, session: Session = Depends(get_session)):
  sensor = session.get(Sensor, sensor_id)
  if not sensor or sensor.device_id != device_id:
    raise HTTPException(status_code=404, detail="Sensor not found")
  if "external_sensor_id" in payload:
    requested_external_sensor_id = _none_if_blank(payload.get("external_sensor_id"))
    if requested_external_sensor_id != sensor.external_sensor_id:
      raise HTTPException(
        status_code=400,
        detail="external_sensor_id is immutable; delete and recreate the sensor to change provider identity",
      )
  _reject_importer_managed_measurement_metadata(payload)

  parameter: Optional[Parameter] = None
  if "parameter_code" in payload:
    parameter_code = str(payload.get("parameter_code") or "").strip().lower()
    if not parameter_code:
      raise HTTPException(status_code=400, detail="parameter_code is required")
    parameter = session.execute(
      select(Parameter).where(func.lower(Parameter.code) == parameter_code)
    ).scalar_one_or_none()
    if not parameter:
      raise HTTPException(status_code=400, detail=f"Unknown parameter_code '{parameter_code}'")
    sensor.parameter_id = parameter.parameter_id
    sensor.unit_id = parameter.default_unit_id
  elif sensor.parameter_id:
    parameter = session.get(Parameter, sensor.parameter_id)

  if "external_sensor_id" in payload:
    sensor.external_sensor_id = _none_if_blank(payload.get("external_sensor_id"))
  if "hourly_concentration_provenance" in payload:
    sensor.hourly_concentration_provenance = _none_if_blank(
      payload.get("hourly_concentration_provenance")
    )
  if "hourly_timestamp_semantics" in payload:
    sensor.hourly_timestamp_semantics = _none_if_blank(
      payload.get("hourly_timestamp_semantics")
    )

  aggregation_period: Optional[AggregationPeriod] = None
  if "aggregation_code" in payload:
    aggregation_code = str(payload.get("aggregation_code") or "").strip().lower()
    if aggregation_code:
      aggregation_period = session.execute(
        select(AggregationPeriod).where(func.lower(AggregationPeriod.code) == aggregation_code)
      ).scalar_one_or_none()
      if not aggregation_period:
        raise HTTPException(status_code=400, detail=f"Unknown aggregation_code '{aggregation_code}'")
      sensor.aggregation_period_id = aggregation_period.aggregation_period_id
    else:
      sensor.aggregation_period_id = None
  elif sensor.aggregation_period_id:
    aggregation_period = session.get(AggregationPeriod, sensor.aggregation_period_id)

  try:
    session.commit()
  except IntegrityError as exc:
    session.rollback()
    raise HTTPException(status_code=409, detail=f"Database constraint error while updating sensor: {exc.orig}")
  session.refresh(sensor)

  if parameter is None and sensor.parameter_id:
    parameter = session.get(Parameter, sensor.parameter_id)
  if aggregation_period is None and sensor.aggregation_period_id:
    aggregation_period = session.get(AggregationPeriod, sensor.aggregation_period_id)

  return _serialize_sensor_admin(sensor, parameter, aggregation_period)


@router.delete("/devices/{device_id}/sensors/{sensor_id}")
def delete_device_sensor_admin(device_id: int, sensor_id: int, session: Session = Depends(get_session)):
  sensor = session.get(Sensor, sensor_id)
  if not sensor or sensor.device_id != device_id:
    raise HTTPException(status_code=404, detail="Sensor not found")
  session.delete(sensor)
  session.commit()
  return {"status": "deleted", "sensor_id": sensor_id}


                                                                            
                                                      
                                                                            

def _lookup_timezone(lat: Optional[float], lon: Optional[float]) -> Optional[str]:
    """Return IANA timezone for coordinates, or None when unavailable."""
    try:
        from timezonefinder import TimezoneFinder
        if lat is None or lon is None:
            return None
        return TimezoneFinder().timezone_at(lat=lat, lng=lon)
    except Exception:
        return None


def _get_purpleair_api_key(session: Session) -> Optional[str]:
    """Retrieve PurpleAir API key from external_api table or environment."""
    import os
    record = session.execute(
        select(ExternalAPI).where(ExternalAPI.provider_code == "purpleair")
    ).scalar_one_or_none()
    if record and record.api_key:
        return record.api_key
    return os.getenv("PURPLEAIR_API_KEY")


def _get_purpleair_external_api_id(session: Session) -> Optional[int]:
    """Return the external_api_id for PurpleAir, or None if not configured."""
    record = session.execute(
        select(ExternalAPI.external_api_id).where(ExternalAPI.provider_code == "purpleair")
    ).scalar_one_or_none()
    return record


@router.post("/devices/purpleair/lookup")
def lookup_purpleair_sensor(payload: dict, session: Session = Depends(get_session)):
    """
    Lookup PurpleAir sensor metadata by sensor_index.
    Uses minimal fields to conserve API points.
    Returns device and sensor info ready to be saved.
    """
    sensor_index = str(payload.get("sensor_index") or "").strip()
    if not sensor_index or not sensor_index.isdigit():
        raise HTTPException(status_code=400, detail="sensor_index must be a numeric string")

    try:
        authorization = require_paid_provider_authorization(
            session,
            "PurpleAir",
            explicit_manual_authorization=bool(payload.get("allow_paid_api", False)),
        )
    except ProviderSafetyDenied as exc:
        raise HTTPException(status_code=403, detail=exc.as_detail()) from exc

    api_key = _get_purpleair_api_key(session)
    if not api_key:
        raise HTTPException(status_code=400, detail="PurpleAir API key not configured")

                                                     
    existing = session.execute(
        select(Device).where(Device.external_id == sensor_index)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Device with external_id '{sensor_index}' already exists (device_id={existing.device_id})"
        )

                              
    fields = PA_DEVICE_FIELDS + PA_MEASUREMENT_FIELDS
    url = f"https://api.purpleair.com/v1/sensors/{sensor_index}"
    headers = {"X-API-Key": api_key}
    params = {"fields": ",".join(fields)}

    try:
        with paid_provider_request_scope(authorization):
            assert_paid_provider_http_authorized("PurpleAir")
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
    except requests.HTTPError as exc:
        logger.error("PurpleAir lookup failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"PurpleAir API error: {exc}")
    except requests.RequestException as exc:
        logger.error("PurpleAir lookup request error: %s", exc)
        raise HTTPException(status_code=502, detail=f"PurpleAir API request failed: {exc}")

    data = resp.json()
    sensor_obj = data.get("sensor", {})

    name = sensor_obj.get("name") or f"purpleair-{sensor_index}"
    lat = sensor_obj.get("latitude")
    lon = sensor_obj.get("longitude")

    try:
        coordinate_pair = validate_coordinate_pair(lat, lon)
    except InvalidDeviceLocation as exc:
        raise HTTPException(
            status_code=502,
            detail={"reason": exc.reason, "message": str(exc)},
        ) from exc
    lat, lon = coordinate_pair if coordinate_pair is not None else (None, None)

    timezone = _lookup_timezone(lat, lon)

                                       
    sensors = []
    for code, field in [("pm25", "pm2.5_atm"), ("pm10", "pm10.0_atm")]:
        value = sensor_obj.get(field)
        sensors.append({
            "parameter_code": code,
            "external_sensor_id": f"{sensor_index}:{field}",
            "latest_value": float(value) if value is not None else None,
            "unit_code": "ug_m3",
        })

    external_api_id = _get_purpleair_external_api_id(session)

    return {
        "device": {
            "name": name,
            "external_id": sensor_index,
            "external_api_id": external_api_id,
            "latitude": lat,
            "longitude": lon,
            "timezone": timezone,
        },
        "sensors": sensors,
    }


@router.post("/devices/purpleair/create")
def create_purpleair_device(payload: dict, session: Session = Depends(get_session)):
    """
    Create a PurpleAir device and its sensors from lookup data.
    Expects payload with 'device' and 'sensors' keys matching lookup response.
    """
    device_data = payload.get("device")
    sensors_data = payload.get("sensors", [])

    if not device_data:
        raise HTTPException(status_code=400, detail="device data is required")

    name = (device_data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Device name is required")

    external_id = device_data.get("external_id")
    external_api_id = device_data.get("external_api_id")
    if external_id:
        existing = session.execute(
            select(Device).where(
                Device.external_api_id == external_api_id,
                Device.external_id == str(external_id),
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Device with external_id '{external_id}' already exists"
            )

                   
    device = Device(
        name=name,
        external_id=device_data.get("external_id"),
        external_api_id=external_api_id,
        timezone=device_data.get("timezone"),
        allow_updates=UpdatePolicy.INHERIT,
    )
    session.add(device)
    try:
        set_device_location(
            session,
            device,
            latitude=device_data.get("latitude"),
            longitude=device_data.get("longitude"),
        )
    except InvalidDeviceLocation as exc:
        session.rollback()
        raise HTTPException(
            status_code=400,
            detail={"reason": exc.reason, "message": str(exc)},
        ) from exc

                                                           
    agg_period = session.execute(
        select(AggregationPeriod).where(func.lower(AggregationPeriod.code) == "2m")
    ).scalar_one_or_none()
    agg_period_id = agg_period.aggregation_period_id if agg_period else None

                    
    unit = session.execute(
        select(Unit).where(func.lower(Unit.code) == "ug_m3")
    ).scalar_one_or_none()
    unit_id = unit.unit_id if unit else None

                    
    created_sensors = []
    for s_data in sensors_data:
        param_code = s_data.get("parameter_code")
        if not param_code:
            continue

                          
        param = session.execute(
            select(Parameter).where(func.lower(Parameter.code) == param_code.lower())
        ).scalar_one_or_none()
        param_id = param.parameter_id if param else None

        sensor = Sensor(
            device_id=device.device_id,
            parameter_id=param_id,
            external_sensor_id=s_data.get("external_sensor_id"),
            aggregation_period_id=agg_period_id,
            unit_id=unit_id,
            expected_frequency_seconds=120,
            measurement_duration_seconds=120,
            source_aggregation_duration_seconds=120,
            measurement_timestamp_semantics="provider_received_at",
            measurement_metadata_status="provider_documented",
            measurement_metadata_managed_by="purpleair_importer",
        )
        session.add(sensor)
        session.flush()
        created_sensors.append({
            "sensor_id": sensor.sensor_id,
            "parameter_code": param_code,
            "external_sensor_id": sensor.external_sensor_id,
        })

    session.commit()

    api_name = session.execute(
        select(ExternalAPI.name).where(ExternalAPI.external_api_id == device.external_api_id)
    ).scalar_one_or_none()

    return {
        "device": _serialize_device(device, api_name),
        "sensors": created_sensors,
    }


                                                                            
                                                               
                                                                            

OPENAQ_LOCATIONS_URL = "https://api.openaq.org/v3/locations"


def _get_openaq_api_key(session: Session) -> Optional[str]:
    """Retrieve OpenAQ API key from external_api table or environment."""
    import os
    record = session.execute(
        select(ExternalAPI).where(ExternalAPI.provider_code == "openaq")
    ).scalar_one_or_none()
    if record and record.api_key:
        return record.api_key
    return os.getenv("OPENAQ_API_KEY")


def _get_openaq_external_api_id(session: Session) -> Optional[int]:
    """Return the external_api_id for OpenAQ, or None if not configured."""
    record = session.execute(
        select(ExternalAPI.external_api_id).where(ExternalAPI.provider_code == "openaq")
    ).scalar_one_or_none()
    return record


_SUBSCRIPT_DIGITS = str.maketrans(
    {
        "₀": "0",
        "₁": "1",
        "₂": "2",
        "₃": "3",
        "₄": "4",
        "₅": "5",
        "₆": "6",
        "₇": "7",
        "₈": "8",
        "₉": "9",
    }
)


def _normalize_parameter_code(value: object) -> str:
    """
    Normalize parameter codes from upstream/UI to our canonical `parameter.code`.

    Handles:
    - Unicode subscripts (e.g., "SO₂ mass" -> "so2")
    - Dots/underscores (e.g., "pm2.5" / "pm2_5" -> "pm25")
    - Leading label text (e.g., "NO mass" -> "no")
    """
    if value is None:
        return ""
    s = str(value).strip().lower()
    if not s:
        return ""
    s = s.translate(_SUBSCRIPT_DIGITS)
                                                                 
    s = s.split()[0]
                                                                                
    s = "".join(ch for ch in s if ch.isalnum() or ch in {".", "_"})
    s = s.replace(".", "").replace("_", "")
    return s


def _normalize_unit_key(value: object) -> str:
    """
    Normalize unit strings so visually-similar micro/mu and superscripts match.
    """
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    s = s.replace("µ", "u").replace("μ", "u").replace("³", "3")
    return s.lower()


def _default_display_name_for_parameter(code: str, fallback: object = None) -> str:
    if fallback:
        f = str(fallback).strip()
        if f:
            return f[:64]
    specials = {
        "pm25": "PM2.5",
        "pm10": "PM10",
        "pm1": "PM1",
        "o3": "O₃",
        "no2": "NO₂",
        "so2": "SO₂",
        "nox": "NOx",
        "no": "NO",
        "co": "CO",
    }
    return (specials.get(code) or code.upper())[:64]


def _serialize_openaq_location(loc: dict, external_api_id: Optional[int], existing_sensor_ids: set[str] | None = None) -> dict:
    """Transform a single OpenAQ /v3/locations result into our lookup format."""
    existing_sensor_ids = existing_sensor_ids or set()
    loc_id = str(loc.get("id") or "")
    name = loc.get("name") or f"OpenAQ-{loc_id}"
    coords = loc.get("coordinates") or {}
    lat = coords.get("latitude")
    lon = coords.get("longitude")
    tz = loc.get("timezone")
    
                         
    sensors = []
    for s in loc.get("sensors") or []:
        param_obj = s.get("parameter") or {}
        sid = s.get("id")
        sensors.append({
            "sensor_id": sid,
            "name": s.get("name") or param_obj.get("displayName") or param_obj.get("name"),
            "parameter_code": param_obj.get("name"),
            "parameter_display": param_obj.get("displayName"),
            "unit": param_obj.get("units"),
            "exists": str(sid) in existing_sensor_ids if sid is not None else False,
        })
    
                                  
    country = loc.get("country") or {}
    provider = loc.get("provider") or {}
    owner = loc.get("owner") or {}
    datetime_first = loc.get("datetimeFirst") or {}
    datetime_last = loc.get("datetimeLast") or {}
    
    return {
        "device": {
            "external_id": loc_id,
            "name": name,
            "external_api_id": external_api_id,
            "latitude": lat,
            "longitude": lon,
            "timezone": tz,
        },
        "sensors": sensors,
        "metadata": {
            "locality": loc.get("locality"),
            "country_name": country.get("name"),
            "country_code": country.get("code"),
            "provider_name": provider.get("name"),
            "owner_name": owner.get("name"),
            "instruments": loc.get("instruments") or [],
            "licenses": loc.get("licenses") or [],
            "is_monitor": loc.get("isMonitor"),
            "is_mobile": loc.get("isMobile"),
            "datetime_first_utc": datetime_first.get("utc"),
            "datetime_last_utc": datetime_last.get("utc"),
        },
    }


def _apply_openaq_device_attribution(device: Device, metadata: dict) -> None:
    """Preserve OpenAQ transport, hardware origin, and supplied license facts."""

    provider_name = str(metadata.get("provider_name") or "")
    owner_name = str(metadata.get("owner_name") or "")
    instrument_names = [
        str(instrument.get("name") or "")
        for instrument in metadata.get("instruments") or []
        if isinstance(instrument, dict)
    ]
    airgradient_evidence = " ".join(
        [provider_name, owner_name, *instrument_names]
    ).lower()

    licenses = [
        license_entry
        for license_entry in metadata.get("licenses") or []
        if isinstance(license_entry, dict)
    ]
    license_entry = next(
        (
            candidate
            for candidate in licenses
            if candidate.get("dateTo") in (None, "")
        ),
        licenses[0] if licenses else {},
    )
    attribution = license_entry.get("attribution") or {}
    license_name = str(license_entry.get("name") or "").strip() or None

    device.acquisition_path = "openaq"
    device.provider_url = OPENAQ_PROVIDER_URL
    device.hardware_provider_name = (
        "AirGradient" if "airgradient" in airgradient_evidence else None
    )
    device.contributor_name = (
        attribution.get("name") if isinstance(attribution, dict) else None
    ) or (owner_name or None)
    device.contributor_url = (
        attribution.get("url") if isinstance(attribution, dict) else None
    )
    device.license_code = license_name
    device.license_url = None
    device.license_share_alike = None

    # AirGradient's current data-sharing terms explicitly identify its data
    # transported through OpenAQ as CC-BY 4.0. Use that primary-source fact only
    # when OpenAQ metadata identifies AirGradient hardware and does not provide
    # a more specific active license URL.
    if device.hardware_provider_name == "AirGradient":
        device.license_code = license_name or "CC-BY-4.0"
        device.license_url = CC_BY_4_LICENSE_URL
        device.license_share_alike = False


@router.post("/devices/openaq/lookup")
def lookup_openaq_locations(payload: dict, session: Session = Depends(get_session)):
    """
    Lookup OpenAQ locations by bounding box or location ID.
    
    Payload options:
    - bbox: string in format "min_lon,min_lat,max_lon,max_lat"
    - location_id: single OpenAQ location ID
    
    Returns list of locations with device and sensor info.
    """
    try:
        require_task_source_runnable(session, "openaq_import")
    except ExternalSourceNotRunnable as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.state.runnable_reason.value},
        ) from exc

    bbox = (payload.get("bbox") or "").strip()
    location_id = (payload.get("location_id") or "").strip()
    
    if not bbox and not location_id:
        raise HTTPException(status_code=400, detail="Either bbox or location_id is required")
    
    api_key = _get_openaq_api_key(session)
    headers = {"X-API-Key": api_key} if api_key else {}
    
    params = {"limit": 100}
    if bbox:
                              
        parts = bbox.split(",")
        if len(parts) != 4:
            raise HTTPException(
                status_code=400,
                detail="Invalid bbox format. Expected: min_lon,min_lat,max_lon,max_lat"
            )
        try:
            [float(p.strip()) for p in parts]
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid bbox values. All coordinates must be numbers."
            )
        params["bbox"] = bbox
    elif location_id:
        if not location_id.isdigit():
            raise HTTPException(status_code=400, detail="location_id must be numeric")
        params["id"] = location_id
    
    try:
        resp = requests.get(OPENAQ_LOCATIONS_URL, headers=headers, params=params, timeout=30)
        
        if resp.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail="OpenAQ rate limit reached. Please try again later."
            )
        
        resp.raise_for_status()
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail="OpenAQ rate limit reached. Please try again later."
            )
        logger.error("OpenAQ lookup failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"OpenAQ API error: {exc}")
    except requests.RequestException as exc:
        logger.error("OpenAQ lookup request error: %s", exc)
        raise HTTPException(status_code=502, detail=f"OpenAQ API request failed: {exc}")
    
    data = resp.json()
    results = data.get("results") or []
    
    if not results:
        if location_id:
            raise HTTPException(status_code=404, detail=f"No location found with ID {location_id}")
        return {"locations": []}
    
    external_api_id = _get_openaq_external_api_id(session)

                                                   
    existing_ext_ids = set()
    ext_ids_to_check = [str(r.get("id")) for r in results if r.get("id")]
    sensor_ids_to_check = [
        str(s.get("id"))
        for r in results
        for s in (r.get("sensors") or [])
        if s.get("id")
    ]
    if ext_ids_to_check:
        existing_rows = session.execute(
            select(Device.external_id).where(Device.external_id.in_(ext_ids_to_check))
        ).scalars().all()
        existing_ext_ids = set(existing_rows)
    existing_sensor_ids = set()
    if sensor_ids_to_check:
        existing_sensor_rows = session.execute(
            select(Sensor.external_sensor_id).where(Sensor.external_sensor_id.in_(sensor_ids_to_check))
        ).scalars().all()
        existing_sensor_ids = set(str(x) for x in existing_sensor_rows if x is not None)

    locations = []
    for loc in results:
        serialized = _serialize_openaq_location(loc, external_api_id, existing_sensor_ids)
        serialized["already_exists"] = serialized["device"]["external_id"] in existing_ext_ids
        locations.append(serialized)

    return {"locations": locations}


OPENAQ_SENSORS_URL = "https://api.openaq.org/v3/sensors"


def _serialize_openaq_sensor_result(sensor_data: dict, external_api_id: Optional[int]) -> dict:
    """
    Transform a single OpenAQ /v3/sensors/{id} result into our lookup format.
    The sensor endpoint returns sensor info with coordinates in latest.coordinates.
    """
    sensor_id = str(sensor_data.get("id") or "")
    sensor_name = sensor_data.get("name") or ""
    param_obj = sensor_data.get("parameter") or {}
    latest_obj = sensor_data.get("latest") or {}
    latest_coords = latest_obj.get("coordinates") or {}
    datetime_first = sensor_data.get("datetimeFirst") or {}
    datetime_last = sensor_data.get("datetimeLast") or {}
    coverage = sensor_data.get("coverage") or {}
    summary = sensor_data.get("summary") or {}
    
    lat = latest_coords.get("latitude")
    lon = latest_coords.get("longitude")
    
                                           
    device_name = sensor_name or f"OpenAQ Sensor {sensor_id}"
    
    return {
        "device": {
            "external_id": sensor_id,
            "name": device_name,
            "external_api_id": external_api_id,
            "latitude": lat,
            "longitude": lon,
            "timezone": None,                                            
        },
        "sensors": [{
            "sensor_id": int(sensor_id) if sensor_id.isdigit() else 0,
            "name": sensor_name or param_obj.get("displayName") or param_obj.get("name"),
            "parameter_code": param_obj.get("name"),
            "parameter_display": param_obj.get("displayName"),
            "unit": param_obj.get("units"),
            "exists": False,                                            
        }],
        "metadata": {
            "locality": None,
            "country_name": None,
            "country_code": None,
            "provider_name": None,
            "owner_name": None,
            "is_monitor": None,
            "is_mobile": None,
            "datetime_first_utc": datetime_first.get("utc"),
            "datetime_last_utc": datetime_last.get("utc"),
            "latest_value": latest_obj.get("value"),
            "latest_datetime_utc": (latest_obj.get("datetime") or {}).get("utc"),
            "coverage_percent": coverage.get("percentComplete"),
            "observed_count": coverage.get("observedCount"),
            "expected_count": coverage.get("expectedCount"),
            "summary_min": summary.get("min"),
            "summary_max": summary.get("max"),
            "summary_avg": summary.get("avg"),
        },
    }


@router.post("/devices/openaq/lookup/sensor")
def lookup_openaq_sensor(payload: dict, session: Session = Depends(get_session)):
    """
    Lookup a single OpenAQ sensor by sensor ID.
    Uses the /v3/sensors/{sensor_id} endpoint.
    
    Returns sensor info with device and sensor data formatted for creation.
    """
    try:
        require_task_source_runnable(session, "openaq_import")
    except ExternalSourceNotRunnable as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.state.runnable_reason.value},
        ) from exc

    sensor_id = (payload.get("sensor_id") or "").strip()
    
    if not sensor_id:
        raise HTTPException(status_code=400, detail="sensor_id is required")
    
    if not sensor_id.isdigit():
        raise HTTPException(status_code=400, detail="sensor_id must be numeric")
    
    api_key = _get_openaq_api_key(session)
    headers = {"X-API-Key": api_key} if api_key else {}
    
    url = f"{OPENAQ_SENSORS_URL}/{sensor_id}"
    
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        
        if resp.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail="OpenAQ rate limit reached. Please try again later."
            )
        
        if resp.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail="Sensor not found."
            )
        
        resp.raise_for_status()
    except requests.HTTPError as exc:
        if exc.response is not None:
            if exc.response.status_code == 429:
                raise HTTPException(
                    status_code=429,
                    detail="OpenAQ rate limit reached. Please try again later."
                )
            if exc.response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail="Sensor not found."
                )
        logger.error("OpenAQ sensor lookup failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"OpenAQ API error: {exc}")
    except requests.RequestException as exc:
        logger.error("OpenAQ sensor lookup request error: %s", exc)
        raise HTTPException(status_code=502, detail=f"OpenAQ API request failed: {exc}")
    
    data = resp.json()
    results = data.get("results") or []
    
    if not results:
        raise HTTPException(status_code=404, detail="Sensor not found.")
    
    sensor_data = results[0]
    external_api_id = _get_openaq_external_api_id(session)

    serialized = _serialize_openaq_sensor_result(sensor_data, external_api_id)

                                           
    external_id = serialized["device"]["external_id"]
    existing_device = session.execute(
        select(Device).where(Device.external_id == external_id)
    ).scalar_one_or_none()
    serialized["already_exists"] = existing_device is not None
                                                               
    sensor_exists = session.execute(
        select(Sensor.sensor_id).where(Sensor.external_sensor_id == external_id).limit(1)
    ).scalar_one_or_none()
    if serialized.get("sensors"):
        serialized["sensors"][0]["exists"] = sensor_exists is not None

    return {"locations": [serialized]}


@router.post("/devices/openaq/create")
def create_openaq_devices(payload: dict, session: Session = Depends(get_session)):
    """
    Create OpenAQ devices and sensors from lookup data.
    
    Expects payload with 'locations' key containing array of location objects,
    each with 'device' and 'sensors' (matching lookup response format).
    Can also accept 'selected_sensors' map of device_external_id -> [sensor_ids] for partial selection.
    """
    locations = payload.get("locations") or []
    selected_sensors = payload.get("selected_sensors") or {}                                       
    
    if not locations:
        raise HTTPException(status_code=400, detail="No locations provided")

    openaq_external_api_id = _get_openaq_external_api_id(session)
    if openaq_external_api_id is None:
        raise HTTPException(
            status_code=400,
            detail="OpenAQ is not configured in external_api; seed ExternalAPI(name='OpenAQ') first.",
        )
    
                                                              
    agg_period = session.execute(
        select(AggregationPeriod).where(func.lower(AggregationPeriod.code) == "1h")
    ).scalar_one_or_none()
    agg_period_id = agg_period.aggregation_period_id if agg_period else None
    
                                           
    param_rows = session.execute(select(Parameter.code, Parameter.parameter_id, Parameter.default_unit_id)).all()
    param_map: dict[str, int] = {}
    param_default_unit_map: dict[str, int] = {}
    for code, parameter_id, default_unit_id in param_rows:
        norm = _normalize_parameter_code(code)
        if norm and parameter_id:
            param_map[norm] = parameter_id
        if norm and default_unit_id:
            param_default_unit_map[norm] = default_unit_id
    
                                              
    unit_rows = session.execute(select(Unit.code, Unit.symbol, Unit.unit_id)).all()
    unit_map: dict[str, int] = {}
    for code, symbol, unit_id in unit_rows:
        if code:
            unit_map[_normalize_unit_key(code)] = unit_id
        if symbol:
            unit_map[_normalize_unit_key(symbol)] = unit_id
    
    created_devices = []

    try:
        for loc in locations:
            device_data = loc.get("device") if isinstance(loc, dict) else None
            sensors_data = (loc.get("sensors") or []) if isinstance(loc, dict) else []
            source_metadata = (loc.get("metadata") or {}) if isinstance(loc, dict) else {}

            if not isinstance(device_data, dict):
                continue

            external_id = str(device_data.get("external_id") or "").strip()
            if not external_id:
                continue

                                           
            existing = session.execute(
                select(Device).where(Device.external_id == external_id)
            ).scalar_one_or_none()
            if existing:
                continue

            name = (device_data.get("name") or "").strip() or f"OpenAQ-{external_id}"

                                                                                                                      
            device = Device(
                name=name,
                external_id=external_id,
                external_api_id=openaq_external_api_id,
                timezone=device_data.get("timezone"),
                allow_updates=UpdatePolicy.INHERIT,
            )
            _apply_openaq_device_attribution(device, source_metadata)
            session.add(device)
            set_device_location(
                session,
                device,
                latitude=device_data.get("latitude"),
                longitude=device_data.get("longitude"),
            )

                                               
            sensors_to_create = sensors_data
            if external_id in selected_sensors:
                raw_allowed = selected_sensors.get(external_id) or []
                allowed_sensor_ids = {int(x) for x in raw_allowed if str(x).isdigit()}
                sensors_to_create = [s for s in sensors_data if s.get("sensor_id") in allowed_sensor_ids]

                            
            created_sensors = []
            for s_data in sensors_to_create:
                if not isinstance(s_data, dict):
                    continue
                raw_param_code = s_data.get("parameter_code")
                param_code = _normalize_parameter_code(raw_param_code)
                if not param_code:
                    param_code = _normalize_parameter_code(s_data.get("parameter_display"))
                if not param_code:
                    param_code = _normalize_parameter_code(s_data.get("name"))
                if not param_code:
                    continue

                                                                               
                ext_sensor_id = str(s_data.get("sensor_id") or "").strip()
                if ext_sensor_id:
                    existing_sensor = session.execute(
                        select(Sensor.sensor_id).where(Sensor.external_sensor_id == ext_sensor_id).limit(1)
                    ).scalar_one_or_none()
                    if existing_sensor:
                        continue

                                     
                param_id = param_map.get(param_code)

                                
                unit_str = str(s_data.get("unit") or "")
                unit_key = _normalize_unit_key(unit_str)
                unit_id = unit_map.get(unit_key) if unit_key else None

                                                                    
                if param_id is None:
                    default_unit_id = unit_id or param_default_unit_map.get(param_code)
                    if default_unit_id is None:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Unknown parameter '{raw_param_code}' (normalized='{param_code}') and unit '{unit_str}'; seed them first.",
                        )

                    display_name = _default_display_name_for_parameter(param_code, s_data.get("parameter_display"))
                    stmt = (
                        pg_insert(Parameter.__table__)
                        .values(code=param_code, display_name=display_name, default_unit_id=default_unit_id)
                        .on_conflict_do_nothing(index_elements=[Parameter.__table__.c.code])
                        .returning(Parameter.__table__.c.parameter_id, Parameter.__table__.c.default_unit_id)
                    )
                    row = session.execute(stmt).first()
                    if row:
                        param_id = int(row[0])
                        param_map[param_code] = param_id
                        param_default_unit_map[param_code] = int(row[1])
                    else:
                        existing_param = session.execute(
                            select(Parameter.parameter_id, Parameter.default_unit_id).where(Parameter.code == param_code)
                        ).first()
                        if not existing_param:
                            raise HTTPException(
                                status_code=400,
                                detail=f"Unable to resolve or create parameter '{param_code}'.",
                            )
                        param_id = int(existing_param[0])
                        param_map[param_code] = param_id
                        param_default_unit_map[param_code] = int(existing_param[1])

                if unit_id is None:
                    unit_id = param_default_unit_map.get(param_code)

                sensor = Sensor(
                    device_id=device.device_id,
                    parameter_id=param_id,
                    external_sensor_id=ext_sensor_id,
                    aggregation_period_id=agg_period_id,
                    unit_id=unit_id,
                )
                session.add(sensor)
                session.flush()
                created_sensors.append({
                    "sensor_id": sensor.sensor_id,
                    "parameter_code": param_code,
                    "external_sensor_id": sensor.external_sensor_id,
                })

            api_name = session.execute(
                select(ExternalAPI.name).where(ExternalAPI.external_api_id == device.external_api_id)
            ).scalar_one_or_none()

            created_devices.append({
                "device": _serialize_device(device, api_name),
                "sensors": created_sensors,
            })

        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except InvalidDeviceLocation as exc:
        session.rollback()
        raise HTTPException(
            status_code=400,
            detail={"reason": exc.reason, "message": str(exc)},
        ) from exc
    except IntegrityError as exc:
        session.rollback()
        logger.exception("OpenAQ create failed due to DB integrity error")
        raise HTTPException(status_code=409, detail=f"Database constraint error while creating OpenAQ devices: {exc.orig}")
    
    return {
        "created": created_devices,
        "count": len(created_devices),
    }
