from __future__ import annotations

"""Latest completed-window U.S. EPA ozone AQI orchestration.

Every sensor stream is qualified and calculated independently. The service
never combines hours or AQI candidates across sensors and never ranks sensors
by AQI severity.
"""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from services.aqi_engine import (
    VERIFIED_HOURLY_PROVENANCE,
    VERIFIED_MEASUREMENT_METADATA_STATUS,
    UsEpaSensorStreamMetadata,
    fetch_us_epa_candidate_sensors,
    select_raw_observations_for_hour,
)
from services.air_quality_index.domain import AirQualityIndexProduct, ExclusionReason
from services.air_quality_index.hourly_measurements import (
    RawMeasurementInput,
    ceil_utc_hour,
    floor_utc_hour,
    normalize_utc,
    retrieve_raw_measurement_inputs,
)
from services.air_quality_index.us_epa import get_product, normalize_concentration_unit
from services.air_quality_index.us_epa_hourly_completeness import (
    SUPPORTED_PROVIDER_HOURLY_TIMESTAMP_SEMANTICS,
    SUPPORTED_SUBHOURLY_TIMESTAMP_SEMANTICS,
    EligibleHourlyConcentration,
    HourlyCompletenessAuditFlag,
)
from services.air_quality_index.us_epa_ozone import (
    OZONE_WINDOW_HOUR_COUNT,
    OzoneWindowCalculation,
    calculate_latest_ozone_window,
    construct_provider_hourly_ozone_hour,
    construct_subhourly_ozone_hour,
)


OZONE_SENSOR_SELECTION_RULE = (
    "calculated_then_verified_metadata_then_eight_hour_candidate_then_"
    "complete_window_then_valid_hours_then_sensor_id"
)


@dataclass(frozen=True)
class UsEpaOzoneSensorEvaluation:
    sensor: UsEpaSensorStreamMetadata
    metadata_is_verified_and_complete: bool
    metadata_exclusion_reason: Optional[ExclusionReason]
    blocking_reasons: Tuple[ExclusionReason, ...]
    audit_flags: Tuple[HourlyCompletenessAuditFlag, ...]
    hourly_inputs: Tuple[EligibleHourlyConcentration, ...]
    calculation: OzoneWindowCalculation
    measurement_ids: Tuple[int, ...]
    valid_sample_count: int
    valid_hour_count: int
    duplicate_observation_count: int
    rejected_observation_count: int
    off_frequency_observation_count: int

    @property
    def is_calculated(self) -> bool:
        return self.calculation.selected_candidate is not None


@dataclass(frozen=True)
class UsEpaOzoneDeviceResult:
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
    calculation: OzoneWindowCalculation
    selected_sensor: Optional[UsEpaSensorStreamMetadata]
    selected_sensor_reason: Optional[str]
    candidate_sensor_evaluations: Tuple[UsEpaOzoneSensorEvaluation, ...]
    measurement_ids: Tuple[int, ...]
    valid_sample_count: int
    blocking_reasons: Tuple[ExclusionReason, ...]


def resolve_ozone_sensor_metadata(
    sensor: UsEpaSensorStreamMetadata,
) -> tuple[Optional[ExclusionReason], bool, bool]:
    """Return blocking reason, provider-hourly flag, and verified status."""
    input_unit = sensor.input_unit_code or sensor.input_unit_symbol
    unit_check = normalize_concentration_unit("o3", 0, input_unit)
    if not unit_check.is_supported:
        return unit_check.exclusion_reason, False, False

    aggregation_period = (sensor.aggregation_period or "").strip().lower()
    provider_hourly = (
        aggregation_period == "1h"
        and sensor.hourly_concentration_provenance == VERIFIED_HOURLY_PROVENANCE
    )
    if aggregation_period == "1h":
        if not provider_hourly:
            return ExclusionReason.HOURLY_AGGREGATION_PROVENANCE_MISSING, False, False
        if (
            sensor.measurement_metadata_status
            != VERIFIED_MEASUREMENT_METADATA_STATUS
            or not sensor.measurement_metadata_managed_by
        ):
            return ExclusionReason.HOURLY_AGGREGATION_PROVENANCE_MISSING, True, False
        if sensor.hourly_timestamp_semantics not in SUPPORTED_PROVIDER_HOURLY_TIMESTAMP_SEMANTICS:
            return ExclusionReason.TIMESTAMP_SEMANTICS_UNKNOWN, True, False
        return None, True, True

    if sensor.expected_frequency_seconds is None:
        return ExclusionReason.EXPECTED_FREQUENCY_MISSING, False, False
    if (
        sensor.expected_frequency_seconds < 60
        or sensor.expected_frequency_seconds > 900
        or 3600 % sensor.expected_frequency_seconds != 0
    ):
        return ExclusionReason.UNSUPPORTED_INPUT_FREQUENCY, False, False
    if (
        sensor.measurement_duration_seconds is None
        or sensor.measurement_duration_seconds <= 0
        or sensor.source_aggregation_duration_seconds is None
        or sensor.source_aggregation_duration_seconds <= 0
        or sensor.measurement_metadata_status != VERIFIED_MEASUREMENT_METADATA_STATUS
        or not sensor.measurement_metadata_managed_by
    ):
        return (
            ExclusionReason.UNSUPPORTED_POLLUTANT_DURATION_FREQUENCY_COMBINATION,
            False,
            False,
        )
    if sensor.measurement_timestamp_semantics not in SUPPORTED_SUBHOURLY_TIMESTAMP_SEMANTICS:
        return ExclusionReason.TIMESTAMP_SEMANTICS_UNKNOWN, False, False
    return None, False, True


