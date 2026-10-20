from __future__ import annotations

"""Application service connecting completed hourly inputs to the EEA domain."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from .domain import AirQualityIndexResult, EligibilityStatus, ExclusionReason, PollutantIndexResult
from .eea_european import (
    POLLUTANTS,
    classify_hourly_concentration,
    combine_pollutant_results,
    ineligible_pollutant_result,
)
from .eea_gas_hourly import (
    GAS_PARAMETER_CODES,
    construct_eea_gas_hour,
    gas_metadata_exclusion_reason,
)
from .hourly_measurements import (
    HourlySensorStreamMetadata,
    RawMeasurementInput,
    ceil_utc_hour,
    floor_utc_hour,
    normalize_utc,
    retrieve_candidate_sensor_streams,
    retrieve_latest_valid_observed_at_by_sensor,
    retrieve_raw_measurement_inputs,
    represented_utc_hour,
)
from .hourly_pm_completeness import (
    EligibleHourlyConcentration,
    HourlyCompletenessAuditFlag,
    RawHourlyObservation,
    construct_provider_hourly_pm_hour,
    construct_subhourly_pm_hour,
    resolve_pm_hourly_sensor_metadata,
    select_raw_observations_for_hour,
)


SENSOR_SELECTION_RULE = "lowest_eligible_sensor_id_else_lowest_sensor_id"


@dataclass(frozen=True)
class SensorStreamEvaluationProvenance:
    sensor_id: int
    aggregation_period: Optional[str]
    eligibility_status: EligibilityStatus
    exclusion_reason: Optional[ExclusionReason]
    expected_observation_count: Optional[int]
    valid_observation_count: Optional[int]
    required_valid_observation_count: Optional[int]
    required_completeness_fraction: Optional[float]
    achieved_completeness_fraction: Optional[float]
    completeness_rule_code: Optional[str]
    audit_flags: Tuple[HourlyCompletenessAuditFlag, ...]
    measurement_ids: Tuple[int, ...]
    duplicate_measurement_ids: Tuple[int, ...]
    rejected_measurement_ids: Tuple[int, ...]
    off_frequency_measurement_ids: Tuple[int, ...]
    input_frequency_seconds: Optional[int]
    measurement_duration_seconds: Optional[int]
    source_aggregation_duration_seconds: Optional[int]
    target_duration_seconds: Optional[int]
    measurement_timestamp_semantics: Optional[str]


@dataclass(frozen=True)
class SensorSelectionProvenance:
    parameter_code: str
    selected_sensor_id: int
    selected_external_sensor_id: Optional[str]
    selected_sensor_aggregation_period: Optional[str]
    input_unit_code: Optional[str]
    input_unit_symbol: Optional[str]
    hourly_concentration: Optional[float]
    measurement_ids: Tuple[int, ...]
    sample_count: int
    candidate_sensor_ids: Tuple[int, ...]
    eligible_sensor_ids: Tuple[int, ...]
    duplicate_eligible_sensor_ids: Tuple[int, ...]
    sensor_stream_evaluations: Tuple[SensorStreamEvaluationProvenance, ...]
    selection_rule: str
    expected_observation_count: Optional[int]
    valid_observation_count: Optional[int]
    required_valid_observation_count: Optional[int]
    required_completeness_fraction: Optional[float]
    achieved_completeness_fraction: Optional[float]
    completeness_rule_code: Optional[str]
    audit_flags: Tuple[HourlyCompletenessAuditFlag, ...]
    input_frequency_seconds: Optional[int]
    measurement_duration_seconds: Optional[int]
    source_aggregation_duration_seconds: Optional[int]
    target_duration_seconds: Optional[int]
    measurement_timestamp_semantics: Optional[str]


@dataclass(frozen=True)
class EeaHourlyMeasurementInput:
    """One sensor's candidate concentration for a completed UTC hour."""

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
    hourly_concentration: Optional[float]
    measurement_ids: Tuple[int, ...]
    sample_count: int
    exclusion_reason: Optional[ExclusionReason]
    completeness: Optional[EligibleHourlyConcentration]
    input_frequency_seconds: Optional[int]
    measurement_duration_seconds: Optional[int]
    source_aggregation_duration_seconds: Optional[int]
    measurement_timestamp_semantics: Optional[str]


