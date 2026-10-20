from __future__ import annotations

"""Database orchestration for completed-local-day U.S. EPA PM AQI."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from services.aqi_engine import (
    UsEpaSensorStreamMetadata,
    fetch_us_epa_candidate_sensors,
    resolve_us_epa_sensor_metadata,
    select_raw_observations_for_hour,
)
from services.air_quality_index.domain import (
    AirQualityIndexProduct,
    ExclusionReason,
)
from services.air_quality_index.hourly_measurements import (
    RawMeasurementInput,
    normalize_utc,
    retrieve_raw_measurement_inputs,
)
from services.air_quality_index.us_epa import (
    DataQualificationStatus,
    UsEpaCalculationResult,
    get_product,
)
from services.air_quality_index.us_epa_completed_day import (
    CompletedDayCalculation,
    CompletedLocalDayResolution,
    CompletedLocalDayWindow,
    calculate_completed_day_pm,
    generate_inclusive_local_dates,
    resolve_completed_local_day,
    resolve_represented_local_day,
)
from services.air_quality_index.us_epa_hourly_completeness import (
    CompletenessApplicationProvenance,
    EligibleHourlyConcentration,
    HourlyCompletenessAuditFlag,
    construct_provider_hourly_pm_hour,
    construct_subhourly_pm_hour,
)


COMPLETED_DAY_SENSOR_SELECTION_PROVENANCE = CompletenessApplicationProvenance(
    provenance_code="compass_aq.completed_day_sensor_selection",
    description=(
        "CompassAQ selects one eligible stream by verified metadata, valid-hour "
        "count, achieved daily completeness, then stable sensor ID. Streams are "
        "never averaged together."
    ),
)


@dataclass(frozen=True)
class IndexedRawMeasurementInputs:
    """One sensor's sorted rows and reusable UTC timestamp search index."""

    raw_inputs: Tuple[RawMeasurementInput, ...]
    observed_times_utc: Tuple[datetime, ...]


@dataclass(frozen=True)
class UsEpaCompletedDaySensorEvaluation:
    sensor: UsEpaSensorStreamMetadata
    local_day_resolution: CompletedLocalDayResolution
    metadata_is_verified_and_complete: bool
    hourly_inputs: Tuple[EligibleHourlyConcentration, ...]
    completed_day_calculation: Optional[CompletedDayCalculation]
    blocking_reasons: Tuple[ExclusionReason, ...]
    audit_flags: Tuple[HourlyCompletenessAuditFlag, ...]
    measurement_ids: Tuple[int, ...]
    valid_sample_count: int
    duplicate_observation_count: int
    rejected_observation_count: int
    off_frequency_observation_count: int

    @property
    def is_daily_eligible(self) -> bool:
        return (
            not self.blocking_reasons
            and self.completed_day_calculation is not None
            and self.completed_day_calculation.is_eligible
        )

    @property
    def expected_hour_count(self) -> int:
        window = self.local_day_resolution.window
        return window.expected_hour_count if window is not None else 0

    @property
    def valid_hour_count(self) -> int:
        if self.completed_day_calculation is None:
            return 0
        return self.completed_day_calculation.completeness.valid_hour_count

    @property
    def achieved_completeness_fraction(self) -> float:
        if self.completed_day_calculation is None:
            return 0.0
        return (
            self.completed_day_calculation.completeness
            .achieved_completeness_fraction
        )


@dataclass(frozen=True)
class UsEpaCompletedDayDeviceResult:
    product: AirQualityIndexProduct
    device_id: int
    device_name: str
    device_friendly_name: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    device_timezone: Optional[str]
    source_name: Optional[str]
    observed_at: datetime
    represented_local_date: Optional[date]
    local_day_window: Optional[CompletedLocalDayWindow]
    calculation: Optional[UsEpaCalculationResult]
    completed_day_calculation: Optional[CompletedDayCalculation]
    selected_sensor: Optional[UsEpaSensorStreamMetadata]
    selected_sensor_reason: Optional[str]
    candidate_sensor_evaluations: Tuple[
        UsEpaCompletedDaySensorEvaluation, ...
    ]
    blocking_reasons: Tuple[ExclusionReason, ...]
    audit_flags: Tuple[HourlyCompletenessAuditFlag, ...]
    measurement_ids: Tuple[int, ...]
    data_qualification_status: DataQualificationStatus
    application_provenance: Tuple[CompletenessApplicationProvenance, ...]