def _evaluate_ozone_sensor(
    sensor: UsEpaSensorStreamMetadata,
    raw_inputs: Sequence[RawMeasurementInput],
    *,
    window_started_at: datetime,
    window_ended_at: datetime,
) -> UsEpaOzoneSensorEvaluation:
    metadata_reason, provider_hourly, metadata_complete = resolve_ozone_sensor_metadata(sensor)
    hourly_inputs: list[EligibleHourlyConcentration] = []
    input_unit = sensor.input_unit_code or sensor.input_unit_symbol
    if metadata_reason is None:
        timestamp_semantics = (
            sensor.hourly_timestamp_semantics
            if provider_hourly
            else sensor.measurement_timestamp_semantics
        ) or ""
        for hour_index in range(OZONE_WINDOW_HOUR_COUNT):
            hour_start = window_started_at + timedelta(hours=hour_index)
            observations = select_raw_observations_for_hour(
                raw_inputs,
                interval_started_at=hour_start,
                timestamp_semantics=timestamp_semantics,
            )
            if provider_hourly:
                hourly_input = construct_provider_hourly_ozone_hour(
                    observations,
                    interval_started_at=hour_start,
                    input_unit=input_unit,
                    timestamp_semantics=timestamp_semantics,
                )
            else:
                hourly_input = construct_subhourly_ozone_hour(
                    observations,
                    interval_started_at=hour_start,
                    input_unit=input_unit,
                    expected_frequency_seconds=sensor.expected_frequency_seconds or 0,
                    measurement_duration_seconds=sensor.measurement_duration_seconds or 0,
                    source_aggregation_duration_seconds=(
                        sensor.source_aggregation_duration_seconds or 0
                    ),
                    timestamp_semantics=timestamp_semantics,
                )
            hourly_inputs.append(hourly_input)

    calculation = calculate_latest_ozone_window(
        hourly_inputs,
        window_started_at=window_started_at,
        window_ended_at=window_ended_at,
    )
    blocking_reasons: list[ExclusionReason] = []
    if metadata_reason is not None:
        blocking_reasons.append(metadata_reason)
    audit_flags: list[HourlyCompletenessAuditFlag] = []
    for hourly_input in hourly_inputs:
        for reason in hourly_input.exclusion_reasons:
            if reason not in blocking_reasons:
                blocking_reasons.append(reason)
        for flag in hourly_input.audit_flags:
            if flag not in audit_flags:
                audit_flags.append(flag)
    if calculation.exclusion_reason and calculation.exclusion_reason not in blocking_reasons:
        blocking_reasons.append(calculation.exclusion_reason)
    for candidate in (calculation.eight_hour_candidate, calculation.one_hour_candidate):
        if (
            candidate.candidate_status.value == "unavailable"
            and candidate.exclusion_reason is not None
            and candidate.exclusion_reason not in blocking_reasons
        ):
            blocking_reasons.append(candidate.exclusion_reason)

    measurement_ids = tuple(
        sorted(
            measurement_id
            for hourly_input in hourly_inputs
            if hourly_input.is_eligible
            for measurement_id in hourly_input.measurement_ids
        )
    )
    return UsEpaOzoneSensorEvaluation(
        sensor=sensor,
        metadata_is_verified_and_complete=metadata_complete,
        metadata_exclusion_reason=metadata_reason,
        blocking_reasons=tuple(blocking_reasons),
        audit_flags=tuple(audit_flags),
        hourly_inputs=tuple(hourly_inputs),
        calculation=calculation,
        measurement_ids=measurement_ids,
        valid_sample_count=sum(
            hourly_input.valid_observation_count
            for hourly_input in hourly_inputs
            if hourly_input.is_eligible
        ),
        valid_hour_count=sum(hourly_input.is_eligible for hourly_input in hourly_inputs),
        duplicate_observation_count=sum(
            len(hourly_input.duplicate_measurement_ids) for hourly_input in hourly_inputs
        ),
        rejected_observation_count=sum(
            len(hourly_input.rejected_measurement_ids) for hourly_input in hourly_inputs
        ),
        off_frequency_observation_count=sum(
            len(hourly_input.off_frequency_measurement_ids) for hourly_input in hourly_inputs
        ),
    )