@dataclass(frozen=True)
class DeviceHourlyAirQualityIndex:
    device_id: int
    device_name: str
    device_friendly_name: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    device_timezone: Optional[str]
    source_name: Optional[str]
    observed_at: datetime
    air_quality_index_result: AirQualityIndexResult
    sensor_provenance: Tuple[SensorSelectionProvenance, ...]


def _classify_stream(
    hourly_input: EeaHourlyMeasurementInput,
) -> PollutantIndexResult:
    """Normalize and classify one EEA hourly concentration.

    ``Unit.code`` is the canonical repository identifier. An unrecognized code
    is rejected even if its display symbol looks compatible, so inconsistent
    unit metadata cannot silently make a stream eligible. Ordinary measurement
    formatting rules are intentionally not part of EEA classification.
    """
    if hourly_input.exclusion_reason is not None:
        return ineligible_pollutant_result(
            hourly_input.parameter_code,
            hourly_input.exclusion_reason,
        )
    if hourly_input.hourly_concentration is None:
        return ineligible_pollutant_result(
            hourly_input.parameter_code,
            ExclusionReason.HOURLY_CONCENTRATION_NOT_AVAILABLE,
        )

    unit_identifier = (
        hourly_input.completeness.normalized_unit
        if hourly_input.completeness is not None
        else hourly_input.input_unit_code or hourly_input.input_unit_symbol
    )
    return classify_hourly_concentration(
        hourly_input.parameter_code,
        hourly_input.hourly_concentration,
        unit_identifier,
    )


def _qualified_hourly_input(
    sensor: HourlySensorStreamMetadata,
    observations: Sequence[RawHourlyObservation],
    *,
    hour_started_at: datetime,
) -> EeaHourlyMeasurementInput:
    input_unit = sensor.input_unit_code or sensor.input_unit_symbol
    unit_check = classify_hourly_concentration(
        sensor.parameter_code,
        0.0,
        input_unit,
    )
    completeness: Optional[EligibleHourlyConcentration] = None
    if sensor.parameter_code in GAS_PARAMETER_CODES:
        timestamp_semantics = (
            sensor.hourly_timestamp_semantics
            if (sensor.aggregation_period or "").strip().lower() == "1h"
            else sensor.measurement_timestamp_semantics
        )
        exclusion_reason = (
            unit_check.exclusion_reason or gas_metadata_exclusion_reason(sensor)
        )
        if exclusion_reason is None:
            completeness = construct_eea_gas_hour(
                sensor, observations, hour_started_at=hour_started_at,
            )
            exclusion_reason = completeness.exclusion_reason
    else:
        metadata_resolution = resolve_pm_hourly_sensor_metadata(
            aggregation_period=sensor.aggregation_period,
            hourly_concentration_provenance=sensor.hourly_concentration_provenance,
            hourly_timestamp_semantics=sensor.hourly_timestamp_semantics,
            expected_frequency_seconds=sensor.expected_frequency_seconds,
            measurement_duration_seconds=sensor.measurement_duration_seconds,
            source_aggregation_duration_seconds=sensor.source_aggregation_duration_seconds,
            measurement_timestamp_semantics=sensor.measurement_timestamp_semantics,
            measurement_metadata_status=sensor.measurement_metadata_status,
            measurement_metadata_managed_by=sensor.measurement_metadata_managed_by,
            parameter_code=sensor.parameter_code,
        )
        timestamp_semantics = (
            sensor.hourly_timestamp_semantics
            if metadata_resolution.provider_reported_hourly
            else sensor.measurement_timestamp_semantics
        )
        exclusion_reason = unit_check.exclusion_reason
        if exclusion_reason is None:
            exclusion_reason = metadata_resolution.exclusion_reason

        if exclusion_reason is None:
            if metadata_resolution.provider_reported_hourly:
                completeness = construct_provider_hourly_pm_hour(
                    observations,
                    interval_started_at=hour_started_at,
                    parameter_code=sensor.parameter_code,
                    input_unit=input_unit,
                    timestamp_semantics=timestamp_semantics or "",
                )
            else:
                completeness = construct_subhourly_pm_hour(
                    observations,
                    interval_started_at=hour_started_at,
                    parameter_code=sensor.parameter_code,
                    input_unit=input_unit,
                    expected_frequency_seconds=sensor.expected_frequency_seconds or 0,
                    measurement_duration_seconds=sensor.measurement_duration_seconds or 0,
                    source_aggregation_duration_seconds=(
                        sensor.source_aggregation_duration_seconds or 0
                    ),
                    timestamp_semantics=timestamp_semantics or "",
                )
            exclusion_reason = completeness.exclusion_reason

    if completeness is not None:
        measurement_ids = completeness.measurement_ids
        sample_count = completeness.valid_observation_count
        hourly_concentration = completeness.hourly_concentration
    else:
        measurement_ids = tuple(
            sorted(observation.measurement_id for observation in observations)
        )
        sample_count = sum(observation.is_valid for observation in observations)
        hourly_concentration = None

    return EeaHourlyMeasurementInput(
        device_id=sensor.device_id,
        device_name=sensor.device_name,
        device_friendly_name=sensor.device_friendly_name,
        latitude=sensor.latitude,
        longitude=sensor.longitude,
        device_timezone=sensor.device_timezone,
        source_name=sensor.source_name,
        observed_at=normalize_utc(hour_started_at),
        parameter_code=sensor.parameter_code,
        sensor_id=sensor.sensor_id,
        external_sensor_id=sensor.external_sensor_id,
        sensor_aggregation_period=sensor.aggregation_period,
        input_unit_code=sensor.input_unit_code,
        input_unit_symbol=sensor.input_unit_symbol,
        hourly_concentration=hourly_concentration,
        measurement_ids=measurement_ids,
        sample_count=sample_count,
        exclusion_reason=exclusion_reason,
        completeness=completeness,
        input_frequency_seconds=sensor.expected_frequency_seconds,
        measurement_duration_seconds=sensor.measurement_duration_seconds,
        source_aggregation_duration_seconds=(
            sensor.source_aggregation_duration_seconds
        ),
        measurement_timestamp_semantics=timestamp_semantics,
    )


