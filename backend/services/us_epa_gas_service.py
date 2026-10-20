from __future__ import annotations

"""Orchestration for latest-window U.S. EPA CO, NO2, and SO2 products.

Each sensor is qualified and calculated independently. Selection is based on
metadata quality and coverage; AQI magnitude never influences sensor choice.
Pollutant-specific regulatory calculations remain in their named modules.
"""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Sequence, Tuple

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
from services.air_quality_index.us_epa_carbon_monoxide import (
    CARBON_MONOXIDE_WINDOW_HOUR_COUNT,
    CarbonMonoxideWindowCalculation,
    calculate_latest_carbon_monoxide_window,
)
from services.air_quality_index.us_epa_gas_hourly import (
    construct_provider_hourly_gas_hour,
    construct_subhourly_gas_hour,
)
from services.air_quality_index.us_epa_nitrogen_dioxide import (
    NITROGEN_DIOXIDE_HOUR_COUNT,
    NitrogenDioxideHourCalculation,
    calculate_latest_nitrogen_dioxide_hour,
)
from services.air_quality_index.us_epa_sulfur_dioxide import (
    SULFUR_DIOXIDE_WINDOW_HOUR_COUNT,
    SulfurDioxideWindowCalculation,
    calculate_latest_sulfur_dioxide_window,
)
from services.air_quality_index.us_epa_hourly_completeness import (
    SUPPORTED_PROVIDER_HOURLY_TIMESTAMP_SEMANTICS,
    SUPPORTED_SUBHOURLY_TIMESTAMP_SEMANTICS,
    EligibleHourlyConcentration,
    HourlyCompletenessAuditFlag,
)


GAS_SENSOR_SELECTION_RULE = (
    "calculated_then_verified_metadata_then_complete_window_then_"
    "valid_hours_then_achieved_hourly_coverage_then_sensor_id"
)

GasWindowCalculation = (
    CarbonMonoxideWindowCalculation
    | NitrogenDioxideHourCalculation
    | SulfurDioxideWindowCalculation
)


@dataclass(frozen=True)
class UsEpaGasSensorEvaluation:
    sensor: UsEpaSensorStreamMetadata
    parameter_code: str
    metadata_is_verified_and_complete: bool
    metadata_exclusion_reason: Optional[ExclusionReason]
    blocking_reasons: Tuple[ExclusionReason, ...]
    audit_flags: Tuple[HourlyCompletenessAuditFlag, ...]
    hourly_inputs: Tuple[EligibleHourlyConcentration, ...]
    calculation: GasWindowCalculation
    measurement_ids: Tuple[int, ...]
    valid_sample_count: int
    selected_measurement_ids: Tuple[int, ...]
    selected_valid_sample_count: int
    valid_hour_count: int
    duplicate_observation_count: int
    rejected_observation_count: int
    off_frequency_observation_count: int

    @property
    def is_calculated(self) -> bool:
        return self.calculation.is_calculated

    @property
    def achieved_hourly_coverage(self) -> float:
        if not self.hourly_inputs:
            return 0.0
        return sum(
            hourly_input.achieved_completeness_fraction
            for hourly_input in self.hourly_inputs
        ) / len(self.hourly_inputs)


@dataclass(frozen=True)
class UsEpaGasDeviceResult:
    product: AirQualityIndexProduct
    parameter_code: str
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
    calculation: GasWindowCalculation
    selected_sensor: Optional[UsEpaSensorStreamMetadata]
    selected_sensor_reason: Optional[str]
    candidate_sensor_evaluations: Tuple[UsEpaGasSensorEvaluation, ...]
    measurement_ids: Tuple[int, ...]
    valid_sample_count: int
    blocking_reasons: Tuple[ExclusionReason, ...]


def resolve_gas_sensor_metadata(
    sensor: UsEpaSensorStreamMetadata,
    parameter_code: str,
) -> tuple[Optional[ExclusionReason], bool, bool]:
    """Return blocking reason, provider-hourly flag, and verified status."""
    input_unit = sensor.input_unit_code or sensor.input_unit_symbol
    unit_check = normalize_concentration_unit(parameter_code, 0, input_unit)
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
        if (
            sensor.hourly_timestamp_semantics
            not in SUPPORTED_PROVIDER_HOURLY_TIMESTAMP_SEMANTICS
        ):
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
    if (
        sensor.measurement_timestamp_semantics
        not in SUPPORTED_SUBHOURLY_TIMESTAMP_SEMANTICS
    ):
        return ExclusionReason.TIMESTAMP_SEMANTICS_UNKNOWN, False, False
    return None, False, True