def _construct_hourly_inputs(
    sensor: UsEpaSensorStreamMetadata,
    raw_inputs: Sequence[RawMeasurementInput],
    *,
    parameter_code: str,
    window: CompletedLocalDayWindow,
    provider_hourly: bool,
) -> Tuple[EligibleHourlyConcentration, ...]:
    timestamp_semantics = (
        sensor.hourly_timestamp_semantics
        if provider_hourly
        else sensor.measurement_timestamp_semantics
    ) or ""
    input_unit = sensor.input_unit_code or sensor.input_unit_symbol
    hourly_inputs: list[EligibleHourlyConcentration] = []
    for hour_start in window.hourly_interval_starts_utc:
        observations = select_raw_observations_for_hour(
            raw_inputs,
            interval_started_at=hour_start,
            timestamp_semantics=timestamp_semantics,
        )
        if provider_hourly:
            hourly_input = construct_provider_hourly_pm_hour(
                observations,
                interval_started_at=hour_start,
                parameter_code=parameter_code,
                input_unit=input_unit,
                timestamp_semantics=timestamp_semantics,
            )
        else:
            hourly_input = construct_subhourly_pm_hour(
                observations,
                interval_started_at=hour_start,
                parameter_code=parameter_code,
                input_unit=input_unit,
                expected_frequency_seconds=sensor.expected_frequency_seconds or 0,
                measurement_duration_seconds=(
                    sensor.measurement_duration_seconds or 0
                ),
                source_aggregation_duration_seconds=(
                    sensor.source_aggregation_duration_seconds or 0
                ),
                timestamp_semantics=timestamp_semantics,
            )
        hourly_inputs.append(hourly_input)
    return tuple(hourly_inputs)


def _raw_inputs_for_window(
    indexed_inputs: IndexedRawMeasurementInputs,
    *,
    window: CompletedLocalDayWindow,
    timestamp_semantics: str,
) -> Sequence[RawMeasurementInput]:
    """Slice one sensor's sorted measurements to a single represented date."""
    if not indexed_inputs.raw_inputs:
        return ()
    interval_end_semantics = timestamp_semantics in {
        "interval_end",
        "provider_received_at",
        "hour_end",
    }
    if interval_end_semantics:
        start_index = bisect_right(
            indexed_inputs.observed_times_utc,
            window.utc_window_started_at,
        )
        end_index = bisect_right(
            indexed_inputs.observed_times_utc,
            window.utc_window_ended_at,
        )
    else:
        start_index = bisect_left(
            indexed_inputs.observed_times_utc,
            window.utc_window_started_at,
        )
        end_index = bisect_left(
            indexed_inputs.observed_times_utc,
            window.utc_window_ended_at,
        )
    return indexed_inputs.raw_inputs[start_index:end_index]