def _candidate_timestamp_semantics(sensor: HourlySensorStreamMetadata) -> str:
    # These defaults locate candidate diagnostics only. Missing/unsupported
    # semantics are rejected by qualification, never treated as verified input.
    if (sensor.aggregation_period or "").strip().lower() == "1h":
        return sensor.hourly_timestamp_semantics or "hour_start"
    return sensor.measurement_timestamp_semantics or "interval_start"


def _inputs_for_device_hours(
    session: Session,
    *,
    sensors: Sequence[HourlySensorStreamMetadata],
    hours_by_device: dict[int, tuple[datetime, ...]],
    device_id: Optional[int],
    external_api_name: Optional[str],
    bbox: Optional[Tuple[float, float, float, float]],
    device_ids: Optional[Sequence[int]] = None,
) -> list[EeaHourlyMeasurementInput]:
    requested_hours = tuple(
        hour
        for device_hours in hours_by_device.values()
        for hour in device_hours
    )
    if not sensors or not requested_hours:
        return []
    first_hour = min(requested_hours)
    completed_before = max(requested_hours) + timedelta(hours=1)
    raw_inputs = retrieve_raw_measurement_inputs(
        session,
        parameter_codes=POLLUTANTS,
        start_utc=first_hour,
        end_utc=completed_before,
        include_end=True,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        sensor_ids=tuple(sensor.sensor_id for sensor in sensors),
        device_ids=device_ids,
    )
    inputs_by_sensor: dict[int, list[RawMeasurementInput]] = {}
    for raw_input in raw_inputs:
        inputs_by_sensor.setdefault(raw_input.sensor_id, []).append(raw_input)

    hourly_inputs: list[EeaHourlyMeasurementInput] = []
    for sensor in sensors:
        sensor_inputs = inputs_by_sensor.get(sensor.sensor_id, ())
        for hour_started_at in hours_by_device.get(sensor.device_id, ()):
            observations = select_raw_observations_for_hour(
                sensor_inputs,
                interval_started_at=hour_started_at,
                timestamp_semantics=_candidate_timestamp_semantics(sensor),
            )
            if not observations:
                continue
            hourly_inputs.append(
                _qualified_hourly_input(
                    sensor,
                    observations,
                    hour_started_at=hour_started_at,
                )
            )
    return hourly_inputs