def _selection_sort_key(
    evaluation: UsEpaOzoneSensorEvaluation,
) -> tuple[int, int, int, int, int, int]:
    return (
        -int(evaluation.is_calculated),
        -int(evaluation.metadata_is_verified_and_complete),
        -int(evaluation.calculation.eight_hour_candidate.is_calculated),
        -int(evaluation.valid_hour_count == OZONE_WINDOW_HOUR_COUNT),
        -evaluation.valid_hour_count,
        evaluation.sensor.sensor_id,
    )


def _calculate_ozone_for_window(
    *,
    product: AirQualityIndexProduct,
    sensors: Sequence[UsEpaSensorStreamMetadata],
    raw_inputs: Sequence[RawMeasurementInput],
    window_ended_at: datetime,
    limit: int | None,
) -> list[UsEpaOzoneDeviceResult]:
    """Evaluate one ozone window from already bounded database inputs."""
    window_started_at = window_ended_at - timedelta(hours=OZONE_WINDOW_HOUR_COUNT)
    raw_by_sensor: dict[int, list[RawMeasurementInput]] = {}
    for raw_input in raw_inputs:
        raw_by_sensor.setdefault(raw_input.sensor_id, []).append(raw_input)
    sensors_by_device: dict[int, list[UsEpaSensorStreamMetadata]] = {}
    for sensor in sensors:
        sensors_by_device.setdefault(sensor.device_id, []).append(sensor)

    results: list[UsEpaOzoneDeviceResult] = []
    for current_device_id, device_sensors in sensors_by_device.items():
        evaluations = tuple(
            _evaluate_ozone_sensor(
                sensor,
                raw_by_sensor.get(sensor.sensor_id, ()),
                window_started_at=window_started_at,
                window_ended_at=window_ended_at,
            )
            for sensor in device_sensors
        )
        representative = sorted(evaluations, key=_selection_sort_key)[0]
        selected_evaluation = representative if representative.is_calculated else None
        blocking_reasons = list(representative.blocking_reasons)
        if (
            selected_evaluation is None
            and ExclusionReason.NO_ELIGIBLE_SENSOR_STREAM not in blocking_reasons
        ):
            blocking_reasons.insert(0, ExclusionReason.NO_ELIGIBLE_SENSOR_STREAM)

        selected_measurement_ids: Tuple[int, ...] = ()
        selected_valid_sample_count = 0
        selected_observed_at = window_ended_at
        if selected_evaluation is not None:
            selected_candidate = selected_evaluation.calculation.selected_candidate
            if selected_candidate is None:
                raise RuntimeError("Calculated ozone evaluation has no selected candidate")
            selected_observed_at = selected_candidate.interval_ended_at
            if selected_candidate.aggregation_period == "1h":
                selected_hour = next(
                    hourly_input
                    for hourly_input in selected_evaluation.hourly_inputs
                    if (
                        hourly_input.interval_started_at
                        == selected_candidate.interval_started_at
                        and hourly_input.interval_ended_at
                        == selected_candidate.interval_ended_at
                    )
                )
                selected_measurement_ids = selected_hour.measurement_ids
                selected_valid_sample_count = selected_hour.valid_observation_count
            else:
                selected_measurement_ids = selected_evaluation.measurement_ids
                selected_valid_sample_count = selected_evaluation.valid_sample_count

        device = device_sensors[0]
        results.append(
            UsEpaOzoneDeviceResult(
                product=product,
                device_id=current_device_id,
                device_name=device.device_name,
                device_friendly_name=device.device_friendly_name,
                latitude=device.latitude,
                longitude=device.longitude,
                device_timezone=device.device_timezone,
                source_name=device.source_name,
                observed_at=selected_observed_at,
                window_started_at=window_started_at,
                window_ended_at=window_ended_at,
                calculation=representative.calculation,
                selected_sensor=(
                    selected_evaluation.sensor if selected_evaluation else None
                ),
                selected_sensor_reason=(
                    OZONE_SENSOR_SELECTION_RULE if selected_evaluation else None
                ),
                candidate_sensor_evaluations=evaluations,
                measurement_ids=selected_measurement_ids,
                valid_sample_count=selected_valid_sample_count,
                blocking_reasons=tuple(blocking_reasons),
            )
        )
    return sorted(results, key=lambda result: result.device_id)[:limit]