def _evaluate_sensor_stream(
    sensor: UsEpaSensorStreamMetadata,
    indexed_inputs: IndexedRawMeasurementInputs,
    *,
    parameter_code: str,
    local_day_resolution: CompletedLocalDayResolution,
) -> UsEpaCompletedDaySensorEvaluation:
    if not local_day_resolution.is_available:
        return UsEpaCompletedDaySensorEvaluation(
            sensor=sensor,
            local_day_resolution=local_day_resolution,
            metadata_is_verified_and_complete=False,
            hourly_inputs=(),
            completed_day_calculation=None,
            blocking_reasons=local_day_resolution.blocking_reasons,
            audit_flags=(),
            measurement_ids=(),
            valid_sample_count=0,
            duplicate_observation_count=0,
            rejected_observation_count=0,
            off_frequency_observation_count=0,
        )

    metadata_reason, provider_hourly, metadata_complete = (
        resolve_us_epa_sensor_metadata(sensor, parameter_code=parameter_code)
    )
    if metadata_reason is not None:
        return UsEpaCompletedDaySensorEvaluation(
            sensor=sensor,
            local_day_resolution=local_day_resolution,
            metadata_is_verified_and_complete=metadata_complete,
            hourly_inputs=(),
            completed_day_calculation=None,
            blocking_reasons=(metadata_reason,),
            audit_flags=(),
            measurement_ids=(),
            valid_sample_count=0,
            duplicate_observation_count=0,
            rejected_observation_count=0,
            off_frequency_observation_count=0,
        )

    window = local_day_resolution.window
    if window is None:
        raise RuntimeError("Available local-day resolution has no window")
    timestamp_semantics = (
        sensor.hourly_timestamp_semantics
        if provider_hourly
        else sensor.measurement_timestamp_semantics
    ) or ""
    window_raw_inputs = _raw_inputs_for_window(
        indexed_inputs,
        window=window,
        timestamp_semantics=timestamp_semantics,
    )
    hourly_inputs = _construct_hourly_inputs(
        sensor,
        window_raw_inputs,
        parameter_code=parameter_code,
        window=window,
        provider_hourly=provider_hourly,
    )
    daily_calculation = calculate_completed_day_pm(
        parameter_code=parameter_code,
        represented_local_date=window.represented_local_date,
        expected_hour_count=window.expected_hour_count,
        hourly_inputs=hourly_inputs,
    )
    return UsEpaCompletedDaySensorEvaluation(
        sensor=sensor,
        local_day_resolution=local_day_resolution,
        metadata_is_verified_and_complete=metadata_complete,
        hourly_inputs=hourly_inputs,
        completed_day_calculation=daily_calculation,
        blocking_reasons=daily_calculation.blocking_reasons,
        audit_flags=daily_calculation.audit_flags,
        measurement_ids=daily_calculation.measurement_ids,
        valid_sample_count=sum(
            hourly_input.valid_observation_count
            for hourly_input in hourly_inputs
            if hourly_input.is_eligible
        ),
        duplicate_observation_count=sum(
            len(hourly_input.duplicate_measurement_ids)
            for hourly_input in hourly_inputs
        ),
        rejected_observation_count=sum(
            len(hourly_input.rejected_measurement_ids)
            for hourly_input in hourly_inputs
        ),
        off_frequency_observation_count=sum(
            len(hourly_input.off_frequency_measurement_ids)
            for hourly_input in hourly_inputs
        ),
    )


def _selection_sort_key(
    evaluation: UsEpaCompletedDaySensorEvaluation,
) -> tuple[int, int, int, float, int]:
    return (
        -int(evaluation.metadata_is_verified_and_complete),
        -int(evaluation.is_daily_eligible),
        -evaluation.valid_hour_count,
        -evaluation.achieved_completeness_fraction,
        evaluation.sensor.sensor_id,
    )


def _require_completed_day_product(product_code: str) -> AirQualityIndexProduct:
    product = get_product(product_code)
    if (
        product is None
        or product.product_kind != "completed_day"
        or product.parameter_code not in {"pm25", "pm10"}
    ):
        raise ValueError(
            "Completed-day U.S. EPA AQI supports only "
            "us_epa.pm25.completed_day and us_epa.pm10.completed_day: "
            f"{product_code}"
        )
    return product


def _group_and_limit_sensors(
    sensors: Sequence[UsEpaSensorStreamMetadata],
    *,
    limit: int | None,
) -> dict[int, list[UsEpaSensorStreamMetadata]]:
    sensors_by_device: dict[int, list[UsEpaSensorStreamMetadata]] = {}
    for sensor in sorted(
        sensors,
        key=lambda item: (item.device_id, item.sensor_id),
    ):
        sensors_by_device.setdefault(sensor.device_id, []).append(sensor)
    limited_device_ids = sorted(sensors_by_device)[:limit]
    return {
        device_id: sensors_by_device[device_id]
        for device_id in limited_device_ids
    }