def _latest_hours_by_device(
    session: Session,
    *,
    sensors: Sequence[HourlySensorStreamMetadata],
    completed_before_utc: datetime,
    device_id: Optional[int],
    external_api_name: Optional[str],
    bbox: Optional[Tuple[float, float, float, float]],
) -> dict[int, datetime]:
    exclusive_timestamps = retrieve_latest_valid_observed_at_by_sensor(
        session,
        parameter_codes=POLLUTANTS,
        completed_before_utc=completed_before_utc,
        include_boundary=False,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
    )
    inclusive_timestamps = retrieve_latest_valid_observed_at_by_sensor(
        session,
        parameter_codes=POLLUTANTS,
        completed_before_utc=completed_before_utc,
        include_boundary=True,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
    )
    # A gas hour containing only invalid observations must remain an explicit
    # unavailable latest result, rather than silently selecting an older hour.
    for include_boundary, timestamps in (
        (False, exclusive_timestamps),
        (True, inclusive_timestamps),
    ):
        timestamps.update(
            retrieve_latest_valid_observed_at_by_sensor(
                session,
                parameter_codes=GAS_PARAMETER_CODES,
                completed_before_utc=completed_before_utc,
                include_boundary=include_boundary,
                include_invalid=True,
                device_id=device_id,
                external_api_name=external_api_name,
                bbox=bbox,
            )
        )
    latest_by_device: dict[int, datetime] = {}
    for sensor in sensors:
        timestamp_semantics = _candidate_timestamp_semantics(sensor)
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
        if represented_hour + timedelta(hours=1) > completed_before_utc:
            continue
        current_latest = latest_by_device.get(sensor.device_id)
        if current_latest is None or represented_hour > current_latest:
            latest_by_device[sensor.device_id] = represented_hour
    return latest_by_device


def _stream_evaluation_provenance(
    stream: EeaHourlyMeasurementInput,
    stream_result: PollutantIndexResult,
) -> SensorStreamEvaluationProvenance:
    completeness = stream.completeness
    return SensorStreamEvaluationProvenance(
        sensor_id=stream.sensor_id,
        aggregation_period=stream.sensor_aggregation_period,
        eligibility_status=stream_result.eligibility_status,
        exclusion_reason=stream_result.exclusion_reason,
        expected_observation_count=(
            completeness.expected_observation_count
            if completeness is not None
            else None
        ),
        valid_observation_count=(
            completeness.valid_observation_count
            if completeness is not None
            else None
        ),
        required_valid_observation_count=(
            completeness.required_valid_observation_count
            if completeness is not None
            else None
        ),
        required_completeness_fraction=(
            completeness.required_completeness_fraction
            if completeness is not None
            else None
        ),
        achieved_completeness_fraction=(
            completeness.achieved_completeness_fraction
            if completeness is not None
            else None
        ),
        completeness_rule_code=(
            completeness.completeness_rule_code
            if completeness is not None
            else None
        ),
        audit_flags=completeness.audit_flags if completeness is not None else (),
        measurement_ids=stream.measurement_ids,
        duplicate_measurement_ids=(
            completeness.duplicate_measurement_ids
            if completeness is not None
            else ()
        ),
        rejected_measurement_ids=(
            completeness.rejected_measurement_ids
            if completeness is not None
            else ()
        ),
        off_frequency_measurement_ids=(
            completeness.off_frequency_measurement_ids
            if completeness is not None
            else ()
        ),
        input_frequency_seconds=(
            completeness.input_frequency_seconds
            if completeness is not None
            else stream.input_frequency_seconds
        ),
        measurement_duration_seconds=(
            completeness.measurement_duration_seconds
            if completeness is not None
            else stream.measurement_duration_seconds
        ),
        source_aggregation_duration_seconds=(
            completeness.source_aggregation_duration_seconds
            if completeness is not None
            else stream.source_aggregation_duration_seconds
        ),
        target_duration_seconds=(
            completeness.target_duration_seconds
            if completeness is not None
            else None
        ),
        measurement_timestamp_semantics=stream.measurement_timestamp_semantics,
    )