def _construct_hourly_inputs(
    sensor: UsEpaSensorStreamMetadata,
    raw_inputs: Sequence[RawMeasurementInput],
    *,
    parameter_code: str,
    window_started_at: datetime,
    hour_count: int,
) -> tuple[
    Tuple[EligibleHourlyConcentration, ...],
    Optional[ExclusionReason],
    bool,
]:
    metadata_reason, provider_hourly, metadata_complete = resolve_gas_sensor_metadata(
        sensor, parameter_code
    )
    if metadata_reason is not None:
        return (), metadata_reason, metadata_complete

    input_unit = sensor.input_unit_code or sensor.input_unit_symbol
    timestamp_semantics = (
        sensor.hourly_timestamp_semantics
        if provider_hourly
        else sensor.measurement_timestamp_semantics
    ) or ""
    hourly_inputs: list[EligibleHourlyConcentration] = []
    for hour_index in range(hour_count):
        hour_start = window_started_at + timedelta(hours=hour_index)
        observations = select_raw_observations_for_hour(
            raw_inputs,
            interval_started_at=hour_start,
            timestamp_semantics=timestamp_semantics,
        )
        if provider_hourly:
            hourly_input = construct_provider_hourly_gas_hour(
                observations,
                interval_started_at=hour_start,
                parameter_code=parameter_code,
                input_unit=input_unit,
                timestamp_semantics=timestamp_semantics,
            )
        else:
            hourly_input = construct_subhourly_gas_hour(
                observations,
                interval_started_at=hour_start,
                parameter_code=parameter_code,
                input_unit=input_unit,
                expected_frequency_seconds=sensor.expected_frequency_seconds or 0,
                measurement_duration_seconds=sensor.measurement_duration_seconds or 0,
                source_aggregation_duration_seconds=(
                    sensor.source_aggregation_duration_seconds or 0
                ),
                timestamp_semantics=timestamp_semantics,
            )
        hourly_inputs.append(hourly_input)
    return tuple(hourly_inputs), None, metadata_complete