def _retrieve_grouped_raw_inputs(
    session: Session,
    *,
    parameter_code: str,
    sensors_by_device: dict[int, list[UsEpaSensorStreamMetadata]],
    resolutions: Sequence[CompletedLocalDayResolution],
    device_id: Optional[int],
    external_api_name: Optional[str],
    bbox: Optional[Tuple[float, float, float, float]],
) -> dict[int, IndexedRawMeasurementInputs]:
    available_windows = [
        resolution.window
        for resolution in resolutions
        if resolution.is_available and resolution.window is not None
    ]
    if not available_windows:
        return {}
    selected_sensor_ids = tuple(
        sensor.sensor_id
        for device_sensors in sensors_by_device.values()
        for sensor in device_sensors
    )
    raw_inputs = retrieve_raw_measurement_inputs(
        session,
        parameter_codes=(parameter_code,),
        start_utc=min(
            window.utc_window_started_at for window in available_windows
        ),
        end_utc=max(
            window.utc_window_ended_at for window in available_windows
        ),
        include_end=True,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        sensor_ids=selected_sensor_ids,
    )
    raw_inputs_by_sensor: dict[int, list[RawMeasurementInput]] = {}
    for raw_input in raw_inputs:
        raw_inputs_by_sensor.setdefault(raw_input.sensor_id, []).append(raw_input)
    return {
        sensor_id: IndexedRawMeasurementInputs(
            raw_inputs=tuple(sensor_inputs),
            observed_times_utc=tuple(
                normalize_utc(raw_input.observed_at)
                for raw_input in sensor_inputs
            ),
        )
        for sensor_id, sensor_inputs in raw_inputs_by_sensor.items()
    }


def _calculate_device_date_result(
    *,
    product: AirQualityIndexProduct,
    device_sensors: Sequence[UsEpaSensorStreamMetadata],
    resolution: CompletedLocalDayResolution,
    inputs_by_sensor: dict[int, IndexedRawMeasurementInputs],
    fallback_observed_at: datetime,
) -> UsEpaCompletedDayDeviceResult:
    evaluations = tuple(
        _evaluate_sensor_stream(
            sensor,
            inputs_by_sensor.get(
                sensor.sensor_id,
                IndexedRawMeasurementInputs((), ()),
            ),
            parameter_code=product.parameter_code or "",
            local_day_resolution=resolution,
        )
        for sensor in sorted(device_sensors, key=lambda item: item.sensor_id)
    )
    eligible_evaluations = sorted(
        (
            evaluation
            for evaluation in evaluations
            if evaluation.is_daily_eligible
        ),
        key=_selection_sort_key,
    )
    selected = eligible_evaluations[0] if eligible_evaluations else None
    if selected is not None:
        completed_day_calculation = selected.completed_day_calculation
        if completed_day_calculation is None:
            raise RuntimeError("Eligible daily evaluation has no calculation")
        calculation = completed_day_calculation.calculation
        blocking_reasons: Tuple[ExclusionReason, ...] = ()
        audit_flags = completed_day_calculation.audit_flags
        measurement_ids = completed_day_calculation.measurement_ids
        selected_sensor = selected.sensor
        selection_reason = (
            "verified_metadata_then_eligible_daily_result_then_valid_hour_"
            "count_then_achieved_daily_completeness_then_sensor_id"
        )
        application_provenance = (
            *completed_day_calculation.application_provenance,
            COMPLETED_DAY_SENSOR_SELECTION_PROVENANCE,
        )
    else:
        completed_day_calculation = None
        calculation = None
        candidate_reasons = tuple(
            dict.fromkeys(
                reason
                for evaluation in evaluations
                for reason in evaluation.blocking_reasons
            )
        )
        blocking_reasons = (
            ExclusionReason.NO_ELIGIBLE_SENSOR_STREAM,
            *candidate_reasons,
        )
        audit_flags = tuple(
            dict.fromkeys(
                flag
                for evaluation in evaluations
                for flag in evaluation.audit_flags
            )
        )
        measurement_ids = ()
        selected_sensor = None
        selection_reason = None
        application_provenance = (COMPLETED_DAY_SENSOR_SELECTION_PROVENANCE,)

    device = device_sensors[0]
    window = resolution.window
    return UsEpaCompletedDayDeviceResult(
        product=product,
        device_id=device.device_id,
        device_name=device.device_name,
        device_friendly_name=device.device_friendly_name,
        latitude=device.latitude,
        longitude=device.longitude,
        device_timezone=device.device_timezone,
        source_name=device.source_name,
        observed_at=(window.utc_window_ended_at if window else fallback_observed_at),
        represented_local_date=resolution.represented_local_date,
        local_day_window=window,
        calculation=calculation,
        completed_day_calculation=completed_day_calculation,
        selected_sensor=selected_sensor,
        selected_sensor_reason=selection_reason,
        candidate_sensor_evaluations=evaluations,
        blocking_reasons=blocking_reasons,
        audit_flags=audit_flags,
        measurement_ids=measurement_ids,
        data_qualification_status=DataQualificationStatus.NOT_EVALUATED,
        application_provenance=application_provenance,
    )