def _select_parameter_stream(
    streams: Sequence[EeaHourlyMeasurementInput],
) -> tuple[PollutantIndexResult, SensorSelectionProvenance]:
    classified = sorted(
        (
            (stream, _classify_stream(stream))
            for stream in streams
        ),
        key=lambda stream_and_result: stream_and_result[0].sensor_id,
    )
    eligible = [
        stream_and_result
        for stream_and_result in classified
        if stream_and_result[1].eligibility_status is EligibilityStatus.ELIGIBLE
    ]
    selected_stream, selected_result = eligible[0] if eligible else classified[0]
    candidate_ids = tuple(stream_and_result[0].sensor_id for stream_and_result in classified)
    eligible_ids = tuple(stream_and_result[0].sensor_id for stream_and_result in eligible)
    selected_completeness = selected_stream.completeness
    provenance = SensorSelectionProvenance(
        parameter_code=selected_stream.parameter_code,
        selected_sensor_id=selected_stream.sensor_id,
        selected_external_sensor_id=selected_stream.external_sensor_id,
        selected_sensor_aggregation_period=selected_stream.sensor_aggregation_period,
        input_unit_code=selected_stream.input_unit_code,
        input_unit_symbol=selected_stream.input_unit_symbol,
        hourly_concentration=selected_stream.hourly_concentration,
        measurement_ids=selected_stream.measurement_ids,
        sample_count=selected_stream.sample_count,
        candidate_sensor_ids=candidate_ids,
        eligible_sensor_ids=eligible_ids,
        duplicate_eligible_sensor_ids=tuple(
            sensor_id for sensor_id in eligible_ids if sensor_id != selected_stream.sensor_id
        ),
        sensor_stream_evaluations=tuple(
            _stream_evaluation_provenance(stream, stream_result)
            for stream, stream_result in classified
        ),
        selection_rule=SENSOR_SELECTION_RULE,
        expected_observation_count=(
            selected_completeness.expected_observation_count
            if selected_completeness is not None
            else None
        ),
        valid_observation_count=(
            selected_completeness.valid_observation_count
            if selected_completeness is not None
            else None
        ),
        required_valid_observation_count=(
            selected_completeness.required_valid_observation_count
            if selected_completeness is not None
            else None
        ),
        required_completeness_fraction=(
            selected_completeness.required_completeness_fraction
            if selected_completeness is not None
            else None
        ),
        achieved_completeness_fraction=(
            selected_completeness.achieved_completeness_fraction
            if selected_completeness is not None
            else None
        ),
        completeness_rule_code=(
            selected_completeness.completeness_rule_code
            if selected_completeness is not None
            else None
        ),
        audit_flags=(
            selected_completeness.audit_flags
            if selected_completeness is not None
            else ()
        ),
        input_frequency_seconds=(
            selected_completeness.input_frequency_seconds
            if selected_completeness is not None
            else selected_stream.input_frequency_seconds
        ),
        measurement_duration_seconds=(
            selected_completeness.measurement_duration_seconds
            if selected_completeness is not None
            else selected_stream.measurement_duration_seconds
        ),
        source_aggregation_duration_seconds=(
            selected_completeness.source_aggregation_duration_seconds
            if selected_completeness is not None
            else selected_stream.source_aggregation_duration_seconds
        ),
        target_duration_seconds=(
            selected_completeness.target_duration_seconds
            if selected_completeness is not None
            else None
        ),
        measurement_timestamp_semantics=selected_stream.measurement_timestamp_semantics,
    )
    return selected_result, provenance


