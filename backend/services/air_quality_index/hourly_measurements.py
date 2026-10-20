from __future__ import annotations

"""Measurement retrieval helpers with explicit aggregation ownership.

Stored ``Measurement.observed_at`` timestamps are treated as UTC instants.
Device-local timezones remain provenance only and are not used for bucketing.

AQI paths retrieve ``RawMeasurementInput`` rows and qualify completeness before
classification. The legacy arithmetic-mean helpers remain diagnostic utilities;
their averages alone do not establish eligibility for EEA classification.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import AggregationPeriod, Device, ExternalAPI, Measurement, Parameter, Sensor, Unit
from services.device_locations import device_bbox_predicate


MANUAL_SOURCE_LABEL = "Other"
_ONE_HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class EeaAveragedHourlyMeasurementInput:
    """One EEA sensor stream averaged over one completed UTC clock hour."""

    device_id: int
    device_name: str
    device_friendly_name: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    device_timezone: Optional[str]
    source_name: Optional[str]
    observed_at: datetime
    parameter_code: str
    sensor_id: int
    external_sensor_id: Optional[str]
    sensor_aggregation_period: Optional[str]
    input_unit_code: Optional[str]
    input_unit_symbol: Optional[str]
    hourly_concentration: float
    measurement_ids: Tuple[int, ...]
    sample_count: int
    timestamps_at_hour_start: bool
    measurement_timestamp_semantics: Optional[str]


@dataclass(frozen=True)
class RawMeasurementInput:
    """One stored measurement before any hourly averaging or AQI decision."""

    measurement_id: int
    sensor_id: int
    observed_at: datetime
    concentration: float
    is_valid: bool


@dataclass(frozen=True)
class HourlySensorStreamMetadata:
    """Provider-neutral metadata needed to construct hourly sensor inputs."""

    sensor_id: int
    external_sensor_id: Optional[str]
    aggregation_period: Optional[str]
    hourly_concentration_provenance: Optional[str]
    hourly_timestamp_semantics: Optional[str]
    expected_frequency_seconds: Optional[int]
    measurement_duration_seconds: Optional[int]
    source_aggregation_duration_seconds: Optional[int]
    measurement_timestamp_semantics: Optional[str]
    measurement_metadata_status: Optional[str]
    measurement_metadata_managed_by: Optional[str]
    input_unit_code: Optional[str]
    input_unit_symbol: Optional[str]
    parameter_code: str
    device_id: int
    device_name: str
    device_friendly_name: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    device_timezone: Optional[str]
    source_name: Optional[str]


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def floor_utc_hour(value: datetime) -> datetime:
    return normalize_utc(value).replace(minute=0, second=0, microsecond=0)


def represented_utc_hour(
    observed_at: datetime,
    *,
    timestamp_semantics: str,
) -> datetime:
    """Return the UTC hour represented by an explicitly qualified timestamp."""
    observed = normalize_utc(observed_at)
    floored = floor_utc_hour(observed)
    if (
        timestamp_semantics in {"interval_end", "provider_received_at", "hour_end"}
        and observed == floored
    ):
        return floored - _ONE_HOUR
    return floored


def ceil_utc_hour(value: datetime) -> datetime:
    normalized = normalize_utc(value)
    floored = floor_utc_hour(normalized)
    return floored if normalized == floored else floored + _ONE_HOUR


def _apply_filters(
    statement,
    *,
    parameter_codes: Sequence[str],
    device_id: Optional[int],
    external_api_name: Optional[str],
    bbox: Optional[Tuple[float, float, float, float]],
    device_ids: Optional[Sequence[int]] = None,
):
    statement = statement.where(func.lower(Parameter.code).in_(tuple(parameter_codes)))
    if device_id is not None:
        statement = statement.where(Device.device_id == device_id)
    elif device_ids is not None:
        if not device_ids:
            return statement.where(False)
        statement = statement.where(Device.device_id.in_(tuple(device_ids)))

    normalized_source = (external_api_name or "").strip().lower()
    if normalized_source == MANUAL_SOURCE_LABEL.lower():
        statement = statement.where(Device.manual_data_source_name.is_not(None))
    elif normalized_source:
        statement = statement.where(
            Device.manual_data_source_name.is_(None),
            func.lower(ExternalAPI.name) == normalized_source,
        )

    if bbox is not None:
        statement = statement.where(
            device_bbox_predicate(Device.location, bbox)
        )
    return statement


def retrieve_candidate_sensor_streams(
    session: Session,
    *,
    parameter_codes: Sequence[str],
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    device_ids: Optional[Sequence[int]] = None,
) -> list[HourlySensorStreamMetadata]:
    """Return sensor metadata without requiring a provider-specific identity."""
    statement = (
        select(
            Sensor.sensor_id,
            Sensor.external_sensor_id,
            AggregationPeriod.code.label("aggregation_period"),
            Sensor.hourly_concentration_provenance,
            Sensor.hourly_timestamp_semantics,
            Sensor.expected_frequency_seconds,
            Sensor.measurement_duration_seconds,
            Sensor.source_aggregation_duration_seconds,
            Sensor.measurement_timestamp_semantics,
            Sensor.measurement_metadata_status,
            Sensor.measurement_metadata_managed_by,
            Unit.code.label("unit_code"),
            Unit.symbol.label("unit_symbol"),
            Parameter.code.label("parameter_code"),
            Device.device_id,
            Device.name.label("device_name"),
            Device.friendly_name,
            Device.latitude,
            Device.longitude,
            Device.timezone.label("device_timezone"),
            Device.manual_data_source_name,
            ExternalAPI.name.label("external_api_name"),
        )
        .join(Parameter, Sensor.parameter_id == Parameter.parameter_id)
        .join(Device, Sensor.device_id == Device.device_id)
        .outerjoin(
            AggregationPeriod,
            Sensor.aggregation_period_id == AggregationPeriod.aggregation_period_id,
        )
        .outerjoin(Unit, Sensor.unit_id == Unit.unit_id)
        .outerjoin(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id)
    )
    statement = _apply_filters(
        statement,
        parameter_codes=parameter_codes,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        device_ids=device_ids,
    )
    rows = session.execute(statement).all()
    return [
        HourlySensorStreamMetadata(
            sensor_id=int(row.sensor_id),
            external_sensor_id=row.external_sensor_id,
            aggregation_period=row.aggregation_period,
            hourly_concentration_provenance=row.hourly_concentration_provenance,
            hourly_timestamp_semantics=row.hourly_timestamp_semantics,
            expected_frequency_seconds=row.expected_frequency_seconds,
            measurement_duration_seconds=row.measurement_duration_seconds,
            source_aggregation_duration_seconds=row.source_aggregation_duration_seconds,
            measurement_timestamp_semantics=row.measurement_timestamp_semantics,
            measurement_metadata_status=row.measurement_metadata_status,
            measurement_metadata_managed_by=row.measurement_metadata_managed_by,
            input_unit_code=row.unit_code,
            input_unit_symbol=row.unit_symbol,
            parameter_code=str(row.parameter_code).strip().lower(),
            device_id=int(row.device_id),
            device_name=row.device_name,
            device_friendly_name=row.friendly_name,
            latitude=row.latitude,
            longitude=row.longitude,
            device_timezone=row.device_timezone,
            source_name=(
                MANUAL_SOURCE_LABEL
                if row.manual_data_source_name
                else row.external_api_name
            ),
        )
        for row in sorted(rows, key=lambda item: item.sensor_id)
    ]


def _measurement_rows_statement():
    return (
        select(
            Measurement.measurement_id,
            Measurement.value,
            Measurement.observed_at,
            Sensor.sensor_id,
            Sensor.external_sensor_id,
            Parameter.code.label("parameter_code"),
            Unit.code.label("unit_code"),
            Unit.symbol.label("unit_symbol"),
            AggregationPeriod.code.label("aggregation_period"),
            Sensor.hourly_timestamp_semantics,
            Sensor.measurement_timestamp_semantics,
            Device.device_id,
            Device.name.label("device_name"),
            Device.friendly_name,
            Device.latitude,
            Device.longitude,
            Device.timezone.label("device_timezone"),
            Device.manual_data_source_name,
            ExternalAPI.name.label("external_api_name"),
        )
        .join(Sensor, Measurement.sensor_id == Sensor.sensor_id)
        .join(Parameter, Sensor.parameter_id == Parameter.parameter_id)
        .join(Device, Sensor.device_id == Device.device_id)
        .outerjoin(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id)
        .outerjoin(Unit, Sensor.unit_id == Unit.unit_id)
        .outerjoin(
            AggregationPeriod,
            Sensor.aggregation_period_id == AggregationPeriod.aggregation_period_id,
        )
        .where(Measurement.is_valid.is_(True), Measurement.observed_at.is_not(None))
    )


def _raw_measurement_rows_statement():
    return (
        select(
            Measurement.measurement_id,
            Measurement.value,
            Measurement.observed_at,
            Measurement.is_valid,
            Sensor.sensor_id,
            Parameter.code.label("parameter_code"),
            Device.device_id,
            Device.manual_data_source_name,
            ExternalAPI.name.label("external_api_name"),
        )
        .join(Sensor, Measurement.sensor_id == Sensor.sensor_id)
        .join(Parameter, Sensor.parameter_id == Parameter.parameter_id)
        .join(Device, Sensor.device_id == Device.device_id)
        .outerjoin(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id)
        .where(Measurement.observed_at.is_not(None))
    )


def retrieve_raw_measurement_inputs(
    session: Session,
    *,
    parameter_codes: Sequence[str],
    start_utc: datetime,
    end_utc: datetime,
    include_end: bool = False,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    sensor_ids: Optional[Sequence[int]] = None,
    device_ids: Optional[Sequence[int]] = None,
) -> list[RawMeasurementInput]:
    """Return stored rows without averaging or filtering invalid measurements."""
    start = normalize_utc(start_utc)
    end = normalize_utc(end_utc)
    if start > end or (start == end and not include_end):
        return []
    if sensor_ids is not None and not sensor_ids:
        return []
    end_condition = (
        Measurement.observed_at <= end
        if include_end
        else Measurement.observed_at < end
    )
    statement = _raw_measurement_rows_statement().where(
        Measurement.observed_at >= start,
        end_condition,
    )
    if sensor_ids is not None:
        statement = statement.where(Sensor.sensor_id.in_(tuple(sensor_ids)))
    statement = _apply_filters(
        statement,
        parameter_codes=parameter_codes,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        device_ids=device_ids,
    )
    rows = session.execute(statement).all()
    return [
        RawMeasurementInput(
            measurement_id=int(row.measurement_id),
            sensor_id=int(row.sensor_id),
            observed_at=normalize_utc(row.observed_at),
            concentration=float(row.value),
            is_valid=bool(row.is_valid),
        )
        for row in sorted(
            rows,
            key=lambda item: (
                normalize_utc(item.observed_at),
                item.sensor_id,
                item.measurement_id,
            ),
        )
    ]


def retrieve_latest_valid_observed_at_by_sensor(
    session: Session,
    *,
    parameter_codes: Sequence[str],
    completed_before_utc: datetime,
    include_boundary: bool,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    include_invalid: bool = False,
) -> dict[int, datetime]:
    """Find latest timestamps; optionally retain invalid rows for failure diagnostics."""
    completed_before = normalize_utc(completed_before_utc)
    boundary_condition = (
        Measurement.observed_at <= completed_before
        if include_boundary
        else Measurement.observed_at < completed_before
    )
    statement = (
        select(
            Sensor.sensor_id,
            func.max(Measurement.observed_at).label("latest_observed_at"),
        )
        .join(Sensor, Measurement.sensor_id == Sensor.sensor_id)
        .join(Parameter, Sensor.parameter_id == Parameter.parameter_id)
        .join(Device, Sensor.device_id == Device.device_id)
        .outerjoin(ExternalAPI, Device.external_api_id == ExternalAPI.external_api_id)
        .where(
            Measurement.observed_at.is_not(None),
            boundary_condition,
        )
    )
    if not include_invalid:
        statement = statement.where(Measurement.is_valid.is_(True))
    statement = _apply_filters(
        statement,
        parameter_codes=parameter_codes,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
    ).group_by(Sensor.sensor_id)
    return {
        int(row.sensor_id): normalize_utc(row.latest_observed_at)
        for row in session.execute(statement).all()
        if row.latest_observed_at is not None
    }


def _average_rows_for_eea(
    rows,
) -> list[EeaAveragedHourlyMeasurementInput]:
    """Preserve the established EEA hourly arithmetic-mean behavior."""
    grouped: dict[tuple[int, datetime, str, int], dict] = {}
    for row in rows:
        timestamp_semantics = (
            row.hourly_timestamp_semantics
            or row.measurement_timestamp_semantics
            or "hour_start"
        )
        hour_start = represented_utc_hour(
            row.observed_at,
            timestamp_semantics=timestamp_semantics,
        )
        parameter_code = str(row.parameter_code).strip().lower()
        key = (row.device_id, hour_start, parameter_code, row.sensor_id)
        group = grouped.setdefault(
            key,
            {
                "row": row,
                "values": [],
                "measurement_ids": [],
                "timestamps_at_hour_start": True,
                "measurement_timestamp_semantics": timestamp_semantics,
            },
        )
        group["values"].append(float(row.value))
        group["measurement_ids"].append(int(row.measurement_id))
        if normalize_utc(row.observed_at) != hour_start:
            group["timestamps_at_hour_start"] = False

    inputs: list[EeaAveragedHourlyMeasurementInput] = []
    for (device_id, hour_start, parameter_code, sensor_id), group in grouped.items():
        row = group["row"]
        values = group["values"]
        source_name = MANUAL_SOURCE_LABEL if row.manual_data_source_name else row.external_api_name
        inputs.append(
            EeaAveragedHourlyMeasurementInput(
                device_id=device_id,
                device_name=row.device_name,
                device_friendly_name=row.friendly_name,
                latitude=row.latitude,
                longitude=row.longitude,
                device_timezone=row.device_timezone,
                source_name=source_name,
                observed_at=hour_start,
                parameter_code=parameter_code,
                sensor_id=sensor_id,
                external_sensor_id=row.external_sensor_id,
                sensor_aggregation_period=row.aggregation_period,
                input_unit_code=row.unit_code,
                input_unit_symbol=row.unit_symbol,
                hourly_concentration=sum(values) / len(values),
                measurement_ids=tuple(sorted(group["measurement_ids"])),
                sample_count=len(values),
                timestamps_at_hour_start=group["timestamps_at_hour_start"],
                measurement_timestamp_semantics=group[
                    "measurement_timestamp_semantics"
                ],
            )
        )
    return sorted(
        inputs,
        key=lambda hourly_input: (
            hourly_input.observed_at,
            hourly_input.device_id,
            hourly_input.parameter_code,
            hourly_input.sensor_id,
        ),
    )


def retrieve_eea_averaged_completed_hour_inputs(
    session: Session,
    *,
    parameter_codes: Sequence[str],
    start_hour_utc: datetime,
    end_hour_utc: datetime,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    device_ids: Optional[Sequence[int]] = None,
) -> list[EeaAveragedHourlyMeasurementInput]:
    """Return EEA sensor averages for complete UTC hours in ``[start, end)``."""
    start = normalize_utc(start_hour_utc)
    end = normalize_utc(end_hour_utc)
    if start != floor_utc_hour(start) or end != floor_utc_hour(end):
        raise ValueError("Hourly retrieval boundaries must be aligned to UTC hours")
    if start >= end:
        return []

    # Retrieve both boundary instants, then filter by the represented hour.
    # This supports mixed hour-start and hour-end streams in one query without
    # shifting provider interval-end observations into the following hour.
    statement = _measurement_rows_statement().where(
        Measurement.observed_at >= start,
        Measurement.observed_at <= end,
    )
    statement = _apply_filters(
        statement,
        parameter_codes=parameter_codes,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        device_ids=device_ids,
    )
    return [
        hourly_input
        for hourly_input in _average_rows_for_eea(session.execute(statement).all())
        if start <= hourly_input.observed_at < end
    ]


def retrieve_latest_eea_averaged_completed_hour_inputs(
    session: Session,
    *,
    parameter_codes: Sequence[str],
    completed_before_utc: datetime,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
) -> list[EeaAveragedHourlyMeasurementInput]:
    """Return EEA averages for every stream in each device's latest hour."""
    completed_before = normalize_utc(completed_before_utc)
    if completed_before != floor_utc_hour(completed_before):
        raise ValueError("Latest retrieval boundary must be aligned to a UTC hour")

    sensors = retrieve_candidate_sensor_streams(
        session,
        parameter_codes=parameter_codes,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
    )
    if not sensors:
        return []
    exclusive_timestamps = retrieve_latest_valid_observed_at_by_sensor(
        session,
        parameter_codes=parameter_codes,
        completed_before_utc=completed_before,
        include_boundary=False,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
    )
    inclusive_timestamps = retrieve_latest_valid_observed_at_by_sensor(
        session,
        parameter_codes=parameter_codes,
        completed_before_utc=completed_before,
        include_boundary=True,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
    )
    latest_hour_by_device: dict[int, datetime] = {}
    for sensor in sensors:
        timestamp_semantics = (
            sensor.hourly_timestamp_semantics
            or sensor.measurement_timestamp_semantics
            or "hour_start"
        )
        timestamps = (
            inclusive_timestamps
            if timestamp_semantics
            in {"interval_end", "provider_received_at", "hour_end"}
            else exclusive_timestamps
        )
        latest_observed_at = timestamps.get(sensor.sensor_id)
        if latest_observed_at is None:
            continue
        represented_hour = represented_utc_hour(
            latest_observed_at,
            timestamp_semantics=timestamp_semantics,
        )
        if represented_hour + _ONE_HOUR > completed_before:
            continue
        current_latest = latest_hour_by_device.get(sensor.device_id)
        if current_latest is None or represented_hour > current_latest:
            latest_hour_by_device[sensor.device_id] = represented_hour

    if not latest_hour_by_device:
        return []
    first_hour = min(latest_hour_by_device.values())
    last_hour_end = max(latest_hour_by_device.values()) + _ONE_HOUR
    hourly_inputs = retrieve_eea_averaged_completed_hour_inputs(
        session,
        parameter_codes=parameter_codes,
        start_hour_utc=first_hour,
        end_hour_utc=last_hour_end,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
    )
    return [
        hourly_input
        for hourly_input in hourly_inputs
        if latest_hour_by_device.get(hourly_input.device_id)
        == hourly_input.observed_at
    ]