def _build_sensor_evaluation(
    *,
    sensor: UsEpaSensorStreamMetadata,
    parameter_code: str,
    metadata_reason: Optional[ExclusionReason],
    metadata_complete: bool,
    hourly_inputs: Tuple[EligibleHourlyConcentration, ...],
    calculation: GasWindowCalculation,
    source_measurements_missing: bool,
    selected_measurement_ids: Optional[Tuple[int, ...]] = None,
) -> UsEpaGasSensorEvaluation:
    """Collect common audit and provenance fields after a pollutant calculation."""
    blocking_reasons: list[ExclusionReason] = []
    if source_measurements_missing:
        blocking_reasons.append(ExclusionReason.MISSING_MEASUREMENTS)
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

    measurement_ids = tuple(
        sorted(
            measurement_id
            for hourly_input in hourly_inputs
            if hourly_input.is_eligible
            for measurement_id in hourly_input.measurement_ids
        )
    )
    selected_ids = measurement_ids if selected_measurement_ids is None else selected_measurement_ids
    selected_id_set = set(selected_ids)
    return UsEpaGasSensorEvaluation(
        sensor=sensor,
        parameter_code=parameter_code,
        metadata_is_verified_and_complete=metadata_complete,
        metadata_exclusion_reason=metadata_reason,
        blocking_reasons=tuple(blocking_reasons),
        audit_flags=tuple(audit_flags),
        hourly_inputs=hourly_inputs,
        calculation=calculation,
        measurement_ids=measurement_ids,
        valid_sample_count=sum(
            hourly_input.valid_observation_count
            for hourly_input in hourly_inputs
            if hourly_input.is_eligible
        ),
        selected_measurement_ids=selected_ids,
        selected_valid_sample_count=sum(
            hourly_input.valid_observation_count
            for hourly_input in hourly_inputs
            if selected_id_set.intersection(hourly_input.measurement_ids)
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


def _evaluate_carbon_monoxide_sensor(
    sensor: UsEpaSensorStreamMetadata,
    raw_inputs: Sequence[RawMeasurementInput],
    *,
    window_started_at: datetime,
    window_ended_at: datetime,
) -> UsEpaGasSensorEvaluation:
    hourly_inputs, metadata_reason, metadata_complete = _construct_hourly_inputs(
        sensor,
        raw_inputs,
        parameter_code="co",
        window_started_at=window_started_at,
        hour_count=CARBON_MONOXIDE_WINDOW_HOUR_COUNT,
    )
    calculation = calculate_latest_carbon_monoxide_window(
        hourly_inputs,
        window_started_at=window_started_at,
        window_ended_at=window_ended_at,
    )
    return _build_sensor_evaluation(
        sensor=sensor,
        parameter_code="co",
        metadata_reason=metadata_reason,
        metadata_complete=metadata_complete,
        hourly_inputs=hourly_inputs,
        calculation=calculation,
        source_measurements_missing=not raw_inputs,
    )


def _evaluate_nitrogen_dioxide_sensor(
    sensor: UsEpaSensorStreamMetadata,
    raw_inputs: Sequence[RawMeasurementInput],
    *,
    window_started_at: datetime,
    window_ended_at: datetime,
) -> UsEpaGasSensorEvaluation:
    hourly_inputs, metadata_reason, metadata_complete = _construct_hourly_inputs(
        sensor,
        raw_inputs,
        parameter_code="no2",
        window_started_at=window_started_at,
        hour_count=NITROGEN_DIOXIDE_HOUR_COUNT,
    )
    calculation = calculate_latest_nitrogen_dioxide_hour(
        hourly_inputs,
        window_started_at=window_started_at,
        window_ended_at=window_ended_at,
    )
    return _build_sensor_evaluation(
        sensor=sensor,
        parameter_code="no2",
        metadata_reason=metadata_reason,
        metadata_complete=metadata_complete,
        hourly_inputs=hourly_inputs,
        calculation=calculation,
        source_measurements_missing=not raw_inputs,
    )


def _evaluate_sulfur_dioxide_sensor(
    sensor: UsEpaSensorStreamMetadata,
    raw_inputs: Sequence[RawMeasurementInput],
    *,
    window_started_at: datetime,
    window_ended_at: datetime,
) -> UsEpaGasSensorEvaluation:
    hourly_inputs, metadata_reason, metadata_complete = _construct_hourly_inputs(
        sensor,
        raw_inputs,
        parameter_code="so2",
        window_started_at=window_started_at,
        hour_count=SULFUR_DIOXIDE_WINDOW_HOUR_COUNT,
    )
    calculation = calculate_latest_sulfur_dioxide_window(
        hourly_inputs,
        window_started_at=window_started_at,
        window_ended_at=window_ended_at,
    )
    selected_measurement_ids = (
        calculation.selected_candidate.measurement_ids
        if calculation.selected_candidate
        else ()
    )
    return _build_sensor_evaluation(
        sensor=sensor,
        parameter_code="so2",
        metadata_reason=metadata_reason,
        metadata_complete=metadata_complete,
        hourly_inputs=hourly_inputs,
        calculation=calculation,
        source_measurements_missing=not raw_inputs,
        selected_measurement_ids=selected_measurement_ids,
    )


def _selection_sort_key(
    evaluation: UsEpaGasSensorEvaluation,
) -> tuple[int, int, int, int, float, int]:
    expected_hours = evaluation.calculation.expected_hour_count
    return (
        -int(evaluation.is_calculated),
        -int(evaluation.metadata_is_verified_and_complete),
        -int(evaluation.valid_hour_count == expected_hours),
        -evaluation.valid_hour_count,
        -evaluation.achieved_hourly_coverage,
        evaluation.sensor.sensor_id,
    )


def _calculate_gas_product_for_window(
    *,
    product: AirQualityIndexProduct,
    parameter_code: str,
    hour_count: int,
    evaluate_sensor: Callable[..., UsEpaGasSensorEvaluation],
    sensors: Sequence[UsEpaSensorStreamMetadata],
    raw_inputs: Sequence[RawMeasurementInput],
    window_ended_at: datetime,
    limit: int | None,
) -> list[UsEpaGasDeviceResult]:
    """Evaluate one gas window from already bounded database inputs."""
    window_started_at = window_ended_at - timedelta(hours=hour_count)
    raw_by_sensor: dict[int, list[RawMeasurementInput]] = {}
    for raw_input in raw_inputs:
        raw_by_sensor.setdefault(raw_input.sensor_id, []).append(raw_input)
    sensors_by_device: dict[int, list[UsEpaSensorStreamMetadata]] = {}
    for sensor in sensors:
        sensors_by_device.setdefault(sensor.device_id, []).append(sensor)

    results: list[UsEpaGasDeviceResult] = []
    for current_device_id, device_sensors in sensors_by_device.items():
        evaluations = tuple(
            evaluate_sensor(
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
        device = device_sensors[0]
        results.append(
            UsEpaGasDeviceResult(
                product=product,
                parameter_code=parameter_code,
                device_id=current_device_id,
                device_name=device.device_name,
                device_friendly_name=device.device_friendly_name,
                latitude=device.latitude,
                longitude=device.longitude,
                device_timezone=device.device_timezone,
                source_name=device.source_name,
                observed_at=window_ended_at,
                window_started_at=window_started_at,
                window_ended_at=window_ended_at,
                calculation=representative.calculation,
                selected_sensor=(
                    selected_evaluation.sensor if selected_evaluation else None
                ),
                selected_sensor_reason=(
                    GAS_SENSOR_SELECTION_RULE if selected_evaluation else None
                ),
                candidate_sensor_evaluations=evaluations,
                measurement_ids=(
                    selected_evaluation.selected_measurement_ids
                    if selected_evaluation
                    else ()
                ),
                valid_sample_count=(
                    selected_evaluation.selected_valid_sample_count
                    if selected_evaluation
                    else 0
                ),
                blocking_reasons=tuple(blocking_reasons),
            )
        )
    return sorted(results, key=lambda result: result.device_id)[:limit]


def _calculate_latest_gas_product(
    session: Session,
    *,
    product: AirQualityIndexProduct,
    parameter_code: str,
    hour_count: int,
    evaluate_sensor: Callable[..., UsEpaGasSensorEvaluation],
    reference_time_utc: Optional[datetime] = None,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    limit: int | None = 100,
    current_time_utc: Optional[datetime] = None,
) -> list[UsEpaGasDeviceResult]:
    now = normalize_utc(current_time_utc or datetime.now(timezone.utc))
    requested_boundary = normalize_utc(reference_time_utc) if reference_time_utc else now
    window_ended_at = min(floor_utc_hour(now), floor_utc_hour(requested_boundary))
    window_started_at = window_ended_at - timedelta(hours=hour_count)
    sensors = fetch_us_epa_candidate_sensors(
        session,
        parameter_code,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
    )
    if not sensors:
        return []
    raw_inputs = retrieve_raw_measurement_inputs(
        session,
        parameter_codes=(parameter_code,),
        start_utc=window_started_at,
        end_utc=window_ended_at,
        include_end=True,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        sensor_ids=tuple(sensor.sensor_id for sensor in sensors),
    )
    return _calculate_gas_product_for_window(
        product=product,
        parameter_code=parameter_code,
        hour_count=hour_count,
        evaluate_sensor=evaluate_sensor,
        sensors=sensors,
        raw_inputs=raw_inputs,
        window_ended_at=window_ended_at,
        limit=limit,
    )


def calculate_latest_us_epa_carbon_monoxide_aqi(
    session: Session,
    *,
    product_code: str,
    reference_time_utc: Optional[datetime] = None,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    limit: int | None = 100,
    current_time_utc: Optional[datetime] = None,
) -> list[UsEpaGasDeviceResult]:
    product = get_product(product_code)
    if product is None or product.product_code != "us_epa.co.latest":
        raise ValueError(f"Unknown U.S. EPA carbon monoxide product: {product_code}")
    return _calculate_latest_gas_product(
        session,
        product=product,
        parameter_code="co",
        hour_count=CARBON_MONOXIDE_WINDOW_HOUR_COUNT,
        evaluate_sensor=_evaluate_carbon_monoxide_sensor,
        reference_time_utc=reference_time_utc,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        limit=limit,
        current_time_utc=current_time_utc,
    )


def calculate_latest_us_epa_nitrogen_dioxide_aqi(
    session: Session,
    *,
    product_code: str,
    reference_time_utc: Optional[datetime] = None,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    limit: int | None = 100,
    current_time_utc: Optional[datetime] = None,
) -> list[UsEpaGasDeviceResult]:
    product = get_product(product_code)
    if product is None or product.product_code != "us_epa.no2.latest":
        raise ValueError(f"Unknown U.S. EPA nitrogen dioxide product: {product_code}")
    return _calculate_latest_gas_product(
        session,
        product=product,
        parameter_code="no2",
        hour_count=NITROGEN_DIOXIDE_HOUR_COUNT,
        evaluate_sensor=_evaluate_nitrogen_dioxide_sensor,
        reference_time_utc=reference_time_utc,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        limit=limit,
        current_time_utc=current_time_utc,
    )


def calculate_latest_us_epa_sulfur_dioxide_aqi(
    session: Session,
    *,
    product_code: str,
    reference_time_utc: Optional[datetime] = None,
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    limit: int | None = 100,
    current_time_utc: Optional[datetime] = None,
) -> list[UsEpaGasDeviceResult]:
    product = get_product(product_code)
    if product is None or product.product_code != "us_epa.so2.latest":
        raise ValueError(f"Unknown U.S. EPA sulfur dioxide product: {product_code}")
    return _calculate_latest_gas_product(
        session,
        product=product,
        parameter_code="so2",
        hour_count=SULFUR_DIOXIDE_WINDOW_HOUR_COUNT,
        evaluate_sensor=_evaluate_sulfur_dioxide_sensor,
        reference_time_utc=reference_time_utc,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        limit=limit,
        current_time_utc=current_time_utc,
    )


def calculate_us_epa_gas_history(
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
) -> list[UsEpaGasDeviceResult]:
    """Return at most 2,160 hourly gas evaluations from two bounded queries."""
    product = get_product(product_code)
    product_settings: dict[
        str,
        tuple[str, int, Callable[..., UsEpaGasSensorEvaluation]],
    ] = {
        "us_epa.co.latest": (
            "co",
            CARBON_MONOXIDE_WINDOW_HOUR_COUNT,
            _evaluate_carbon_monoxide_sensor,
        ),
        "us_epa.no2.latest": (
            "no2",
            NITROGEN_DIOXIDE_HOUR_COUNT,
            _evaluate_nitrogen_dioxide_sensor,
        ),
        "us_epa.so2.latest": (
            "so2",
            SULFUR_DIOXIDE_WINDOW_HOUR_COUNT,
            _evaluate_sulfur_dioxide_sensor,
        ),
    }
    settings = product_settings.get(product_code)
    if product is None or settings is None:
        raise ValueError(f"Unknown U.S. EPA gas AQI product: {product_code}")
    parameter_code, hour_count, evaluate_sensor = settings

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
        parameter_code,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=bbox,
        device_ids=device_ids,
    )
    if not sensors:
        return []
    raw_inputs = retrieve_raw_measurement_inputs(
        session,
        parameter_codes=(parameter_code,),
        start_utc=boundaries[0] - timedelta(hours=hour_count),
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
        for result in _calculate_gas_product_for_window(
            product=product,
            parameter_code=parameter_code,
            hour_count=hour_count,
            evaluate_sensor=evaluate_sensor,
            sensors=sensors,
            raw_inputs=raw_inputs[
                bisect_left(
                    raw_input_timestamps,
                    boundary - timedelta(hours=hour_count),
                ) : bisect_right(raw_input_timestamps, boundary)
            ],
            window_ended_at=boundary,
            limit=limit,
        )
    ]
    return sorted(
        results,
        key=lambda result: (result.window_ended_at, result.device_id),
    )[:limit]