def calculate_device_hour_results(
    hourly_inputs: Sequence[EeaHourlyMeasurementInput],
) -> list[DeviceHourlyAirQualityIndex]:
    """Calculate one overall European AQI result per device and UTC hour."""
    grouped: dict[
        tuple[int, datetime], list[EeaHourlyMeasurementInput]
    ] = {}
    for hourly_input in hourly_inputs:
        grouped.setdefault(
            (hourly_input.device_id, hourly_input.observed_at), []
        ).append(hourly_input)

    device_hour_results: list[DeviceHourlyAirQualityIndex] = []
    for (_device_id, observed_at), device_hour_inputs in grouped.items():
        representative = device_hour_inputs[0]
        by_parameter: dict[str, list[EeaHourlyMeasurementInput]] = {}
        for hourly_input in device_hour_inputs:
            by_parameter.setdefault(hourly_input.parameter_code, []).append(hourly_input)

        pollutant_results: list[PollutantIndexResult] = []
        sensor_provenance: list[SensorSelectionProvenance] = []
        for parameter_code in POLLUTANTS:
            streams = by_parameter.get(parameter_code)
            if not streams:
                continue
            parameter_result, parameter_provenance = _select_parameter_stream(
                streams,
            )
            pollutant_results.append(parameter_result)
            sensor_provenance.append(parameter_provenance)

        device_hour_results.append(
            DeviceHourlyAirQualityIndex(
                device_id=representative.device_id,
                device_name=representative.device_name,
                device_friendly_name=representative.device_friendly_name,
                latitude=representative.latitude,
                longitude=representative.longitude,
                device_timezone=representative.device_timezone,
                source_name=representative.source_name,
                observed_at=observed_at,
                air_quality_index_result=combine_pollutant_results(pollutant_results),
                sensor_provenance=tuple(sensor_provenance),
            )
        )
    return sorted(
        device_hour_results,
        key=lambda device_hour_result: (
            -device_hour_result.observed_at.timestamp(),
            device_hour_result.device_id,
        ),
    )


def calculate_latest_eea_european_index(
    session: Session,
    *,
    reference_time_utc: Optional[datetime] = None,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    limit: int | None = 100,
    current_time_utc: Optional[datetime] = None,
) -> list[DeviceHourlyAirQualityIndex]:
    now = normalize_utc(current_time_utc or datetime.now(timezone.utc))
    requested_boundary = normalize_utc(reference_time_utc) if reference_time_utc else now
    completed_before = min(floor_utc_hour(now), floor_utc_hour(requested_boundary))
    sensors = retrieve_candidate_sensor_streams(
        session,
        parameter_codes=POLLUTANTS,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
    )
    latest_hours_by_device = _latest_hours_by_device(
        session,
        sensors=sensors,
        completed_before_utc=completed_before,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
    )
    hours_by_device = {
        current_device_id: (latest_hour,)
        for current_device_id, latest_hour in latest_hours_by_device.items()
    }
    inputs = _inputs_for_device_hours(
        session,
        sensors=sensors,
        hours_by_device=hours_by_device,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
    )
    return calculate_device_hour_results(
        inputs,
    )[:limit]


def calculate_eea_european_index_history(
    session: Session,
    *,
    start_utc: datetime,
    end_utc: datetime,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    limit: int = 1000,
    current_time_utc: Optional[datetime] = None,
    device_ids: Optional[Sequence[int]] = None,
) -> list[DeviceHourlyAirQualityIndex]:
    normalized_start = normalize_utc(start_utc)
    normalized_end = normalize_utc(end_utc)
    if normalized_start >= normalized_end:
        raise ValueError("start must be earlier than end")

    now = normalize_utc(current_time_utc or datetime.now(timezone.utc))
    first_complete_hour = ceil_utc_hour(normalized_start)
    completed_before = min(floor_utc_hour(normalized_end), floor_utc_hour(now))
    sensors = retrieve_candidate_sensor_streams(
        session,
        parameter_codes=POLLUTANTS,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        device_ids=device_ids,
    )
    requested_hours: list[datetime] = []
    current_hour = first_complete_hour
    while current_hour < completed_before:
        requested_hours.append(current_hour)
        current_hour += timedelta(hours=1)
    hours_by_device = {
        sensor.device_id: tuple(requested_hours)
        for sensor in sensors
    }
    inputs = _inputs_for_device_hours(
        session,
        sensors=sensors,
        hours_by_device=hours_by_device,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        device_ids=device_ids,
    )
    return calculate_device_hour_results(
        inputs,
    )[:limit]