def calculate_latest_us_epa_ozone_aqi(
    session: Session,
    *,
    product_code: str,
    reference_time_utc: Optional[datetime] = None,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    limit: int | None = 100,
    current_time_utc: Optional[datetime] = None,
) -> list[UsEpaOzoneDeviceResult]:
    product = get_product(product_code)
    if product is None or product.product_code != "us_epa.o3.latest":
        raise ValueError(f"Unknown U.S. EPA ozone AQI product: {product_code}")
    now = normalize_utc(current_time_utc or datetime.now(timezone.utc))
    requested_boundary = normalize_utc(reference_time_utc) if reference_time_utc else now
    window_ended_at = min(floor_utc_hour(now), floor_utc_hour(requested_boundary))
    window_started_at = window_ended_at - timedelta(hours=OZONE_WINDOW_HOUR_COUNT)

    sensors = fetch_us_epa_candidate_sensors(
        session,
        "o3",
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
    )
    if not sensors:
        return []
    raw_inputs = retrieve_raw_measurement_inputs(
        session,
        parameter_codes=("o3",),
        start_utc=window_started_at,
        end_utc=window_ended_at,
        include_end=True,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        sensor_ids=tuple(sensor.sensor_id for sensor in sensors),
    )
    return _calculate_ozone_for_window(
        product=product,
        sensors=sensors,
        raw_inputs=raw_inputs,
        window_ended_at=window_ended_at,
        limit=limit,
    )


def calculate_us_epa_ozone_history(
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
) -> list[UsEpaOzoneDeviceResult]:
    """Return at most 2,160 hourly ozone evaluations from two bounded queries."""
    product = get_product(product_code)
    if product is None or product.product_code != "us_epa.o3.latest":
        raise ValueError(f"Unknown U.S. EPA ozone AQI product: {product_code}")
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
        "o3",
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        device_ids=device_ids,
    )
    if not sensors:
        return []
    raw_inputs = retrieve_raw_measurement_inputs(
        session,
        parameter_codes=("o3",),
        start_utc=boundaries[0] - timedelta(hours=OZONE_WINDOW_HOUR_COUNT),
        end_utc=boundaries[-1],
        include_end=True,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        sensor_ids=tuple(sensor.sensor_id for sensor in sensors),
        device_ids=device_ids,
    )
    raw_input_timestamps = [raw_input.observed_at for raw_input in raw_inputs]
    results: list[UsEpaOzoneDeviceResult] = []
    for boundary in boundaries:
        boundary_results = _calculate_ozone_for_window(
            product=product,
            sensors=sensors,
            raw_inputs=raw_inputs[
                bisect_left(
                    raw_input_timestamps,
                    boundary - timedelta(hours=OZONE_WINDOW_HOUR_COUNT),
                ) : bisect_right(raw_input_timestamps, boundary)
            ],
            window_ended_at=boundary,
            limit=limit,
        )
        # The selected one-hour ozone candidate may occur earlier in its
        # evaluation window. History is keyed by the evaluation boundary,
        # while the selected candidate interval remains separately available.
        results.extend(
            replace(result, observed_at=boundary)
            for result in boundary_results
        )
    return sorted(
        results,
        key=lambda result: (result.observed_at, result.device_id),
    )[:limit]
