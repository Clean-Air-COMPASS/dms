from __future__ import annotations

"""Database service for documented Philippine DENR-EMB AQI products."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
from typing import Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .domain import AirQualityIndexProduct, ExclusionReason
from .hourly_measurements import (
    HourlySensorStreamMetadata,
    RawMeasurementInput,
    floor_utc_hour,
    normalize_utc,
    retrieve_candidate_sensor_streams,
    retrieve_raw_measurement_inputs,
)
from .hourly_pm_completeness import (
    RawHourlyObservation,
    assign_observations_to_expected_positions,
    select_raw_observations_for_hour,
)
from .philippines_denr import (
    CALCULATION_TIMEZONE,
    DEFAULT_PRODUCT_CODE,
    PHILIPPINES_DENR_PRODUCTS,
    PhilippineAqiCalculationResult,
    calculate_component_aqi,
    calculate_ozone_aqi,
    normalize_concentration_unit,
)


MANILA_TIMEZONE = ZoneInfo(CALCULATION_TIMEZONE)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
SUPPORTED_SUBHOURLY_TIMESTAMP_SEMANTICS = (
    "interval_start",
    "interval_end",
    "provider_received_at",
)
SUPPORTED_PROVIDER_HOURLY_TIMESTAMP_SEMANTICS = ("hour_start", "hour_end")


@dataclass(frozen=True)
class QualifiedPhilippineHour:
    interval_started_at: datetime
    interval_ended_at: datetime
    concentration: Optional[Decimal]
    normalized_unit: Optional[str]
    eligibility_status: str
    exclusion_reason: Optional[ExclusionReason]
    expected_observation_count: int
    valid_observation_count: int
    required_valid_observation_count: int
    measurement_ids: Tuple[int, ...]
    duplicate_measurement_ids: Tuple[int, ...]
    rejected_measurement_ids: Tuple[int, ...]
    off_frequency_measurement_ids: Tuple[int, ...]

    @property
    def is_eligible(self) -> bool:
        return self.eligibility_status == "eligible"


@dataclass(frozen=True)
class PhilippinePeriodCompleteness:
    eligibility_status: str
    exclusion_reason: Optional[ExclusionReason]
    expected_hour_count: int
    valid_hour_count: int
    required_valid_hour_count: int
    block_valid_hour_counts: Tuple[int, ...]
    maximum_consecutive_missing_hours: int


@dataclass(frozen=True)
class PhilippineSensorPeriodEvaluation:
    sensor: HourlySensorStreamMetadata
    interval_started_at: datetime
    interval_ended_at: datetime
    represented_local_date: Optional[date]
    calculation: PhilippineAqiCalculationResult
    eligibility_status: str
    exclusion_reason: Optional[ExclusionReason]
    expected_hour_count: int
    valid_hour_count: int
    required_valid_hour_count: int
    block_valid_hour_counts: Tuple[int, ...]
    maximum_consecutive_missing_hours: int
    concentration: Optional[Decimal]
    normalized_unit: Optional[str]
    measurement_ids: Tuple[int, ...]
    hourly_inputs: Tuple[QualifiedPhilippineHour, ...]


@dataclass(frozen=True)
class PhilippineDeviceAqiResult:
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
    local_period_started_at: datetime
    local_period_ended_at: datetime
    utc_window_started_at: datetime
    utc_window_ended_at: datetime
    calculation: PhilippineAqiCalculationResult
    coverage_status: str
    selected_sensor_id: Optional[int]
    selected_sensor_reason: Optional[str]
    measurement_ids: Tuple[int, ...]
    candidate_sensor_evaluations: Tuple[PhilippineSensorPeriodEvaluation, ...]


def resolve_product(product_code: Optional[str]) -> AirQualityIndexProduct:
    selected_code = (product_code or DEFAULT_PRODUCT_CODE).strip().lower()
    product = next(
        (item for item in PHILIPPINES_DENR_PRODUCTS if item.product_code == selected_code),
        None,
    )
    if product is None:
        raise ValueError(f"Unknown Philippines AQI product: {selected_code}")
    return product


def _metadata_exclusion_reason(
    sensor: HourlySensorStreamMetadata,
) -> Optional[ExclusionReason]:
    unit_check = normalize_concentration_unit(
        sensor.parameter_code,
        0,
        sensor.input_unit_code or sensor.input_unit_symbol,
    )
    if not unit_check.is_supported:
        return unit_check.exclusion_reason
    if sensor.aggregation_period == "1h":
        if sensor.hourly_concentration_provenance != "provider_reported_hourly_average":
            return ExclusionReason.HOURLY_AGGREGATION_PROVENANCE_MISSING
        if (
            sensor.measurement_metadata_status != "provider_documented"
            or not sensor.measurement_metadata_managed_by
        ):
            return ExclusionReason.HOURLY_AGGREGATION_PROVENANCE_MISSING
        if sensor.hourly_timestamp_semantics not in SUPPORTED_PROVIDER_HOURLY_TIMESTAMP_SEMANTICS:
            return ExclusionReason.TIMESTAMP_SEMANTICS_UNKNOWN
        return None
    if sensor.expected_frequency_seconds is None:
        return ExclusionReason.EXPECTED_FREQUENCY_MISSING
    if (
        sensor.expected_frequency_seconds <= 0
        or 3600 % sensor.expected_frequency_seconds != 0
        or sensor.measurement_duration_seconds is None
        or sensor.measurement_duration_seconds <= 0
        or sensor.measurement_duration_seconds > sensor.expected_frequency_seconds
        or sensor.source_aggregation_duration_seconds is None
        or sensor.source_aggregation_duration_seconds <= 0
        or sensor.source_aggregation_duration_seconds > sensor.expected_frequency_seconds
        or sensor.measurement_metadata_status != "provider_documented"
        or not sensor.measurement_metadata_managed_by
    ):
        return ExclusionReason.UNSUPPORTED_POLLUTANT_DURATION_FREQUENCY_COMBINATION
    if sensor.measurement_timestamp_semantics not in SUPPORTED_SUBHOURLY_TIMESTAMP_SEMANTICS:
        return ExclusionReason.TIMESTAMP_SEMANTICS_UNKNOWN
    return None


def _unavailable_calculation(
    parameter_code: str,
    component_code: str,
    reason: ExclusionReason,
    input_unit: object,
) -> PhilippineAqiCalculationResult:
    # The pure calculator owns the shape and all unavailable-state semantics.
    if reason in {ExclusionReason.UNSUPPORTED_UNIT, ExclusionReason.CONVERSION_NOT_SUPPORTED}:
        return calculate_component_aqi(parameter_code, component_code, 0, input_unit)
    result = calculate_component_aqi(parameter_code, component_code, -1, input_unit)
    return PhilippineAqiCalculationResult(
        parameter_code=result.parameter_code,
        component_code=component_code,
        calculation_status=result.calculation_status,
        exclusion_reason=reason,
        input_unit=result.input_unit,
        normalized_concentration=None,
        normalized_unit=None,
        preprocessed_concentration=None,
        numeric_value=None,
        category_code=None,
        category_label=None,
        internal_severity_rank=None,
        aqi_scale_status=None,
    )


def qualify_hour(
    sensor: HourlySensorStreamMetadata,
    raw_inputs: Sequence[RawMeasurementInput],
    *,
    interval_started_at: datetime,
) -> QualifiedPhilippineHour:
    interval_start = normalize_utc(interval_started_at)
    metadata_reason = _metadata_exclusion_reason(sensor)
    if metadata_reason is not None:
        return QualifiedPhilippineHour(
            interval_start,
            interval_start + HOUR,
            None,
            None,
            "ineligible",
            metadata_reason,
            0,
            0,
            0,
            (),
            (),
            (),
            (),
        )
    provider_hourly = sensor.aggregation_period == "1h"
    timestamp_semantics = (
        sensor.hourly_timestamp_semantics
        if provider_hourly
        else sensor.measurement_timestamp_semantics
    ) or ""
    observations = select_raw_observations_for_hour(
        raw_inputs,
        interval_started_at=interval_start,
        timestamp_semantics=timestamp_semantics,
    )
    input_unit = sensor.input_unit_code or sensor.input_unit_symbol
    if provider_hourly:
        expected_timestamp = interval_start if timestamp_semantics == "hour_start" else interval_start + HOUR
        valid: list[tuple[int, Decimal]] = []
        rejected: list[int] = []
        off_frequency: list[int] = []
        for observation in observations:
            normalized = normalize_concentration_unit(
                sensor.parameter_code, observation.concentration, input_unit
            )
            if not observation.is_valid or not normalized.is_supported or normalized.normalized_concentration is None:
                rejected.append(observation.measurement_id)
            elif normalize_utc(observation.observed_at) != expected_timestamp:
                off_frequency.append(observation.measurement_id)
            else:
                valid.append((observation.measurement_id, normalized.normalized_concentration))
        duplicate = tuple(item[0] for item in valid[1:])
        is_eligible = len(valid) == 1 and not rejected and not off_frequency
        reason = (
            None
            if is_eligible
            else ExclusionReason.DUPLICATE_OBSERVATION_INTERVAL
            if len(valid) > 1
            else ExclusionReason.OFF_FREQUENCY_OBSERVATIONS
            if off_frequency
            else ExclusionReason.NO_VALID_OBSERVATIONS
        )
        return QualifiedPhilippineHour(
            interval_start,
            interval_start + HOUR,
            valid[0][1] if is_eligible else None,
            normalize_concentration_unit(sensor.parameter_code, 0, input_unit).normalized_unit,
            "eligible" if is_eligible else "ineligible",
            reason,
            1,
            1 if is_eligible else 0,
            1,
            (valid[0][0],) if is_eligible else (),
            duplicate,
            tuple(sorted(rejected)),
            tuple(sorted(off_frequency)),
        )
    frequency = sensor.expected_frequency_seconds or 0
    expected_count = 3600 // frequency
    required_count = int(
        (Decimal(2700) / Decimal(frequency)).to_integral_value(rounding=ROUND_CEILING)
    )
    assignment = assign_observations_to_expected_positions(
        observations,
        interval_started_at=interval_start,
        target_duration_seconds=3600,
        expected_frequency_seconds=frequency,
        expected_observation_count=expected_count,
        timestamp_semantics=timestamp_semantics,
        parameter_code=sensor.parameter_code,
        input_unit=input_unit,
        concentration_normalizer=normalize_concentration_unit,
    )
    valid_count = len(assignment.accepted_observations)
    # Rejected and unassigned readings remain explicit provenance. They block
    # the hour only when too few unambiguous expected positions remain.
    is_eligible = valid_count >= required_count
    reason = (
        None
        if is_eligible
        else ExclusionReason.NO_VALID_OBSERVATIONS
        if valid_count == 0
        else ExclusionReason.HOURLY_COMPLETENESS_NOT_MET
    )
    concentration = (
        sum(item.normalized_concentration for item in assignment.accepted_observations)
        / Decimal(valid_count)
        if is_eligible
        else None
    )
    return QualifiedPhilippineHour(
        interval_start,
        interval_start + HOUR,
        concentration,
        normalize_concentration_unit(sensor.parameter_code, 0, input_unit).normalized_unit,
        "eligible" if is_eligible else "ineligible",
        reason,
        expected_count,
        valid_count,
        required_count,
        tuple(item.measurement_id for item in assignment.accepted_observations),
        assignment.duplicate_measurement_ids,
        assignment.rejected_measurement_ids,
        assignment.off_frequency_measurement_ids,
    )


def _maximum_consecutive_missing(hours: Sequence[QualifiedPhilippineHour]) -> int:
    maximum = current = 0
    for hour in hours:
        if hour.is_eligible:
            current = 0
        else:
            current += 1
            maximum = max(maximum, current)
    return maximum


def qualify_completed_day_hours(
    hours: Sequence[QualifiedPhilippineHour],
) -> PhilippinePeriodCompleteness:
    """Apply the representative-day rule to 24 positional Manila hours."""
    block_counts = tuple(
        sum(hour.is_eligible for hour in hours[offset : offset + 8])
        for offset in (0, 8, 16)
    )
    valid_count = sum(hour.is_eligible for hour in hours)
    maximum_missing = _maximum_consecutive_missing(hours)
    is_eligible = (
        len(hours) == 24
        and valid_count >= 18
        and all(count >= 6 for count in block_counts)
        and maximum_missing <= 2
    )
    return PhilippinePeriodCompleteness(
        eligibility_status="eligible" if is_eligible else "ineligible",
        exclusion_reason=(None if is_eligible else ExclusionReason.DAILY_COMPLETENESS_NOT_MET),
        expected_hour_count=24,
        valid_hour_count=valid_count,
        required_valid_hour_count=18,
        block_valid_hour_counts=block_counts,
        maximum_consecutive_missing_hours=maximum_missing,
    )


def qualify_rolling_eight_hour_hours(
    hours: Sequence[QualifiedPhilippineHour],
) -> PhilippinePeriodCompleteness:
    valid_count = sum(hour.is_eligible for hour in hours)
    is_eligible = len(hours) == 8 and valid_count >= 6
    return PhilippinePeriodCompleteness(
        eligibility_status="eligible" if is_eligible else "ineligible",
        exclusion_reason=(
            None
            if is_eligible
            else ExclusionReason.ROLLING_8_HOUR_COMPLETENESS_NOT_MET
        ),
        expected_hour_count=8,
        valid_hour_count=valid_count,
        required_valid_hour_count=6,
        block_valid_hour_counts=(),
        maximum_consecutive_missing_hours=_maximum_consecutive_missing(hours),
    )


def _component_code(product: AirQualityIndexProduct) -> str:
    return {
        "pm25": "pm25_24_hour",
        "pm10": "pm10_24_hour",
        "so2": "so2_24_hour",
        "co": "co_8_hour",
        "no2": "no2_1_hour",
        "o3": "ozone_latest_completed_window",
    }[product.parameter_code or ""]


def _evaluate_sensor_period(
    sensor: HourlySensorStreamMetadata,
    raw_inputs: Sequence[RawMeasurementInput],
    *,
    product: AirQualityIndexProduct,
    interval_started_at: datetime,
    interval_ended_at: datetime,
    represented_local_date: Optional[date],
) -> PhilippineSensorPeriodEvaluation:
    hours: list[QualifiedPhilippineHour] = []
    hour_start = interval_started_at
    while hour_start < interval_ended_at:
        hours.append(qualify_hour(sensor, raw_inputs, interval_started_at=hour_start))
        hour_start += HOUR
    valid_hours = [hour for hour in hours if hour.is_eligible]
    expected_hours = len(hours)
    parameter = product.parameter_code or ""
    if product.product_kind == "completed_day":
        completeness = qualify_completed_day_hours(hours)
    elif parameter in {"o3", "co"}:
        completeness = qualify_rolling_eight_hour_hours(hours)
    else:
        is_complete_hour = len(hours) == 1 and len(valid_hours) == 1
        completeness = PhilippinePeriodCompleteness(
            "eligible" if is_complete_hour else "ineligible",
            None if is_complete_hour else ExclusionReason.HOURLY_COMPLETENESS_NOT_MET,
            1,
            len(valid_hours),
            1,
            (),
            _maximum_consecutive_missing(hours),
        )
    eligible = completeness.eligibility_status == "eligible"
    exclusion = completeness.exclusion_reason
    concentration = (
        sum(hour.concentration for hour in valid_hours if hour.concentration is not None)
        / Decimal(len(valid_hours))
        if eligible
        else None
    )
    input_unit = valid_hours[0].normalized_unit if valid_hours else sensor.input_unit_code or sensor.input_unit_symbol
    if eligible and concentration is not None:
        if parameter == "o3":
            last_hour = hours[-1]
            calculation = calculate_ozone_aqi(
                concentration,
                input_unit,
                corresponding_one_hour_concentration=last_hour.concentration if last_hour.is_eligible else None,
                corresponding_one_hour_input_unit=last_hour.normalized_unit,
            )
        else:
            calculation = calculate_component_aqi(parameter, _component_code(product), concentration, input_unit)
        if not calculation.is_eligible:
            eligible = False
            exclusion = calculation.exclusion_reason
    else:
        calculation = _unavailable_calculation(parameter, _component_code(product), exclusion or ExclusionReason.MISSING_MEASUREMENTS, input_unit)
    return PhilippineSensorPeriodEvaluation(
        sensor=sensor,
        interval_started_at=interval_started_at,
        interval_ended_at=interval_ended_at,
        represented_local_date=represented_local_date,
        calculation=calculation,
        eligibility_status="eligible" if eligible else "ineligible",
        exclusion_reason=exclusion,
        expected_hour_count=expected_hours,
        valid_hour_count=completeness.valid_hour_count,
        required_valid_hour_count=completeness.required_valid_hour_count,
        block_valid_hour_counts=completeness.block_valid_hour_counts,
        maximum_consecutive_missing_hours=(
            completeness.maximum_consecutive_missing_hours
        ),
        concentration=concentration,
        normalized_unit=input_unit if isinstance(input_unit, str) else None,
        measurement_ids=tuple(
            measurement_id for hour in valid_hours for measurement_id in hour.measurement_ids
        ),
        hourly_inputs=tuple(hours),
    )


def _periods_for_range(
    product: AirQualityIndexProduct,
    start_utc: datetime,
    end_utc: datetime,
) -> list[tuple[datetime, datetime, Optional[date], datetime, datetime]]:
    start = normalize_utc(start_utc)
    end = normalize_utc(end_utc)
    periods: list[tuple[datetime, datetime, Optional[date], datetime, datetime]] = []
    if product.product_kind == "completed_day":
        local_date = start.astimezone(MANILA_TIMEZONE).date() - DAY
        last_date = end.astimezone(MANILA_TIMEZONE).date()
        while local_date <= last_date:
            local_start = datetime.combine(local_date, time.min, MANILA_TIMEZONE)
            local_end = local_start + DAY
            utc_start = local_start.astimezone(timezone.utc)
            utc_end = local_end.astimezone(timezone.utc)
            if start <= utc_end < end:
                periods.append((utc_start, utc_end, local_date, local_start, local_end))
            local_date += DAY
        return periods
    completed_end = floor_utc_hour(start)
    if completed_end < start:
        completed_end += HOUR
    while completed_end < end:
        duration = timedelta(hours=8 if product.parameter_code in {"o3", "co"} else 1)
        utc_start = completed_end - duration
        local_start = utc_start.astimezone(MANILA_TIMEZONE)
        local_end = completed_end.astimezone(MANILA_TIMEZONE)
        periods.append((utc_start, completed_end, None, local_start, local_end))
        completed_end += HOUR
    return periods


def calculate_philippine_aqi_history(
    session: Session,
    *,
    product_code: str,
    start_utc: datetime,
    end_utc: datetime,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    device_ids: Optional[Sequence[int]] = None,
    limit: int = 1000,
    include_empty_periods: bool = True,
) -> list[PhilippineDeviceAqiResult]:
    product = resolve_product(product_code)
    parameter = product.parameter_code or ""
    periods = _periods_for_range(product, start_utc, end_utc)
    if len(periods) > product.maximum_history_interval_count:
        raise ValueError(
            f"{product.product_code} supports at most "
            f"{product.maximum_history_interval_count} history intervals"
        )
    if not periods:
        return []
    sensors = retrieve_candidate_sensor_streams(
        session,
        parameter_codes=(parameter,),
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        device_ids=device_ids,
    )
    if not sensors:
        return []
    raw_inputs = retrieve_raw_measurement_inputs(
        session,
        parameter_codes=(parameter,),
        start_utc=min(period[0] for period in periods),
        end_utc=max(period[1] for period in periods),
        include_end=True,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        sensor_ids=tuple(sensor.sensor_id for sensor in sensors),
        device_ids=device_ids,
    )
    raw_by_sensor: dict[int, list[RawMeasurementInput]] = {}
    for raw_input in raw_inputs:
        raw_by_sensor.setdefault(raw_input.sensor_id, []).append(raw_input)
    sensors_by_device: dict[int, list[HourlySensorStreamMetadata]] = {}
    for sensor in sensors:
        sensors_by_device.setdefault(sensor.device_id, []).append(sensor)
    results: list[PhilippineDeviceAqiResult] = []
    for device_sensors in sensors_by_device.values():
        device = device_sensors[0]
        device_raw_inputs = [
            item
            for sensor in device_sensors
            for item in raw_by_sensor.get(sensor.sensor_id, ())
        ]
        first_device_observation = (
            min(item.observed_at for item in device_raw_inputs)
            if device_raw_inputs
            else None
        )
        last_device_observation = (
            max(item.observed_at for item in device_raw_inputs)
            if device_raw_inputs
            else None
        )
        for utc_start, utc_end, local_date, local_start, local_end in periods:
            if (
                not include_empty_periods
                and (
                    first_device_observation is None
                    or last_device_observation is None
                    or last_device_observation < utc_start
                    or first_device_observation > utc_end
                )
            ):
                continue
            evaluations = tuple(
                _evaluate_sensor_period(
                    sensor,
                    raw_by_sensor.get(sensor.sensor_id, ()),
                    product=product,
                    interval_started_at=utc_start,
                    interval_ended_at=utc_end,
                    represented_local_date=local_date,
                )
                for sensor in sorted(device_sensors, key=lambda item: item.sensor_id)
            )
            eligible = [evaluation for evaluation in evaluations if evaluation.eligibility_status == "eligible"]
            selected = eligible[0] if eligible else evaluations[0]
            results.append(
                PhilippineDeviceAqiResult(
                    product=product,
                    device_id=device.device_id,
                    device_name=device.device_name,
                    device_friendly_name=device.device_friendly_name,
                    latitude=device.latitude,
                    longitude=device.longitude,
                    device_timezone=device.device_timezone,
                    source_name=device.source_name,
                    observed_at=utc_end,
                    represented_local_date=local_date,
                    local_period_started_at=local_start,
                    local_period_ended_at=local_end,
                    utc_window_started_at=utc_start,
                    utc_window_ended_at=utc_end,
                    calculation=selected.calculation,
                    coverage_status="complete" if selected.eligibility_status == "eligible" else "none",
                    selected_sensor_id=selected.sensor.sensor_id if selected.eligibility_status == "eligible" else None,
                    selected_sensor_reason="lowest_eligible_sensor_id" if selected.eligibility_status == "eligible" else None,
                    measurement_ids=selected.measurement_ids,
                    candidate_sensor_evaluations=evaluations,
                )
            )
    return sorted(results, key=lambda item: (item.observed_at, item.device_id))[:limit]


def calculate_latest_philippine_aqi(
    session: Session,
    *,
    product_code: Optional[str] = None,
    reference_time_utc: Optional[datetime] = None,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    limit: int | None = 100,
) -> list[PhilippineDeviceAqiResult]:
    product = resolve_product(product_code)
    end = normalize_utc(reference_time_utc or datetime.now(timezone.utc))
    lookback = timedelta(days=366 if product.product_kind == "completed_day" else 90)
    history = calculate_philippine_aqi_history(
        session,
        product_code=product.product_code,
        start_utc=end - lookback,
        end_utc=end + timedelta(microseconds=1),
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        limit=100000,
        include_empty_periods=False,
    )
    by_device: dict[int, list[PhilippineDeviceAqiResult]] = {}
    for result in history:
        by_device.setdefault(result.device_id, []).append(result)
    latest: list[PhilippineDeviceAqiResult] = []
    for device_results in by_device.values():
        eligible = [item for item in device_results if item.calculation.is_eligible]
        latest.append(max(eligible or device_results, key=lambda item: item.observed_at))
    return sorted(latest, key=lambda item: item.device_id)[:limit]