def calculate_latest_us_epa_completed_day_aqi(
    session: Session,
    *,
    product_code: str,
    reference_time_utc: Optional[datetime] = None,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    limit: int | None = 100,
    current_time_utc: Optional[datetime] = None,
) -> list[UsEpaCompletedDayDeviceResult]:
    product = _require_completed_day_product(product_code)

    now = normalize_utc(current_time_utc or datetime.now(timezone.utc))
    requested_time = (
        normalize_utc(reference_time_utc) if reference_time_utc else now
    )
    evaluation_time = min(now, requested_time)
    sensors = fetch_us_epa_candidate_sensors(
        session,
        product.parameter_code,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
    )
    if not sensors:
        return []
    sensors_by_device = _group_and_limit_sensors(sensors, limit=limit)
    day_resolution_by_device = {
        current_device_id: resolve_completed_local_day(
            evaluation_time,
            device_sensors[0].device_timezone,
        )
        for current_device_id, device_sensors in sensors_by_device.items()
    }
    inputs_by_sensor = _retrieve_grouped_raw_inputs(
        session,
        parameter_code=product.parameter_code,
        sensors_by_device=sensors_by_device,
        resolutions=tuple(day_resolution_by_device.values()),
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
    )
    return [
        _calculate_device_date_result(
            product=product,
            device_sensors=sensors_by_device[current_device_id],
            resolution=day_resolution_by_device[current_device_id],
            inputs_by_sensor=inputs_by_sensor,
            fallback_observed_at=evaluation_time,
        )
        for current_device_id in sorted(sensors_by_device)
    ]


def calculate_us_epa_completed_day_history(
    session: Session,
    *,
    product_code: str,
    start_local_date: date,
    end_local_date: date,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    limit: int = 100,
    current_time_utc: Optional[datetime] = None,
) -> list[UsEpaCompletedDayDeviceResult]:
    """Calculate gap-complete historical AQI for each selected device/date."""
    product = _require_completed_day_product(product_code)
    represented_dates = generate_inclusive_local_dates(
        start_local_date,
        end_local_date,
    )
    now = normalize_utc(current_time_utc or datetime.now(timezone.utc))
    sensors = fetch_us_epa_candidate_sensors(
        session,
        product.parameter_code,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
    )
    if not sensors:
        return []
    sensors_by_device = _group_and_limit_sensors(sensors, limit=limit)

    resolutions_by_device_date: dict[
        tuple[int, date], CompletedLocalDayResolution
    ] = {}
    for current_device_id, device_sensors in sensors_by_device.items():
        timezone_name = device_sensors[0].device_timezone
        for represented_date in represented_dates:
            resolution = resolve_represented_local_day(
                represented_date,
                timezone_name,
            )
            window = resolution.window
            if (
                resolution.is_available
                and window is not None
                and window.utc_window_ended_at > now
            ):
                resolution = CompletedLocalDayResolution(
                    window=window,
                    blocking_reasons=(
                        ExclusionReason.COMPLETED_LOCAL_DAY_NOT_AVAILABLE,
                    ),
                    represented_local_date=represented_date,
                )
            resolutions_by_device_date[(current_device_id, represented_date)] = (
                resolution
            )

    inputs_by_sensor = _retrieve_grouped_raw_inputs(
        session,
        parameter_code=product.parameter_code,
        sensors_by_device=sensors_by_device,
        resolutions=tuple(resolutions_by_device_date.values()),
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
    )
    return [
        _calculate_device_date_result(
            product=product,
            device_sensors=sensors_by_device[current_device_id],
            resolution=resolutions_by_device_date[
                (current_device_id, represented_date)
            ],
            inputs_by_sensor=inputs_by_sensor,
            fallback_observed_at=now,
        )
        for current_device_id in sorted(sensors_by_device)
        for represented_date in represented_dates
    ]
