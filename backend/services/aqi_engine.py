from __future__ import annotations

"""Shared PM sensor-stream access and current-condition U.S. EPA NowCast."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from services.air_quality_index.domain import AirQualityIndexProduct, ExclusionReason
from services.air_quality_index.hourly_measurements import (
    HourlySensorStreamMetadata,
    RawMeasurementInput,
    ceil_utc_hour,
    floor_utc_hour,
    normalize_utc,
    retrieve_candidate_sensor_streams,
    retrieve_raw_measurement_inputs,
)
from services.air_quality_index.us_epa import (
    CalculationStatus,
    CoverageStatus,
    DataQualificationStatus,
    UsEpaCalculationResult,
    calculate_pm_nowcast,
    get_product,
    normalize_concentration_unit,
)
from services.air_quality_index.hourly_pm_completeness import (
    US_EPA_STANDARD_CODE,
    EligibleHourlyConcentration,
    HourlyCompletenessAuditFlag,
    VERIFIED_HOURLY_PROVENANCE,
    VERIFIED_MEASUREMENT_METADATA_STATUS,
    construct_provider_hourly_pm_hour,
    construct_subhourly_pm_hour,
    resolve_pm_hourly_sensor_metadata,
    select_raw_observations_for_hour,
)


NOWCAST_HOUR_COUNT = 12


class NowCastHourlyInputEligibility(str, Enum):
    """Whether recent eligible hourly inputs can be passed to NowCast."""

    ELIGIBLE = "eligible"
    INSUFFICIENT_RECENT_HOURS = "insufficient_recent_hours"
    NOT_EVALUATED = "not_evaluated"


UsEpaSensorStreamMetadata = HourlySensorStreamMetadata


@dataclass(frozen=True)
class UsEpaSensorStreamEvaluation:
    sensor: UsEpaSensorStreamMetadata
    is_input_eligible: bool
    exclusion_reason: Optional[ExclusionReason]
    exclusion_reasons: Tuple[ExclusionReason, ...]
    audit_flags: Tuple[HourlyCompletenessAuditFlag, ...]
    metadata_is_verified_and_complete: bool
    hourly_inputs: Tuple[EligibleHourlyConcentration, ...]
    hourly_concentrations: Tuple[Optional[float], ...]
    measurement_ids: Tuple[int, ...]
    valid_sample_count: int
    valid_hourly_slot_count: int
    valid_recent_hourly_slot_count: int
    missing_hourly_slot_count: int
    duplicate_observation_count: int
    rejected_observation_count: int
    off_frequency_observation_count: int


@dataclass(frozen=True)
class UsEpaDeviceAqiResult:
    product: AirQualityIndexProduct
    device_id: int
    device_name: str
    device_friendly_name: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    device_timezone: Optional[str]
    source_name: Optional[str]
    observed_at: datetime
    window_started_at: datetime
    window_ended_at: datetime
    calculation: UsEpaCalculationResult
    selected_sensor: Optional[UsEpaSensorStreamMetadata]
    selected_sensor_reason: Optional[str]
    candidate_sensor_evaluations: Tuple[UsEpaSensorStreamEvaluation, ...]
    completeness_evaluation: Optional[UsEpaSensorStreamEvaluation]
    measurement_ids: Tuple[int, ...]
    valid_sample_count: int
    valid_hourly_slot_count: int
    valid_recent_hourly_slot_count: int
    missing_hourly_slot_count: int
    nowcast_hourly_input_eligibility: NowCastHourlyInputEligibility
    data_qualification_status: DataQualificationStatus


def fetch_us_epa_candidate_sensors(
    session: Session,
    parameter_code: str,
    *,
    device_id: Optional[int],
    external_api_name: Optional[str],
    bbox: Optional[Tuple[float, float, float, float]],
    device_ids: Optional[Sequence[int]] = None,
) -> list[UsEpaSensorStreamMetadata]:
    """Compatibility name for U.S. services using shared sensor retrieval."""
    return retrieve_candidate_sensor_streams(
        session,
        parameter_codes=(parameter_code,),
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        device_ids=device_ids,
    )


def _unavailable_calculation(
    parameter_code: str,
    reason: ExclusionReason,
    valid_observation_count: int = 0,
) -> UsEpaCalculationResult:
    return UsEpaCalculationResult(
        parameter_code=parameter_code,
        component_code=f"{parameter_code}_24_hour",
        calculation_status=CalculationStatus.UNAVAILABLE,
        coverage_status=(
            CoverageStatus.PARTIAL
            if valid_observation_count
            else CoverageStatus.NONE
        ),
        exclusion_reason=reason,
        normalized_concentration=None,
        normalized_unit=None,
        preprocessed_concentration=None,
        numeric_value=None,
        category_code=None,
        category_label=None,
        internal_severity_rank=None,
        aqi_scale_status=None,
        expected_observation_count=NOWCAST_HOUR_COUNT,
        valid_observation_count=valid_observation_count,
    )


def resolve_us_epa_sensor_metadata(
    sensor: UsEpaSensorStreamMetadata,
    *,
    parameter_code: str,
) -> tuple[Optional[ExclusionReason], bool, bool]:
    """Return reason, provider-hourly flag, and verified/complete status."""
    resolution = resolve_pm_hourly_sensor_metadata(
        aggregation_period=sensor.aggregation_period,
        hourly_concentration_provenance=sensor.hourly_concentration_provenance,
        hourly_timestamp_semantics=sensor.hourly_timestamp_semantics,
        expected_frequency_seconds=sensor.expected_frequency_seconds,
        measurement_duration_seconds=sensor.measurement_duration_seconds,
        source_aggregation_duration_seconds=sensor.source_aggregation_duration_seconds,
        measurement_timestamp_semantics=sensor.measurement_timestamp_semantics,
        measurement_metadata_status=sensor.measurement_metadata_status,
        measurement_metadata_managed_by=sensor.measurement_metadata_managed_by,
        parameter_code=parameter_code,
    )
    input_unit = sensor.input_unit_code or sensor.input_unit_symbol
    unit_check = normalize_concentration_unit(parameter_code, 0, input_unit)
    if not unit_check.is_supported:
        return (
            unit_check.exclusion_reason or ExclusionReason.UNSUPPORTED_UNIT,
            resolution.provider_reported_hourly,
            False,
        )
    return (
        resolution.exclusion_reason,
        resolution.provider_reported_hourly,
        resolution.metadata_is_verified_and_complete,
    )


def _evaluate_sensor_stream(
    sensor: UsEpaSensorStreamMetadata,
    raw_inputs: Sequence[RawMeasurementInput],
    *,
    parameter_code: str,
    completed_before_utc: datetime,
) -> UsEpaSensorStreamEvaluation:
    metadata_reason, provider_hourly, metadata_complete = (
        resolve_us_epa_sensor_metadata(
            sensor,
            parameter_code=parameter_code,
        )
    )
    hourly_results: list[EligibleHourlyConcentration] = []
    input_unit = sensor.input_unit_code or sensor.input_unit_symbol
    if metadata_reason is None:
        timestamp_semantics = (
            sensor.hourly_timestamp_semantics
            if provider_hourly
            else sensor.measurement_timestamp_semantics
        ) or ""
        for hours_ago in range(NOWCAST_HOUR_COUNT):
            hour_start = completed_before_utc - timedelta(hours=hours_ago + 1)
            observations = select_raw_observations_for_hour(
                raw_inputs,
                interval_started_at=hour_start,
                timestamp_semantics=timestamp_semantics,
            )
            if provider_hourly:
                hourly_result = construct_provider_hourly_pm_hour(
                    observations,
                    interval_started_at=hour_start,
                    parameter_code=parameter_code,
                    input_unit=input_unit,
                    timestamp_semantics=timestamp_semantics,
                )
            else:
                hourly_result = construct_subhourly_pm_hour(
                    observations,
                    interval_started_at=hour_start,
                    parameter_code=parameter_code,
                    input_unit=input_unit,
                    expected_frequency_seconds=sensor.expected_frequency_seconds or 0,
                    measurement_duration_seconds=sensor.measurement_duration_seconds
                    or 0,
                    source_aggregation_duration_seconds=(
                        sensor.source_aggregation_duration_seconds or 0
                    ),
                    timestamp_semantics=timestamp_semantics,
                )
            hourly_results.append(hourly_result)

    hourly_concentrations = tuple(
        hourly_result.hourly_concentration
        if hourly_result.is_eligible
        else None
        for hourly_result in hourly_results
    )
    valid_hourly_count = sum(
        concentration is not None for concentration in hourly_concentrations
    )
    recent_count = sum(
        concentration is not None for concentration in hourly_concentrations[:3]
    )
    is_input_eligible = metadata_reason is None and valid_hourly_count > 0
    detailed_reasons: list[ExclusionReason] = []
    audit_flags: list[HourlyCompletenessAuditFlag] = []
    # Source absence is distinct from metadata qualification and hourly
    # completeness. Record it first so a zero-row stream is diagnosable even
    # when its manifest metadata is also incomplete or unknown.
    if not raw_inputs:
        detailed_reasons.append(ExclusionReason.MISSING_MEASUREMENTS)
    if metadata_reason is not None:
        detailed_reasons.append(metadata_reason)
    for hourly_result in hourly_results:
        for reason in hourly_result.exclusion_reasons:
            if reason not in detailed_reasons:
                detailed_reasons.append(reason)
        for audit_flag in hourly_result.audit_flags:
            if audit_flag not in audit_flags:
                audit_flags.append(audit_flag)
    if metadata_reason is None and valid_hourly_count == 0 and not detailed_reasons:
        detailed_reasons.append(ExclusionReason.NO_VALID_OBSERVATIONS)
    exclusion_reason = detailed_reasons[0] if not is_input_eligible else None
    measurement_ids = tuple(
        sorted(
            measurement_id
            for hourly_result in hourly_results
            if hourly_result.is_eligible
            for measurement_id in hourly_result.measurement_ids
        )
    )
    return UsEpaSensorStreamEvaluation(
        sensor=sensor,
        is_input_eligible=is_input_eligible,
        exclusion_reason=exclusion_reason,
        exclusion_reasons=tuple(detailed_reasons),
        audit_flags=tuple(audit_flags),
        metadata_is_verified_and_complete=metadata_complete,
        hourly_inputs=tuple(hourly_results),
        hourly_concentrations=hourly_concentrations,
        measurement_ids=measurement_ids,
        valid_sample_count=sum(
            hourly_result.valid_observation_count
            for hourly_result in hourly_results
            if hourly_result.is_eligible
        ),
        valid_hourly_slot_count=valid_hourly_count,
        valid_recent_hourly_slot_count=recent_count,
        missing_hourly_slot_count=NOWCAST_HOUR_COUNT - valid_hourly_count,
        duplicate_observation_count=sum(
            len(hourly_result.duplicate_measurement_ids)
            for hourly_result in hourly_results
        ),
        rejected_observation_count=sum(
            len(hourly_result.rejected_measurement_ids)
            for hourly_result in hourly_results
        ),
        off_frequency_observation_count=sum(
            len(hourly_result.off_frequency_measurement_ids)
            for hourly_result in hourly_results
        ),
    )


def _selection_sort_key(
    evaluation: UsEpaSensorStreamEvaluation,
) -> tuple[int, int, int, int]:
    return (
        -int(evaluation.metadata_is_verified_and_complete),
        -evaluation.valid_hourly_slot_count,
        -evaluation.valid_recent_hourly_slot_count,
        evaluation.sensor.sensor_id,
    )


def _calculate_us_epa_aqi_for_boundary(
    *,
    product: AirQualityIndexProduct,
    sensors: Sequence[UsEpaSensorStreamMetadata],
    raw_inputs: Sequence[RawMeasurementInput],
    completed_before: datetime,
    limit: int | None,
) -> list[UsEpaDeviceAqiResult]:
    """Evaluate one NowCast boundary from already bounded database inputs."""
    inputs_by_sensor: dict[int, list[RawMeasurementInput]] = {}
    for raw_input in raw_inputs:
        inputs_by_sensor.setdefault(raw_input.sensor_id, []).append(raw_input)
    sensors_by_device: dict[int, list[UsEpaSensorStreamMetadata]] = {}
    for sensor in sensors:
        sensors_by_device.setdefault(sensor.device_id, []).append(sensor)

    window_started_at = completed_before - timedelta(hours=NOWCAST_HOUR_COUNT)
    results: list[UsEpaDeviceAqiResult] = []
    for current_device_id, device_sensors in sensors_by_device.items():
        evaluations = tuple(
            _evaluate_sensor_stream(
                sensor,
                inputs_by_sensor.get(sensor.sensor_id, ()),
                parameter_code=product.parameter_code or "",
                completed_before_utc=completed_before,
            )
            for sensor in sorted(device_sensors, key=lambda item: item.sensor_id)
        )
        eligible = sorted(
            (item for item in evaluations if item.is_input_eligible),
            key=_selection_sort_key,
        )
        selected = eligible[0] if eligible else None
        audit_evaluation = selected or sorted(
            evaluations,
            key=_selection_sort_key,
        )[0]
        if selected is None:
            calculation = _unavailable_calculation(
                product.parameter_code or "",
                ExclusionReason.NO_ELIGIBLE_SENSOR_STREAM,
            )
            measurement_ids: Tuple[int, ...] = ()
            valid_sample_count = 0
            selected_sensor = None
            selected_reason = None
            valid_hourly_slot_count = 0
            valid_recent_hourly_slot_count = 0
            missing_hourly_slot_count = NOWCAST_HOUR_COUNT
            nowcast_hourly_input_eligibility = (
                NowCastHourlyInputEligibility.NOT_EVALUATED
            )
        else:
            calculation = calculate_pm_nowcast(
                product.parameter_code or "",
                selected.hourly_concentrations,
                selected.hourly_inputs[0].normalized_unit,
            )
            measurement_ids = selected.measurement_ids
            valid_sample_count = selected.valid_sample_count
            selected_sensor = selected.sensor
            selected_reason = (
                "verified_metadata_then_most_valid_hourly_slots_then_recent_"
                "slots_then_sensor_id"
            )
            valid_hourly_slot_count = selected.valid_hourly_slot_count
            valid_recent_hourly_slot_count = selected.valid_recent_hourly_slot_count
            missing_hourly_slot_count = selected.missing_hourly_slot_count
            nowcast_hourly_input_eligibility = (
                NowCastHourlyInputEligibility.ELIGIBLE
                if selected.valid_recent_hourly_slot_count >= 2
                else NowCastHourlyInputEligibility.INSUFFICIENT_RECENT_HOURS
            )
        device = device_sensors[0]
        results.append(
            UsEpaDeviceAqiResult(
                product=product,
                device_id=current_device_id,
                device_name=device.device_name,
                device_friendly_name=device.device_friendly_name,
                latitude=device.latitude,
                longitude=device.longitude,
                device_timezone=device.device_timezone,
                source_name=device.source_name,
                observed_at=completed_before,
                window_started_at=window_started_at,
                window_ended_at=completed_before,
                calculation=calculation,
                selected_sensor=selected_sensor,
                selected_sensor_reason=selected_reason,
                candidate_sensor_evaluations=evaluations,
                completeness_evaluation=audit_evaluation,
                measurement_ids=measurement_ids,
                valid_sample_count=valid_sample_count,
                valid_hourly_slot_count=valid_hourly_slot_count,
                valid_recent_hourly_slot_count=valid_recent_hourly_slot_count,
                missing_hourly_slot_count=missing_hourly_slot_count,
                nowcast_hourly_input_eligibility=nowcast_hourly_input_eligibility,
                data_qualification_status=DataQualificationStatus.NOT_EVALUATED,
            )
        )
    return sorted(results, key=lambda result: result.device_id)[:limit]


def calculate_latest_us_epa_aqi(
    session: Session,
    *,
    product_code: str,
    reference_time_utc: Optional[datetime] = None,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    limit: int | None = 100,
    current_time_utc: Optional[datetime] = None,
) -> list[UsEpaDeviceAqiResult]:
    product = get_product(product_code)
    if product is None or product.parameter_code not in {"pm25", "pm10"}:
        raise ValueError(f"Unknown U.S. EPA AQI product: {product_code}")
    now = normalize_utc(current_time_utc or datetime.now(timezone.utc))
    requested_boundary = (
        normalize_utc(reference_time_utc) if reference_time_utc else now
    )
    completed_before = min(
        floor_utc_hour(now),
        floor_utc_hour(requested_boundary),
    )
    window_started_at = completed_before - timedelta(hours=NOWCAST_HOUR_COUNT)
    sensors = fetch_us_epa_candidate_sensors(
        session,
        product.parameter_code,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
    )
    if not sensors:
        return []
    raw_inputs = retrieve_raw_measurement_inputs(
        session,
        parameter_codes=(product.parameter_code,),
        start_utc=window_started_at,
        end_utc=completed_before,
        include_end=True,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
    )
    return _calculate_us_epa_aqi_for_boundary(
        product=product,
        sensors=sensors,
        raw_inputs=raw_inputs,
        completed_before=completed_before,
        limit=limit,
    )


def calculate_us_epa_aqi_history(
    session: Session,
    *,
    product_code: str,
    start_utc: datetime,
    end_utc: datetime,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    limit: int = 1000,
    current_time_utc: Optional[datetime] = None,
    device_ids: Optional[Sequence[int]] = None,
) -> list[UsEpaDeviceAqiResult]:
    """Return at most 2,160 hourly NowCast evaluations from two bounded queries."""
    product = get_product(product_code)
    if product is None or product.parameter_code not in {"pm25", "pm10"}:
        raise ValueError(f"Unknown U.S. EPA AQI product: {product_code}")
    normalized_start = normalize_utc(start_utc)
    normalized_end = normalize_utc(end_utc)
    if normalized_start >= normalized_end:
        raise ValueError("start must be earlier than end")
    if normalized_end - normalized_start > timedelta(hours=2160):
        raise ValueError("U.S. EPA current-condition history cannot exceed 90 days")

    latest_boundary = floor_utc_hour(
        normalize_utc(current_time_utc or datetime.now(timezone.utc))
    )
    boundaries: list[datetime] = []
    current_boundary = ceil_utc_hour(normalized_start)
    while current_boundary < normalized_end and current_boundary <= latest_boundary:
        boundaries.append(current_boundary)
        current_boundary += timedelta(hours=1)
    if not boundaries:
        return []

    sensors = fetch_us_epa_candidate_sensors(
        session,
        product.parameter_code,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        device_ids=device_ids,
    )
    if not sensors:
        return []
    raw_inputs = retrieve_raw_measurement_inputs(
        session,
        parameter_codes=(product.parameter_code,),
        start_utc=boundaries[0] - timedelta(hours=NOWCAST_HOUR_COUNT),
        end_utc=boundaries[-1],
        include_end=True,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        sensor_ids=tuple(sensor.sensor_id for sensor in sensors),
        device_ids=device_ids,
    )
    raw_input_timestamps = [raw_input.observed_at for raw_input in raw_inputs]
    results = [
        result
        for boundary in boundaries
        for result in _calculate_us_epa_aqi_for_boundary(
            product=product,
            sensors=sensors,
            raw_inputs=raw_inputs[
                bisect_left(
                    raw_input_timestamps,
                    boundary - timedelta(hours=NOWCAST_HOUR_COUNT),
                ) : bisect_right(raw_input_timestamps, boundary)
            ],
            completed_before=boundary,
            limit=limit,
        )
    ]
    return sorted(
        results,
        key=lambda result: (result.observed_at, result.device_id),
    )[:limit]
