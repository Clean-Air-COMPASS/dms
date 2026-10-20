from __future__ import annotations

"""Standard-aware public API for calculated air-quality index results."""

from datetime import date, datetime, timedelta, timezone
from typing import List, Literal, Optional, Tuple, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db import get_session
from models import Device
from services.aqi_engine import (
    UsEpaDeviceAqiResult,
    calculate_latest_us_epa_aqi,
    calculate_us_epa_aqi_history,
)
from services.us_epa_completed_day_service import (
    UsEpaCompletedDayDeviceResult,
    UsEpaCompletedDaySensorEvaluation,
    calculate_latest_us_epa_completed_day_aqi,
    calculate_us_epa_completed_day_history,
)
from services.us_epa_ozone_service import (
    UsEpaOzoneDeviceResult,
    UsEpaOzoneSensorEvaluation,
    calculate_latest_us_epa_ozone_aqi,
    calculate_us_epa_ozone_history,
)
from services.us_epa_gas_service import (
    UsEpaGasDeviceResult,
    UsEpaGasSensorEvaluation,
    calculate_latest_us_epa_carbon_monoxide_aqi,
    calculate_latest_us_epa_nitrogen_dioxide_aqi,
    calculate_latest_us_epa_sulfur_dioxide_aqi,
    calculate_us_epa_gas_history,
)
from services.air_quality_index.domain import (
    AirQualityIndexProduct,
    AirQualityIndexResult,
    AirQualityIndexStandard,
    ExclusionReason,
    MethodologyReference,
    PollutantIndexResult,
)
from services.air_quality_index.us_epa_sulfur_dioxide import (
    SulfurDioxideAqiCandidate,
    SulfurDioxideWindowCalculation,
)
from services.air_quality_index.eea_european import EEA_EUROPEAN_STANDARD, NORMALIZED_UNIT
from services.air_quality_index.eea_european_service import (
    DeviceHourlyAirQualityIndex,
    SensorSelectionProvenance,
    SensorStreamEvaluationProvenance,
    calculate_eea_european_index_history,
    calculate_latest_eea_european_index,
)
from services.air_quality_index.us_epa import (
    DEFAULT_PRODUCT_CODE as US_EPA_DEFAULT_PRODUCT_CODE,
    STANDARD_CODE as US_EPA_STANDARD_CODE,
    US_EPA_STANDARD,
)
from services.air_quality_index.philippines_denr import (
    PHILIPPINES_DENR_STANDARD,
    STANDARD_CODE as PHILIPPINES_DENR_STANDARD_CODE,
)
from services.air_quality_index.philippines_denr_service import (
    PhilippineDeviceAqiResult,
    calculate_latest_philippine_aqi,
    calculate_philippine_aqi_history,
)
from services.air_quality_index.hourly_pm_completeness import (
    CompletenessApplicationProvenance,
    EligibleHourlyConcentration,
)
from services.air_quality_index.us_epa_ozone import OzoneAqiCandidate
from services.air_quality_index.us_epa_completed_day import (
    DAILY_REQUIRED_COMPLETENESS_FRACTION,
    MAXIMUM_HISTORICAL_LOCAL_DATE_COUNT,
    calculate_required_daily_hour_count,
)
from services.device_locations import InvalidBoundingBox, parse_bounding_box


router = APIRouter(prefix="/air-quality-index", tags=["air-quality-index"])


class IndexCategoryOut(BaseModel):
    code: str
    label: str
    internal_severity_rank: int
    color: str
    index_min: Optional[int] = None
    index_max: Optional[int] = None


class MethodologyReferenceOut(BaseModel):
    reference_code: str
    title: str
    document_number: Optional[str]
    publication_date: Optional[str]
    section: str
    url: str


class CompletenessApplicationProvenanceOut(BaseModel):
    provenance_code: str
    description: str


class AirQualityIndexProductOut(BaseModel):
    product_code: str
    display_name: str
    parameter_code: Optional[str]
    calculation_code: str
    aggregation_period: str
    aggregation_display_name: str
    result_scope: str
    is_parameter_default: bool
    availability_status: str
    availability_reason: Optional[str]
    product_kind: str
    history_status: str
    history_interval: str
    maximum_history_interval_count: int
    methodology_code: Optional[str]
    methodology_revision: Optional[str]
    methodology_effective_date: Optional[str]
    methodology_references: List[MethodologyReferenceOut]
    limitations: List[str]


class AirQualityIndexStandardOut(BaseModel):
    standard_code: str
    display_name: str
    methodology_version: str
    result_kind: str
    averaging_minutes: Optional[int]
    required_averaging_period: Optional[str]
    supported_parameter_codes: List[str]
    normalized_unit: str
    categories: List[IndexCategoryOut]
    products: List[AirQualityIndexProductOut]
    default_product_code: str
    is_default: bool
    methodology_code: Optional[str] = None
    methodology_revision: Optional[str] = None
    methodology_effective_date: Optional[str] = None
    methodology_references: List[MethodologyReferenceOut] = Field(
        default_factory=list
    )
    limitations: List[str] = Field(default_factory=list)


class AirQualityIndexAnalyticsSeriesRequest(BaseModel):
    standard_code: str
    product_code: str
    device_id: int = Field(gt=0)


class AirQualityIndexAnalyticsHistoryRequest(BaseModel):
    range_started_at: datetime
    range_ended_at: datetime
    series: List[AirQualityIndexAnalyticsSeriesRequest] = Field(
        min_length=1,
        max_length=6,
    )


class AirQualityIndexAnalyticsPointOut(BaseModel):
    observed_at: datetime
    interval_started_at: datetime
    interval_ended_at: datetime
    represented_local_date: Optional[date] = None
    numeric_value: Optional[float] = None
    category_code: Optional[str] = None
    category_label: Optional[str] = None
    normalized_concentration: Optional[float] = None
    preprocessed_concentration: Optional[float] = None
    normalized_unit: Optional[str] = None
    calculation_status: str
    eligibility_status: str
    coverage_status: str
    exclusion_reason: Optional[str] = None
    selected_calculation_code: Optional[str] = None
    selected_aggregation_period: Optional[str] = None
    dominant_pollutants: List[str] = Field(default_factory=list)
    available_pollutants: List[str] = Field(default_factory=list)
    missing_pollutants: List[str] = Field(default_factory=list)
    ineligible_pollutants: List[str] = Field(default_factory=list)


class AirQualityIndexAnalyticsSeriesOut(BaseModel):
    standard_code: str
    standard_display_name: str
    methodology_version: str
    product_code: str
    product_display_name: str
    parameter_code: Optional[str]
    calculation_code: str
    aggregation_period: str
    result_kind: str
    result_scope: str
    history_interval: str
    device_id: int
    device_name: str
    device_friendly_name: Optional[str]
    device_timezone: Optional[str]
    source_name: Optional[str]
    points: List[AirQualityIndexAnalyticsPointOut]


class AirQualityIndexAnalyticsHistoryOut(BaseModel):
    range_started_at: datetime
    range_ended_at: datetime
    requested_series_count: int
    returned_series_count: int
    maximum_series_count: int = 6
    maximum_hourly_interval_count: int = 366 * 24
    maximum_completed_day_interval_count: int = 366
    series: List[AirQualityIndexAnalyticsSeriesOut]


class PollutantIndexResultOut(BaseModel):
    standard_code: str
    methodology_version: str
    parameter_code: str
    normalized_concentration: Optional[float]
    preprocessed_concentration: Optional[float] = None
    normalized_unit: Optional[str]
    result_kind: str
    numeric_value: Optional[float]
    category_code: Optional[str]
    category_label: Optional[str]
    eligibility_status: str
    exclusion_reason: Optional[str]


class CoverageInformationOut(BaseModel):
    coverage_status: str
    available_pollutants: List[str]
    missing_pollutants: List[str]
    ineligible_pollutants: List[str]
    missing_or_ineligible_pollutants: List[str]
    display_qualification: str


class SensorStreamEvaluationProvenanceOut(BaseModel):
    sensor_id: int
    aggregation_period: Optional[str]
    eligibility_status: str
    exclusion_reason: Optional[str]
    expected_observation_count: Optional[int] = None
    valid_observation_count: Optional[int] = None
    required_valid_observation_count: Optional[int] = None
    required_completeness_fraction: Optional[float] = None
    achieved_completeness_fraction: Optional[float] = None
    completeness_rule_code: Optional[str] = None
    audit_flags: List[str] = Field(default_factory=list)
    measurement_ids: List[int] = Field(default_factory=list)
    duplicate_measurement_ids: List[int] = Field(default_factory=list)
    rejected_measurement_ids: List[int] = Field(default_factory=list)
    off_frequency_measurement_ids: List[int] = Field(default_factory=list)
    input_frequency_seconds: Optional[int] = None
    measurement_duration_seconds: Optional[int] = None
    source_aggregation_duration_seconds: Optional[int] = None
    target_duration_seconds: Optional[int] = None
    measurement_timestamp_semantics: Optional[str] = None


class UsEpaHourlyCompletenessOut(BaseModel):
    interval_started_at: datetime
    interval_ended_at: datetime
    hourly_concentration: Optional[float]
    normalized_unit: Optional[str]
    hourly_eligibility_status: str
    exclusion_reason: Optional[str]
    exclusion_reasons: List[str]
    audit_flags: List[str]
    input_frequency_seconds: int
    input_frequency_display: str
    measurement_duration_seconds: int
    source_aggregation_duration_seconds: int
    target_duration_seconds: int
    expected_observation_count: int
    valid_observation_count: int
    required_valid_observation_count: int
    required_completeness_fraction: Optional[float]
    achieved_completeness_fraction: float
    measurement_ids: List[int]
    duplicate_measurement_ids: List[int]
    rejected_measurement_ids: List[int]
    off_frequency_measurement_ids: List[int]
    duplicate_observation_count: int
    rejected_observation_count: int
    off_frequency_observation_count: int
    missing_position_count: int
    completeness_rule_code: str
    completeness_reference_basis: List[MethodologyReferenceOut]
    application_provenance: List[CompletenessApplicationProvenanceOut]


class UsEpaSensorStreamEvaluationOut(SensorStreamEvaluationProvenanceOut):
    hourly_concentration_provenance: Optional[str]
    hourly_timestamp_semantics: Optional[str]
    expected_frequency_seconds: Optional[int]
    input_frequency_display: Optional[str]
    measurement_duration_seconds: Optional[int]
    source_aggregation_duration_seconds: Optional[int]
    measurement_timestamp_semantics: Optional[str]
    measurement_metadata_status: Optional[str]
    metadata_is_verified_and_complete: bool
    exclusion_reasons: List[str]
    audit_flags: List[str]
    valid_hourly_slot_count: int
    valid_recent_hourly_slot_count: int
    missing_hourly_slot_count: int
    valid_sample_count: int
    duplicate_observation_count: int
    rejected_observation_count: int
    off_frequency_observation_count: int
    measurement_ids: List[int]
    completeness_reference_basis: List[MethodologyReferenceOut]
    application_provenance: List[CompletenessApplicationProvenanceOut]
    hourly_inputs: List[UsEpaHourlyCompletenessOut]


class UsEpaCompletedDaySensorEvaluationOut(BaseModel):
    sensor_id: int
    external_sensor_id: Optional[str]
    aggregation_period: Optional[str]
    metadata_is_verified_and_complete: bool
    eligibility_status: str
    blocking_reasons: List[str]
    audit_flags: List[str]
    represented_local_date: Optional[date]
    device_timezone: Optional[str]
    expected_hour_count: int
    valid_hour_count: int
    required_valid_hour_count: int
    required_completeness_fraction: Optional[float]
    achieved_completeness_fraction: float
    daily_concentration: Optional[float]
    normalized_unit: Optional[str]
    measurement_ids: List[int]
    valid_sample_count: int
    duplicate_observation_count: int
    rejected_observation_count: int
    off_frequency_observation_count: int
    daily_completeness_rule_code: Optional[str]
    reference_basis: List[MethodologyReferenceOut]
    application_provenance: List[CompletenessApplicationProvenanceOut]
    hourly_inputs: List[UsEpaHourlyCompletenessOut]


class UsEpaOzoneCandidateOut(BaseModel):
    candidate_status: str
    aggregation_period: str
    interval_started_at: datetime
    interval_ended_at: datetime
    normalized_concentration: Optional[float]
    normalized_unit: Optional[str]
    preprocessed_concentration: Optional[float]
    numeric_value: Optional[int]
    category_code: Optional[str]
    category_label: Optional[str]
    aqi_scale_status: Optional[str]
    coverage_status: str
    expected_hour_count: int
    valid_hour_count: int
    exclusion_reason: Optional[str]
    zero_substitution_used: bool
    reference_basis: List[MethodologyReferenceOut]


class UsEpaOzoneSensorEvaluationOut(BaseModel):
    sensor_id: int
    external_sensor_id: Optional[str]
    aggregation_period: Optional[str]
    input_unit_code: Optional[str]
    input_unit_symbol: Optional[str]
    hourly_concentration_provenance: Optional[str]
    hourly_timestamp_semantics: Optional[str]
    expected_frequency_seconds: Optional[int]
    measurement_duration_seconds: Optional[int]
    source_aggregation_duration_seconds: Optional[int]
    measurement_timestamp_semantics: Optional[str]
    measurement_metadata_status: Optional[str]
    metadata_is_verified_and_complete: bool
    calculation_status: str
    blocking_reasons: List[str]
    audit_flags: List[str]
    valid_hour_count: int
    valid_sample_count: int
    duplicate_observation_count: int
    rejected_observation_count: int
    off_frequency_observation_count: int
    measurement_ids: List[int]
    ozone_8_hour_candidate: UsEpaOzoneCandidateOut
    ozone_1_hour_candidate: UsEpaOzoneCandidateOut
    selected_aggregation_period: Optional[str]
    hourly_inputs: List[UsEpaHourlyCompletenessOut]


class UsEpaGasSensorEvaluationOut(BaseModel):
    sensor_id: int
    external_sensor_id: Optional[str]
    parameter_code: str
    aggregation_period: Optional[str]
    input_unit_code: Optional[str]
    input_unit_symbol: Optional[str]
    hourly_concentration_provenance: Optional[str]
    hourly_timestamp_semantics: Optional[str]
    expected_frequency_seconds: Optional[int]
    measurement_duration_seconds: Optional[int]
    source_aggregation_duration_seconds: Optional[int]
    measurement_timestamp_semantics: Optional[str]
    measurement_metadata_status: Optional[str]
    measurement_metadata_managed_by: Optional[str]
    metadata_is_verified_and_complete: bool
    calculation_status: str
    blocking_reasons: List[str]
    audit_flags: List[str]
    valid_hour_count: int
    valid_sample_count: int
    duplicate_observation_count: int
    rejected_observation_count: int
    off_frequency_observation_count: int
    measurement_ids: List[int]
    hourly_inputs: List[UsEpaHourlyCompletenessOut]


class UsEpaSo2CandidateOut(BaseModel):
    candidate_status: str
    calculation_code: str
    aggregation_period: str
    interval_started_at: datetime
    interval_ended_at: datetime
    evaluation_interval_started_at: datetime
    evaluation_interval_ended_at: datetime
    normalized_concentration: Optional[float]
    normalized_unit: str
    preprocessed_concentration: Optional[float]
    numeric_value: Optional[int]
    category_code: Optional[str]
    category_label: Optional[str]
    aqi_scale_status: Optional[str]
    coverage_status: str
    expected_hour_count: int
    valid_hour_count: int
    exclusion_reason: Optional[str]
    measurement_ids: List[int]
    reference_basis: List[MethodologyReferenceOut]


class UsEpaSo2SensorEvaluationOut(UsEpaGasSensorEvaluationOut):
    so2_1_hour_candidate: UsEpaSo2CandidateOut
    so2_24_hour_candidate: UsEpaSo2CandidateOut
    selected_aggregation_period: Optional[str]
    selected_calculation_code: Optional[str]


class UsEpaCompletedDayHistoryCandidateEvaluationOut(
    UsEpaCompletedDaySensorEvaluationOut
):
    hourly_concentration_provenance: Optional[str]
    hourly_timestamp_semantics: Optional[str]
    expected_frequency_seconds: Optional[int]
    measurement_duration_seconds: Optional[int]
    source_aggregation_duration_seconds: Optional[int]
    measurement_timestamp_semantics: Optional[str]
    measurement_metadata_status: Optional[str]
    input_unit_code: Optional[str]
    input_unit_symbol: Optional[str]


class SensorSelectionProvenanceOut(BaseModel):
    parameter_code: str
    selected_sensor_id: Optional[int]
    selected_external_sensor_id: Optional[str]
    selected_sensor_aggregation_period: Optional[str]
    input_unit_code: Optional[str]
    input_unit_symbol: Optional[str]
    hourly_concentration: Optional[float]
    measurement_ids: List[int]
    sample_count: int
    candidate_sensor_ids: List[int]
    eligible_sensor_ids: List[int]
    duplicate_eligible_sensor_ids: List[int]
    sensor_stream_evaluations: List[SensorStreamEvaluationProvenanceOut]
    selection_rule: Optional[str]
    expected_observation_count: Optional[int] = None
    valid_observation_count: Optional[int] = None
    required_valid_observation_count: Optional[int] = None
    required_completeness_fraction: Optional[float] = None
    achieved_completeness_fraction: Optional[float] = None
    completeness_rule_code: Optional[str] = None
    audit_flags: List[str] = Field(default_factory=list)
    input_frequency_seconds: Optional[int] = None
    measurement_duration_seconds: Optional[int] = None
    source_aggregation_duration_seconds: Optional[int] = None
    target_duration_seconds: Optional[int] = None
    measurement_timestamp_semantics: Optional[str] = None


class DeviceAirQualityIndexOut(BaseModel):
    standard_code: str
    methodology_version: str
    result_kind: str
    device_id: int
    device_name: str
    device_friendly_name: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    device_timezone: Optional[str]
    source_name: Optional[str]
    observed_at: datetime
    numeric_value: Optional[float]
    category_code: Optional[str]
    category_label: Optional[str]
    eligibility_status: str
    exclusion_reasons: List[str]
    dominant_pollutants: List[str]
    pollutant_results: List[PollutantIndexResultOut]
    coverage: CoverageInformationOut
    sensor_provenance: List[SensorSelectionProvenanceOut]
    parameter_code: Optional[str] = None
    product_code: Optional[str] = None
    product_display_name: Optional[str] = None
    product_kind: Optional[str] = None
    methodology_code: Optional[str] = None
    methodology_revision: Optional[str] = None
    methodology_effective_date: Optional[str] = None
    methodology_references: List[MethodologyReferenceOut] = Field(
        default_factory=list
    )
    calculation_status: Optional[str] = None
    coverage_status: Optional[str] = None
    exclusion_reason: Optional[str] = None
    aqi_scale_status: Optional[str] = None
    expected_observation_count: Optional[int] = None
    valid_observation_count: Optional[int] = None
    window_started_at: Optional[datetime] = None
    window_ended_at: Optional[datetime] = None
    normalized_concentration: Optional[float] = None
    normalized_unit: Optional[str] = None
    preprocessed_concentration: Optional[float] = None
    sensor_id: Optional[int] = None
    external_sensor_id: Optional[str] = None
    measurement_ids: List[int] = Field(default_factory=list)
    valid_sample_count: Optional[int] = None
    selected_sensor_reason: Optional[str] = None
    valid_hourly_slot_count: Optional[int] = None
    valid_recent_hourly_slot_count: Optional[int] = None
    missing_hourly_slot_count: Optional[int] = None
    latest_completed_hour_input_frequency_seconds: Optional[int] = None
    latest_completed_hour_input_frequency_display: Optional[str] = None
    latest_completed_hour_measurement_duration_seconds: Optional[int] = None
    latest_completed_hour_source_aggregation_duration_seconds: Optional[int] = None
    latest_completed_hour_target_duration_seconds: Optional[int] = None
    latest_completed_hour_expected_observation_count: Optional[int] = None
    latest_completed_hour_valid_observation_count: Optional[int] = None
    latest_completed_hour_required_observation_count: Optional[int] = None
    latest_completed_hour_required_completeness_fraction: Optional[float] = None
    latest_completed_hour_achieved_completeness_fraction: Optional[float] = None
    nowcast_window_duplicate_observation_count: Optional[int] = None
    nowcast_window_rejected_observation_count: Optional[int] = None
    nowcast_window_off_frequency_observation_count: Optional[int] = None
    latest_completed_hour_eligibility_status: Optional[str] = None
    latest_completed_hour_completeness_rule_code: Optional[str] = None
    latest_completed_hour_audit_flags: List[str] = Field(default_factory=list)
    latest_completed_hour_completeness_reference_basis: List[
        MethodologyReferenceOut
    ] = Field(default_factory=list)
    latest_completed_hour_application_provenance: List[
        CompletenessApplicationProvenanceOut
    ] = Field(default_factory=list)
    nowcast_hourly_input_eligibility: Optional[str] = None
    candidate_sensor_evaluations: List[UsEpaSensorStreamEvaluationOut] = Field(
        default_factory=list
    )
    data_qualification_status: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)
    represented_local_date: Optional[date] = None
    local_day_started_at: Optional[datetime] = None
    local_day_ended_at: Optional[datetime] = None
    utc_window_started_at: Optional[datetime] = None
    utc_window_ended_at: Optional[datetime] = None
    expected_hour_count: Optional[int] = None
    valid_hour_count: Optional[int] = None
    required_valid_hour_count: Optional[int] = None
    required_completeness_fraction: Optional[float] = None
    achieved_completeness_fraction: Optional[float] = None
    daily_concentration: Optional[float] = None
    daily_completeness_rule_code: Optional[str] = None
    blocking_reasons: List[str] = Field(default_factory=list)
    audit_flags: List[str] = Field(default_factory=list)
    reference_basis: List[MethodologyReferenceOut] = Field(default_factory=list)
    application_provenance: List[
        CompletenessApplicationProvenanceOut
    ] = Field(default_factory=list)
    completed_day_candidate_sensor_evaluations: List[
        UsEpaCompletedDaySensorEvaluationOut
    ] = Field(default_factory=list)
    selected_aggregation_period: Optional[str] = None
    selected_calculation_code: Optional[str] = None
    ozone_8_hour_candidate: Optional[UsEpaOzoneCandidateOut] = None
    ozone_1_hour_candidate: Optional[UsEpaOzoneCandidateOut] = None
    ozone_candidate_sensor_evaluations: List[
        UsEpaOzoneSensorEvaluationOut
    ] = Field(default_factory=list)
    gas_candidate_sensor_evaluations: List[
        UsEpaGasSensorEvaluationOut
    ] = Field(default_factory=list)
    so2_1_hour_candidate: Optional[UsEpaSo2CandidateOut] = None
    so2_24_hour_candidate: Optional[UsEpaSo2CandidateOut] = None
    so2_candidate_sensor_evaluations: List[
        UsEpaSo2SensorEvaluationOut
    ] = Field(default_factory=list)


class AirQualityIndexCollectionOut(BaseModel):
    standard_code: str
    methodology_version: str
    result_kind: str
    count: int
    results: List[DeviceAirQualityIndexOut]
    product_code: Optional[str] = None
    product_display_name: Optional[str] = None
    product_kind: Optional[str] = None
    methodology_code: Optional[str] = None
    methodology_revision: Optional[str] = None
    methodology_effective_date: Optional[str] = None
    methodology_references: List[MethodologyReferenceOut] = Field(
        default_factory=list
    )
    limitations: List[str] = Field(default_factory=list)


class UsEpaCompletedDayHistoryResultOut(BaseModel):
    represented_local_date: date
    local_day_started_at: Optional[datetime]
    local_day_ended_at: Optional[datetime]
    utc_window_started_at: Optional[datetime]
    utc_window_ended_at: Optional[datetime]
    expected_hour_count: Optional[int]
    valid_hour_count: int
    required_valid_hour_count: Optional[int]
    required_completeness_fraction: Optional[float]
    achieved_completeness_fraction: Optional[float]
    daily_concentration: Optional[float]
    preprocessed_concentration: Optional[float]
    normalized_unit: Optional[str]
    calculation_status: str
    coverage_status: str
    numeric_value: Optional[int]
    category_code: Optional[str]
    category_label: Optional[str]
    aqi_scale_status: Optional[str]
    selected_sensor_id: Optional[int]
    blocking_reasons: List[str]
    audit_flags: List[str]


class UsEpaCompletedDaySelectedSensorOut(BaseModel):
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
    input_unit_code: Optional[str]
    input_unit_symbol: Optional[str]


class UsEpaCompletedDayHistoryFullResultOut(
    UsEpaCompletedDayHistoryResultOut
):
    selected_sensor: Optional[UsEpaCompletedDaySelectedSensorOut]
    selected_sensor_reason: Optional[str]
    measurement_ids: List[int]
    reference_basis: List[MethodologyReferenceOut]
    application_provenance: List[CompletenessApplicationProvenanceOut]
    candidate_sensor_evaluations: List[
        UsEpaCompletedDayHistoryCandidateEvaluationOut
    ]


class UsEpaCompletedDayHistoryDeviceSeriesOut(BaseModel):
    device_id: int
    device_name: str
    device_friendly_name: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    device_timezone: Optional[str]
    source_name: Optional[str]
    results: List[UsEpaCompletedDayHistoryResultOut]


class UsEpaCompletedDayHistoryFullDeviceSeriesOut(BaseModel):
    device_id: int
    device_name: str
    device_friendly_name: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    device_timezone: Optional[str]
    source_name: Optional[str]
    results: List[UsEpaCompletedDayHistoryFullResultOut]


class UsEpaCompletedDayHistoryResponseBase(BaseModel):
    standard_code: str
    methodology_version: str
    result_kind: str
    product_code: str
    product_display_name: str
    product_kind: str
    parameter_code: str
    methodology_code: Optional[str]
    methodology_revision: Optional[str]
    methodology_effective_date: Optional[str]
    start_local_date: date
    end_local_date: date
    requested_day_count: int
    returned_device_count: int
    returned_result_count: int
    calculated_result_count: int
    unavailable_result_count: int
    maximum_supported_day_count: int


class UsEpaCompletedDayHistorySummaryOut(
    UsEpaCompletedDayHistoryResponseBase
):
    detail: Literal["summary"]
    device_series: List[UsEpaCompletedDayHistoryDeviceSeriesOut]


class UsEpaCompletedDayHistoryFullOut(
    UsEpaCompletedDayHistoryResponseBase
):
    detail: Literal["full"]
    methodology_references: List[MethodologyReferenceOut]
    limitations: List[str]
    device_series: List[UsEpaCompletedDayHistoryFullDeviceSeriesOut]


def _parse_bbox(value: Optional[str]) -> Optional[Tuple[float, float, float, float]]:
    try:
        parsed = parse_bounding_box(value)
    except InvalidBoundingBox as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return parsed.as_tuple() if parsed is not None else None


def _require_supported_standard(standard_code: str) -> None:
    if standard_code not in {
        EEA_EUROPEAN_STANDARD.code,
        US_EPA_STANDARD_CODE,
        PHILIPPINES_DENR_STANDARD_CODE,
    }:
        raise HTTPException(status_code=404, detail=f"Unknown air quality index standard: {standard_code}")


def _methodology_reference_out(
    reference: MethodologyReference,
) -> MethodologyReferenceOut:
    return MethodologyReferenceOut(
        reference_code=reference.reference_code,
        title=reference.title,
        document_number=reference.document_number,
        publication_date=reference.publication_date,
        section=reference.section,
        url=reference.url,
    )


def _application_provenance_out(
    provenance: CompletenessApplicationProvenance,
) -> CompletenessApplicationProvenanceOut:
    return CompletenessApplicationProvenanceOut(
        provenance_code=provenance.provenance_code,
        description=provenance.description,
    )


def _input_frequency_display(frequency_seconds: int) -> str:
    if frequency_seconds % 3600 == 0:
        count = frequency_seconds // 3600
        return f"{count} hour" if count == 1 else f"{count} hours"
    if frequency_seconds % 60 == 0:
        count = frequency_seconds // 60
        return f"{count} minute" if count == 1 else f"{count} minutes"
    return (
        f"{frequency_seconds} second"
        if frequency_seconds == 1
        else f"{frequency_seconds} seconds"
    )


def _hourly_completeness_out(
    hourly_input: EligibleHourlyConcentration,
) -> UsEpaHourlyCompletenessOut:
    return UsEpaHourlyCompletenessOut(
        interval_started_at=hourly_input.interval_started_at,
        interval_ended_at=hourly_input.interval_ended_at,
        hourly_concentration=hourly_input.hourly_concentration,
        normalized_unit=hourly_input.normalized_unit,
        hourly_eligibility_status=hourly_input.eligibility_status,
        exclusion_reason=(
            hourly_input.exclusion_reason.value
            if hourly_input.exclusion_reason is not None
            else None
        ),
        exclusion_reasons=[
            reason.value for reason in hourly_input.exclusion_reasons
        ],
        audit_flags=[flag.value for flag in hourly_input.audit_flags],
        input_frequency_seconds=hourly_input.input_frequency_seconds,
        input_frequency_display=_input_frequency_display(
            hourly_input.input_frequency_seconds
        ),
        measurement_duration_seconds=hourly_input.measurement_duration_seconds,
        source_aggregation_duration_seconds=(
            hourly_input.source_aggregation_duration_seconds
        ),
        target_duration_seconds=hourly_input.target_duration_seconds,
        expected_observation_count=hourly_input.expected_observation_count,
        valid_observation_count=hourly_input.valid_observation_count,
        required_valid_observation_count=(
            hourly_input.required_valid_observation_count
        ),
        required_completeness_fraction=(
            hourly_input.required_completeness_fraction
        ),
        achieved_completeness_fraction=(
            hourly_input.achieved_completeness_fraction
        ),
        measurement_ids=list(hourly_input.measurement_ids),
        duplicate_measurement_ids=list(
            hourly_input.duplicate_measurement_ids
        ),
        rejected_measurement_ids=list(hourly_input.rejected_measurement_ids),
        off_frequency_measurement_ids=list(
            hourly_input.off_frequency_measurement_ids
        ),
        duplicate_observation_count=len(
            hourly_input.duplicate_measurement_ids
        ),
        rejected_observation_count=len(hourly_input.rejected_measurement_ids),
        off_frequency_observation_count=len(
            hourly_input.off_frequency_measurement_ids
        ),
        missing_position_count=hourly_input.missing_position_count,
        completeness_rule_code=hourly_input.completeness_rule_code,
        completeness_reference_basis=[
            _methodology_reference_out(reference)
            for reference in hourly_input.completeness_reference_basis
        ],
        application_provenance=[
            _application_provenance_out(provenance)
            for provenance in hourly_input.application_provenance
        ],
    )


def _pollutant_result_out(result: PollutantIndexResult) -> PollutantIndexResultOut:
    return PollutantIndexResultOut(
        standard_code=result.standard_code,
        methodology_version=result.methodology_version,
        parameter_code=result.parameter_code,
        normalized_concentration=result.normalized_concentration,
        preprocessed_concentration=result.preprocessed_concentration,
        normalized_unit=result.normalized_unit,
        result_kind=result.result_kind.value,
        numeric_value=result.numeric_value,
        category_code=result.category_code,
        category_label=result.category_label,
        eligibility_status=result.eligibility_status.value,
        exclusion_reason=result.exclusion_reason.value if result.exclusion_reason else None,
    )


def _provenance_out(
    sensor_provenance: SensorSelectionProvenance,
) -> SensorSelectionProvenanceOut:
    return SensorSelectionProvenanceOut(
        parameter_code=sensor_provenance.parameter_code,
        selected_sensor_id=sensor_provenance.selected_sensor_id,
        selected_external_sensor_id=sensor_provenance.selected_external_sensor_id,
        selected_sensor_aggregation_period=sensor_provenance.selected_sensor_aggregation_period,
        input_unit_code=sensor_provenance.input_unit_code,
        input_unit_symbol=sensor_provenance.input_unit_symbol,
        hourly_concentration=sensor_provenance.hourly_concentration,
        measurement_ids=list(sensor_provenance.measurement_ids),
        sample_count=sensor_provenance.sample_count,
        candidate_sensor_ids=list(sensor_provenance.candidate_sensor_ids),
        eligible_sensor_ids=list(sensor_provenance.eligible_sensor_ids),
        duplicate_eligible_sensor_ids=list(sensor_provenance.duplicate_eligible_sensor_ids),
        sensor_stream_evaluations=[
            _stream_evaluation_out(stream_evaluation)
            for stream_evaluation in sensor_provenance.sensor_stream_evaluations
        ],
        selection_rule=sensor_provenance.selection_rule,
        expected_observation_count=sensor_provenance.expected_observation_count,
        valid_observation_count=sensor_provenance.valid_observation_count,
        required_valid_observation_count=(
            sensor_provenance.required_valid_observation_count
        ),
        required_completeness_fraction=(
            sensor_provenance.required_completeness_fraction
        ),
        achieved_completeness_fraction=(
            sensor_provenance.achieved_completeness_fraction
        ),
        completeness_rule_code=sensor_provenance.completeness_rule_code,
        audit_flags=[flag.value for flag in sensor_provenance.audit_flags],
        input_frequency_seconds=sensor_provenance.input_frequency_seconds,
        measurement_duration_seconds=sensor_provenance.measurement_duration_seconds,
        source_aggregation_duration_seconds=(
            sensor_provenance.source_aggregation_duration_seconds
        ),
        target_duration_seconds=sensor_provenance.target_duration_seconds,
        measurement_timestamp_semantics=(
            sensor_provenance.measurement_timestamp_semantics
        ),
    )


def _stream_evaluation_out(
    stream_evaluation: SensorStreamEvaluationProvenance,
) -> SensorStreamEvaluationProvenanceOut:
    return SensorStreamEvaluationProvenanceOut(
        sensor_id=stream_evaluation.sensor_id,
        aggregation_period=stream_evaluation.aggregation_period,
        eligibility_status=stream_evaluation.eligibility_status.value,
        exclusion_reason=(
            stream_evaluation.exclusion_reason.value
            if stream_evaluation.exclusion_reason is not None
            else None
        ),
        expected_observation_count=stream_evaluation.expected_observation_count,
        valid_observation_count=stream_evaluation.valid_observation_count,
        required_valid_observation_count=(
            stream_evaluation.required_valid_observation_count
        ),
        required_completeness_fraction=(
            stream_evaluation.required_completeness_fraction
        ),
        achieved_completeness_fraction=(
            stream_evaluation.achieved_completeness_fraction
        ),
        completeness_rule_code=stream_evaluation.completeness_rule_code,
        audit_flags=[flag.value for flag in stream_evaluation.audit_flags],
        measurement_ids=list(stream_evaluation.measurement_ids),
        duplicate_measurement_ids=list(stream_evaluation.duplicate_measurement_ids),
        rejected_measurement_ids=list(stream_evaluation.rejected_measurement_ids),
        off_frequency_measurement_ids=list(
            stream_evaluation.off_frequency_measurement_ids
        ),
        input_frequency_seconds=stream_evaluation.input_frequency_seconds,
        measurement_duration_seconds=stream_evaluation.measurement_duration_seconds,
        source_aggregation_duration_seconds=(
            stream_evaluation.source_aggregation_duration_seconds
        ),
        target_duration_seconds=stream_evaluation.target_duration_seconds,
        measurement_timestamp_semantics=(
            stream_evaluation.measurement_timestamp_semantics
        ),
    )


def _result_out(
    device_hour_result: DeviceHourlyAirQualityIndex,
) -> DeviceAirQualityIndexOut:
    air_quality_index_result: AirQualityIndexResult = device_hour_result.air_quality_index_result
    coverage = air_quality_index_result.coverage
    return DeviceAirQualityIndexOut(
        standard_code=air_quality_index_result.standard_code,
        methodology_version=air_quality_index_result.methodology_version,
        result_kind=air_quality_index_result.result_kind.value,
        device_id=device_hour_result.device_id,
        device_name=device_hour_result.device_name,
        device_friendly_name=device_hour_result.device_friendly_name,
        latitude=device_hour_result.latitude,
        longitude=device_hour_result.longitude,
        device_timezone=device_hour_result.device_timezone,
        source_name=device_hour_result.source_name,
        observed_at=device_hour_result.observed_at,
        numeric_value=air_quality_index_result.numeric_value,
        category_code=air_quality_index_result.category_code,
        category_label=air_quality_index_result.category_label,
        eligibility_status=air_quality_index_result.eligibility_status.value,
        exclusion_reasons=[reason.value for reason in air_quality_index_result.exclusion_reasons],
        dominant_pollutants=list(air_quality_index_result.dominant_pollutants),
        pollutant_results=[
            _pollutant_result_out(pollutant_result)
            for pollutant_result in air_quality_index_result.pollutant_results
        ],
        coverage=CoverageInformationOut(
            coverage_status=coverage.coverage_status.value,
            available_pollutants=list(coverage.available_pollutants),
            missing_pollutants=list(coverage.missing_pollutants),
            ineligible_pollutants=list(coverage.ineligible_pollutants),
            missing_or_ineligible_pollutants=list(coverage.missing_or_ineligible_pollutants),
            display_qualification=coverage.display_qualification.value,
        ),
        sensor_provenance=[
            _provenance_out(sensor_provenance)
            for sensor_provenance in device_hour_result.sensor_provenance
        ],
    )


def _collection(results: list[DeviceHourlyAirQualityIndex]) -> AirQualityIndexCollectionOut:
    standard = EEA_EUROPEAN_STANDARD
    return AirQualityIndexCollectionOut(
        standard_code=standard.code,
        methodology_version=standard.methodology_version,
        result_kind=standard.result_kind.value,
        count=len(results),
        results=[_result_out(result) for result in results],
    )


def _philippine_sensor_provenance_out(
    result: PhilippineDeviceAqiResult,
) -> SensorSelectionProvenanceOut:
    evaluations = result.candidate_sensor_evaluations
    selected = next(
        (
            evaluation
            for evaluation in evaluations
            if evaluation.sensor.sensor_id == result.selected_sensor_id
        ),
        None,
    )
    selected_or_first = selected or (evaluations[0] if evaluations else None)
    eligible_sensor_ids = [
        evaluation.sensor.sensor_id
        for evaluation in evaluations
        if evaluation.eligibility_status == "eligible"
    ]
    completeness_rule_code = {
        "completed_day": "philippines_denr_representative_day",
        "latest_window": (
            "philippines_denr_representative_8_hour"
            if result.product.parameter_code in {"o3", "co"}
            else "philippines_denr_representative_hour"
        ),
    }[result.product.product_kind]

    stream_evaluations: list[SensorStreamEvaluationProvenanceOut] = []
    for evaluation in evaluations:
        duplicate_ids = sorted(
            measurement_id
            for hour in evaluation.hourly_inputs
            for measurement_id in hour.duplicate_measurement_ids
        )
        rejected_ids = sorted(
            measurement_id
            for hour in evaluation.hourly_inputs
            for measurement_id in hour.rejected_measurement_ids
        )
        off_frequency_ids = sorted(
            measurement_id
            for hour in evaluation.hourly_inputs
            for measurement_id in hour.off_frequency_measurement_ids
        )
        audit_flags = [
            flag
            for flag, measurement_ids in (
                ("duplicate_observation_interval", duplicate_ids),
                ("invalid_observations_rejected", rejected_ids),
                ("off_frequency_observations", off_frequency_ids),
            )
            if measurement_ids
        ]
        sensor = evaluation.sensor
        stream_evaluations.append(
            SensorStreamEvaluationProvenanceOut(
                sensor_id=sensor.sensor_id,
                aggregation_period=sensor.aggregation_period,
                eligibility_status=evaluation.eligibility_status,
                exclusion_reason=(
                    evaluation.exclusion_reason.value
                    if evaluation.exclusion_reason is not None
                    else None
                ),
                expected_observation_count=evaluation.expected_hour_count,
                valid_observation_count=evaluation.valid_hour_count,
                required_valid_observation_count=(
                    evaluation.required_valid_hour_count
                ),
                required_completeness_fraction=(
                    evaluation.required_valid_hour_count
                    / evaluation.expected_hour_count
                    if evaluation.expected_hour_count
                    else None
                ),
                achieved_completeness_fraction=(
                    evaluation.valid_hour_count / evaluation.expected_hour_count
                    if evaluation.expected_hour_count
                    else None
                ),
                completeness_rule_code=completeness_rule_code,
                audit_flags=audit_flags,
                measurement_ids=list(evaluation.measurement_ids),
                duplicate_measurement_ids=duplicate_ids,
                rejected_measurement_ids=rejected_ids,
                off_frequency_measurement_ids=off_frequency_ids,
                input_frequency_seconds=(
                    3600
                    if sensor.aggregation_period == "1h"
                    else sensor.expected_frequency_seconds
                ),
                measurement_duration_seconds=sensor.measurement_duration_seconds,
                source_aggregation_duration_seconds=(
                    sensor.source_aggregation_duration_seconds
                ),
                target_duration_seconds=evaluation.expected_hour_count * 3600,
                measurement_timestamp_semantics=(
                    sensor.hourly_timestamp_semantics
                    if sensor.aggregation_period == "1h"
                    else sensor.measurement_timestamp_semantics
                ),
            )
        )

    selected_sensor = selected_or_first.sensor if selected_or_first else None
    expected_count = selected_or_first.expected_hour_count if selected_or_first else None
    valid_count = selected_or_first.valid_hour_count if selected_or_first else None
    required_count = (
        selected_or_first.required_valid_hour_count if selected_or_first else None
    )
    return SensorSelectionProvenanceOut(
        parameter_code=result.product.parameter_code or "",
        selected_sensor_id=result.selected_sensor_id,
        selected_external_sensor_id=(
            selected_sensor.external_sensor_id if selected_sensor else None
        ),
        selected_sensor_aggregation_period=(
            selected_sensor.aggregation_period if selected_sensor else None
        ),
        input_unit_code=selected_sensor.input_unit_code if selected_sensor else None,
        input_unit_symbol=selected_sensor.input_unit_symbol if selected_sensor else None,
        hourly_concentration=None,
        measurement_ids=list(result.measurement_ids),
        sample_count=len(result.measurement_ids),
        candidate_sensor_ids=[
            evaluation.sensor.sensor_id for evaluation in evaluations
        ],
        eligible_sensor_ids=eligible_sensor_ids,
        duplicate_eligible_sensor_ids=eligible_sensor_ids[1:],
        sensor_stream_evaluations=stream_evaluations,
        selection_rule=result.selected_sensor_reason,
        expected_observation_count=expected_count,
        valid_observation_count=valid_count,
        required_valid_observation_count=required_count,
        required_completeness_fraction=(
            required_count / expected_count
            if required_count is not None and expected_count
            else None
        ),
        achieved_completeness_fraction=(
            valid_count / expected_count
            if valid_count is not None and expected_count
            else None
        ),
        completeness_rule_code=completeness_rule_code,
        audit_flags=sorted(
            {
                flag
                for evaluation in stream_evaluations
                for flag in evaluation.audit_flags
            }
        ),
        input_frequency_seconds=(
            3600
            if selected_sensor and selected_sensor.aggregation_period == "1h"
            else selected_sensor.expected_frequency_seconds if selected_sensor else None
        ),
        measurement_duration_seconds=(
            selected_sensor.measurement_duration_seconds if selected_sensor else None
        ),
        source_aggregation_duration_seconds=(
            selected_sensor.source_aggregation_duration_seconds
            if selected_sensor
            else None
        ),
        target_duration_seconds=(expected_count * 3600 if expected_count else None),
        measurement_timestamp_semantics=(
            selected_sensor.hourly_timestamp_semantics
            if selected_sensor and selected_sensor.aggregation_period == "1h"
            else selected_sensor.measurement_timestamp_semantics
            if selected_sensor
            else None
        ),
    )


def _philippine_result_out(
    result: PhilippineDeviceAqiResult,
) -> DeviceAirQualityIndexOut:
    calculation = result.calculation
    is_eligible = calculation.is_eligible
    primary_reason = calculation.exclusion_reason
    selected_evaluation = next(
        (
            evaluation
            for evaluation in result.candidate_sensor_evaluations
            if evaluation.sensor.sensor_id == result.selected_sensor_id
        ),
        result.candidate_sensor_evaluations[0]
        if result.candidate_sensor_evaluations
        else None,
    )
    if primary_reason is None and not is_eligible and selected_evaluation is not None:
        primary_reason = selected_evaluation.exclusion_reason
    parameter_code = result.product.parameter_code or ""
    pollutant_result = PollutantIndexResultOut(
        standard_code=PHILIPPINES_DENR_STANDARD.code,
        methodology_version=PHILIPPINES_DENR_STANDARD.methodology_version,
        parameter_code=parameter_code,
        normalized_concentration=(
            float(calculation.normalized_concentration)
            if calculation.normalized_concentration is not None
            else None
        ),
        preprocessed_concentration=(
            float(calculation.preprocessed_concentration)
            if calculation.preprocessed_concentration is not None
            else None
        ),
        normalized_unit=calculation.normalized_unit,
        result_kind=PHILIPPINES_DENR_STANDARD.result_kind.value,
        numeric_value=(
            float(calculation.numeric_value)
            if calculation.numeric_value is not None
            else None
        ),
        category_code=calculation.category_code,
        category_label=calculation.category_label,
        eligibility_status="eligible" if is_eligible else "ineligible",
        exclusion_reason=primary_reason.value if primary_reason else None,
    )
    expected_hours = (
        selected_evaluation.expected_hour_count if selected_evaluation else None
    )
    valid_hours = (
        selected_evaluation.valid_hour_count if selected_evaluation else None
    )
    required_hours = (
        selected_evaluation.required_valid_hour_count
        if selected_evaluation
        else None
    )
    return DeviceAirQualityIndexOut(
        standard_code=PHILIPPINES_DENR_STANDARD.code,
        methodology_version=PHILIPPINES_DENR_STANDARD.methodology_version,
        result_kind=PHILIPPINES_DENR_STANDARD.result_kind.value,
        device_id=result.device_id,
        device_name=result.device_name,
        device_friendly_name=result.device_friendly_name,
        latitude=result.latitude,
        longitude=result.longitude,
        device_timezone=result.device_timezone,
        source_name=result.source_name,
        observed_at=result.observed_at,
        numeric_value=pollutant_result.numeric_value,
        category_code=calculation.category_code,
        category_label=calculation.category_label,
        eligibility_status="eligible" if is_eligible else "ineligible",
        exclusion_reasons=[primary_reason.value] if primary_reason else [],
        dominant_pollutants=[],
        pollutant_results=[pollutant_result],
        coverage=CoverageInformationOut(
            coverage_status=result.coverage_status,
            available_pollutants=[parameter_code] if is_eligible else [],
            missing_pollutants=(
                [parameter_code]
                if primary_reason is ExclusionReason.MISSING_MEASUREMENTS
                else []
            ),
            ineligible_pollutants=[] if is_eligible else [parameter_code],
            missing_or_ineligible_pollutants=[] if is_eligible else [parameter_code],
            display_qualification="not_evaluated",
        ),
        sensor_provenance=[_philippine_sensor_provenance_out(result)],
        parameter_code=parameter_code,
        product_code=result.product.product_code,
        product_display_name=result.product.display_name,
        product_kind=result.product.product_kind,
        methodology_code=result.product.methodology_code,
        methodology_revision=result.product.methodology_revision,
        methodology_effective_date=result.product.methodology_effective_date,
        methodology_references=[
            _methodology_reference_out(reference)
            for reference in result.product.methodology_references
        ],
        calculation_status=calculation.calculation_status.value,
        coverage_status=result.coverage_status,
        exclusion_reason=primary_reason.value if primary_reason else None,
        aqi_scale_status=(
            calculation.aqi_scale_status.value
            if calculation.aqi_scale_status is not None
            else None
        ),
        expected_observation_count=expected_hours,
        valid_observation_count=valid_hours,
        window_started_at=result.utc_window_started_at,
        window_ended_at=result.utc_window_ended_at,
        normalized_concentration=pollutant_result.normalized_concentration,
        normalized_unit=calculation.normalized_unit,
        preprocessed_concentration=pollutant_result.preprocessed_concentration,
        sensor_id=result.selected_sensor_id,
        measurement_ids=list(result.measurement_ids),
        selected_sensor_reason=result.selected_sensor_reason,
        represented_local_date=result.represented_local_date,
        local_day_started_at=(
            result.local_period_started_at
            if result.represented_local_date is not None
            else None
        ),
        local_day_ended_at=(
            result.local_period_ended_at
            if result.represented_local_date is not None
            else None
        ),
        utc_window_started_at=result.utc_window_started_at,
        utc_window_ended_at=result.utc_window_ended_at,
        expected_hour_count=expected_hours,
        valid_hour_count=valid_hours,
        required_valid_hour_count=required_hours,
        achieved_completeness_fraction=(
            valid_hours / expected_hours
            if valid_hours is not None and expected_hours
            else None
        ),
        required_completeness_fraction=(
            required_hours / expected_hours
            if required_hours is not None and expected_hours
            else None
        ),
        daily_completeness_rule_code=(
            "philippines_denr_representative_day"
            if result.product.product_kind == "completed_day"
            else None
        ),
        daily_concentration=(
            float(selected_evaluation.concentration)
            if result.represented_local_date is not None
            and selected_evaluation is not None
            and selected_evaluation.concentration is not None
            else None
        ),
        selected_aggregation_period=result.product.aggregation_period,
        selected_calculation_code=result.product.calculation_code,
        limitations=list(result.product.limitations),
    )


def _philippine_collection(
    results: list[PhilippineDeviceAqiResult],
    product_code: str,
) -> AirQualityIndexCollectionOut:
    product = next(
        product
        for product in PHILIPPINES_DENR_STANDARD.products
        if product.product_code == product_code
    )
    return AirQualityIndexCollectionOut(
        standard_code=PHILIPPINES_DENR_STANDARD.code,
        methodology_version=PHILIPPINES_DENR_STANDARD.methodology_version,
        result_kind=PHILIPPINES_DENR_STANDARD.result_kind.value,
        count=len(results),
        results=[_philippine_result_out(result) for result in results],
        product_code=product.product_code,
        product_display_name=product.display_name,
        product_kind=product.product_kind,
        methodology_code=product.methodology_code,
        methodology_revision=product.methodology_revision,
        methodology_effective_date=product.methodology_effective_date,
        methodology_references=[
            _methodology_reference_out(reference)
            for reference in product.methodology_references
        ],
        limitations=list(product.limitations),
    )


def _us_epa_result_out(
    result: UsEpaDeviceAqiResult,
) -> DeviceAirQualityIndexOut:
    calculation = result.calculation
    completeness_evaluation = result.completeness_evaluation
    latest_hourly_input = (
        completeness_evaluation.hourly_inputs[0]
        if completeness_evaluation is not None
        and completeness_evaluation.hourly_inputs
        else None
    )
    is_calculated = calculation.is_calculated
    parameter_code = result.product.parameter_code or ""
    selected_coverage_status = (
        calculation.coverage_status.value if is_calculated else "none"
    )
    available_pollutants = [parameter_code] if is_calculated else []
    missing_pollutants = (
        [parameter_code]
        if calculation.exclusion_reason is not None
        and calculation.exclusion_reason.value == "missing_measurements"
        else []
    )
    ineligible_pollutants = (
        []
        if is_calculated or missing_pollutants
        else [parameter_code]
    )
    missing_or_ineligible = list(
        dict.fromkeys(missing_pollutants + ineligible_pollutants)
    )
    pollutant_result = PollutantIndexResultOut(
        standard_code=US_EPA_STANDARD.code,
        methodology_version=US_EPA_STANDARD.methodology_version,
        parameter_code=parameter_code,
        normalized_concentration=(
            calculation.normalized_concentration if is_calculated else None
        ),
        normalized_unit=(calculation.normalized_unit if is_calculated else None),
        result_kind=US_EPA_STANDARD.result_kind.value,
        numeric_value=calculation.numeric_value,
        category_code=calculation.category_code,
        category_label=calculation.category_label,
        eligibility_status="eligible" if is_calculated else "ineligible",
        exclusion_reason=(
            calculation.exclusion_reason.value
            if calculation.exclusion_reason is not None
            else None
        ),
    )
    return DeviceAirQualityIndexOut(
        standard_code=US_EPA_STANDARD.code,
        methodology_version=US_EPA_STANDARD.methodology_version,
        result_kind=US_EPA_STANDARD.result_kind.value,
        device_id=result.device_id,
        device_name=result.device_name,
        device_friendly_name=result.device_friendly_name,
        latitude=result.latitude,
        longitude=result.longitude,
        device_timezone=result.device_timezone,
        source_name=result.source_name,
        observed_at=result.observed_at,
        numeric_value=calculation.numeric_value,
        category_code=calculation.category_code,
        category_label=calculation.category_label,
        eligibility_status="eligible" if is_calculated else "ineligible",
        exclusion_reasons=(
            [calculation.exclusion_reason.value]
            if calculation.exclusion_reason is not None
            else []
        ),
        dominant_pollutants=[parameter_code] if is_calculated else [],
        pollutant_results=[pollutant_result],
        coverage=CoverageInformationOut(
            coverage_status=selected_coverage_status,
            available_pollutants=available_pollutants,
            missing_pollutants=missing_pollutants,
            ineligible_pollutants=ineligible_pollutants,
            missing_or_ineligible_pollutants=missing_or_ineligible,
            display_qualification="not_evaluated",
        ),
        sensor_provenance=[
            SensorSelectionProvenanceOut(
                parameter_code=parameter_code,
                selected_sensor_id=(
                    result.selected_sensor.sensor_id
                    if is_calculated and result.selected_sensor is not None
                    else None
                ),
                selected_external_sensor_id=(
                    result.selected_sensor.external_sensor_id
                    if is_calculated and result.selected_sensor is not None
                    else None
                ),
                selected_sensor_aggregation_period=(
                    result.selected_sensor.aggregation_period
                    if is_calculated and result.selected_sensor is not None
                    else None
                ),
                input_unit_code=(
                    result.selected_sensor.input_unit_code
                    if is_calculated and result.selected_sensor is not None
                    else None
                ),
                input_unit_symbol=(
                    result.selected_sensor.input_unit_symbol
                    if is_calculated and result.selected_sensor is not None
                    else None
                ),
                hourly_concentration=(
                    calculation.normalized_concentration if is_calculated else None
                ),
                measurement_ids=(list(result.measurement_ids) if is_calculated else []),
                sample_count=result.valid_sample_count if is_calculated else 0,
                candidate_sensor_ids=[
                    evaluation.sensor.sensor_id
                    for evaluation in result.candidate_sensor_evaluations
                ],
                eligible_sensor_ids=[
                    evaluation.sensor.sensor_id
                    for evaluation in result.candidate_sensor_evaluations
                    if evaluation.is_input_eligible
                ],
                duplicate_eligible_sensor_ids=[
                    evaluation.sensor.sensor_id
                    for evaluation in result.candidate_sensor_evaluations
                    if evaluation.is_input_eligible
                    and (
                        result.selected_sensor is None
                        or evaluation.sensor.sensor_id
                        != result.selected_sensor.sensor_id
                    )
                ],
                sensor_stream_evaluations=[
                    SensorStreamEvaluationProvenanceOut(
                        sensor_id=evaluation.sensor.sensor_id,
                        aggregation_period=evaluation.sensor.aggregation_period,
                        eligibility_status=(
                            "eligible"
                            if evaluation.is_input_eligible
                            else "ineligible"
                        ),
                        exclusion_reason=(
                            evaluation.exclusion_reason.value
                            if evaluation.exclusion_reason is not None
                            else None
                        ),
                    )
                    for evaluation in result.candidate_sensor_evaluations
                ],
                selection_rule=(result.selected_sensor_reason if is_calculated else None),
            )
        ],
        parameter_code=parameter_code,
        product_code=result.product.product_code,
        product_display_name=result.product.display_name,
        product_kind=result.product.product_kind,
        methodology_code=result.product.methodology_code,
        methodology_revision=result.product.methodology_revision,
        methodology_effective_date=(
            result.product.methodology_effective_date
        ),
        methodology_references=[
            _methodology_reference_out(reference)
            for reference in result.product.methodology_references
        ],
        calculation_status=calculation.calculation_status.value,
        coverage_status=selected_coverage_status,
        exclusion_reason=(
            calculation.exclusion_reason.value
            if calculation.exclusion_reason is not None
            else None
        ),
        aqi_scale_status=(
            calculation.aqi_scale_status.value
            if calculation.aqi_scale_status is not None
            else None
        ),
        expected_observation_count=(
            calculation.expected_observation_count if is_calculated else None
        ),
        valid_observation_count=(
            calculation.valid_observation_count if is_calculated else None
        ),
        window_started_at=(result.window_started_at if is_calculated else None),
        window_ended_at=(result.window_ended_at if is_calculated else None),
        normalized_concentration=(
            calculation.normalized_concentration if is_calculated else None
        ),
        normalized_unit=(calculation.normalized_unit if is_calculated else None),
        preprocessed_concentration=(
            calculation.preprocessed_concentration if is_calculated else None
        ),
        sensor_id=(
            result.selected_sensor.sensor_id
            if is_calculated and result.selected_sensor is not None
            else None
        ),
        external_sensor_id=(
            result.selected_sensor.external_sensor_id
            if is_calculated and result.selected_sensor is not None
            else None
        ),
        measurement_ids=(list(result.measurement_ids) if is_calculated else []),
        valid_sample_count=result.valid_sample_count if is_calculated else 0,
        selected_sensor_reason=(
            result.selected_sensor_reason if is_calculated else None
        ),
        valid_hourly_slot_count=(
            result.valid_hourly_slot_count if is_calculated else None
        ),
        valid_recent_hourly_slot_count=(
            result.valid_recent_hourly_slot_count if is_calculated else None
        ),
        missing_hourly_slot_count=(
            result.missing_hourly_slot_count if is_calculated else None
        ),
        latest_completed_hour_input_frequency_seconds=(
            latest_hourly_input.input_frequency_seconds
            if latest_hourly_input is not None
            else None
        ),
        latest_completed_hour_input_frequency_display=(
            _input_frequency_display(latest_hourly_input.input_frequency_seconds)
            if latest_hourly_input is not None
            else None
        ),
        latest_completed_hour_measurement_duration_seconds=(
            latest_hourly_input.measurement_duration_seconds
            if latest_hourly_input is not None
            else None
        ),
        latest_completed_hour_source_aggregation_duration_seconds=(
            latest_hourly_input.source_aggregation_duration_seconds
            if latest_hourly_input is not None
            else None
        ),
        latest_completed_hour_target_duration_seconds=(
            latest_hourly_input.target_duration_seconds
            if latest_hourly_input is not None
            else None
        ),
        latest_completed_hour_expected_observation_count=(
            latest_hourly_input.expected_observation_count
            if latest_hourly_input is not None
            else None
        ),
        latest_completed_hour_valid_observation_count=(
            latest_hourly_input.valid_observation_count
            if latest_hourly_input is not None
            else None
        ),
        latest_completed_hour_required_observation_count=(
            latest_hourly_input.required_valid_observation_count
            if latest_hourly_input is not None
            else None
        ),
        latest_completed_hour_required_completeness_fraction=(
            latest_hourly_input.required_completeness_fraction
            if latest_hourly_input is not None
            else None
        ),
        latest_completed_hour_achieved_completeness_fraction=(
            latest_hourly_input.achieved_completeness_fraction
            if latest_hourly_input is not None
            else None
        ),
        nowcast_window_duplicate_observation_count=(
            completeness_evaluation.duplicate_observation_count
            if completeness_evaluation is not None
            else None
        ),
        nowcast_window_rejected_observation_count=(
            completeness_evaluation.rejected_observation_count
            if completeness_evaluation is not None
            else None
        ),
        nowcast_window_off_frequency_observation_count=(
            completeness_evaluation.off_frequency_observation_count
            if completeness_evaluation is not None
            else None
        ),
        latest_completed_hour_eligibility_status=(
            latest_hourly_input.eligibility_status
            if latest_hourly_input is not None
            else None
        ),
        latest_completed_hour_completeness_rule_code=(
            latest_hourly_input.completeness_rule_code
            if latest_hourly_input is not None
            else None
        ),
        latest_completed_hour_audit_flags=(
            [flag.value for flag in latest_hourly_input.audit_flags]
            if latest_hourly_input is not None
            else []
        ),
        latest_completed_hour_completeness_reference_basis=(
            [
                _methodology_reference_out(reference)
                for reference in (
                    latest_hourly_input.completeness_reference_basis
                )
            ]
            if latest_hourly_input is not None
            else []
        ),
        latest_completed_hour_application_provenance=(
            [
                _application_provenance_out(provenance)
                for provenance in latest_hourly_input.application_provenance
            ]
            if latest_hourly_input is not None
            else []
        ),
        nowcast_hourly_input_eligibility=(
            result.nowcast_hourly_input_eligibility.value
        ),
        candidate_sensor_evaluations=[
            UsEpaSensorStreamEvaluationOut(
                sensor_id=evaluation.sensor.sensor_id,
                aggregation_period=evaluation.sensor.aggregation_period,
                eligibility_status=(
                    "eligible" if evaluation.is_input_eligible else "ineligible"
                ),
                exclusion_reason=(
                    evaluation.exclusion_reason.value
                    if evaluation.exclusion_reason is not None
                    else None
                ),
                hourly_concentration_provenance=(
                    evaluation.sensor.hourly_concentration_provenance
                ),
                hourly_timestamp_semantics=(
                    evaluation.sensor.hourly_timestamp_semantics
                ),
                expected_frequency_seconds=(
                    evaluation.sensor.expected_frequency_seconds
                    if evaluation.sensor.expected_frequency_seconds is not None
                    else (
                        evaluation.hourly_inputs[0].input_frequency_seconds
                        if evaluation.hourly_inputs
                        else None
                    )
                ),
                input_frequency_display=(
                    _input_frequency_display(
                        evaluation.sensor.expected_frequency_seconds
                        if evaluation.sensor.expected_frequency_seconds
                        is not None
                        else evaluation.hourly_inputs[0].input_frequency_seconds
                    )
                    if evaluation.sensor.expected_frequency_seconds is not None
                    or evaluation.hourly_inputs
                    else None
                ),
                measurement_duration_seconds=(
                    evaluation.sensor.measurement_duration_seconds
                    if evaluation.sensor.measurement_duration_seconds is not None
                    else (
                        evaluation.hourly_inputs[0].measurement_duration_seconds
                        if evaluation.hourly_inputs
                        else None
                    )
                ),
                source_aggregation_duration_seconds=(
                    evaluation.sensor.source_aggregation_duration_seconds
                    if evaluation.sensor.source_aggregation_duration_seconds
                    is not None
                    else (
                        evaluation.hourly_inputs[
                            0
                        ].source_aggregation_duration_seconds
                        if evaluation.hourly_inputs
                        else None
                    )
                ),
                measurement_timestamp_semantics=(
                    evaluation.sensor.measurement_timestamp_semantics
                ),
                measurement_metadata_status=(
                    evaluation.sensor.measurement_metadata_status
                ),
                metadata_is_verified_and_complete=(
                    evaluation.metadata_is_verified_and_complete
                ),
                exclusion_reasons=[
                    reason.value for reason in evaluation.exclusion_reasons
                ],
                audit_flags=[flag.value for flag in evaluation.audit_flags],
                valid_hourly_slot_count=evaluation.valid_hourly_slot_count,
                valid_recent_hourly_slot_count=(
                    evaluation.valid_recent_hourly_slot_count
                ),
                missing_hourly_slot_count=evaluation.missing_hourly_slot_count,
                valid_sample_count=evaluation.valid_sample_count,
                duplicate_observation_count=(
                    evaluation.duplicate_observation_count
                ),
                rejected_observation_count=(
                    evaluation.rejected_observation_count
                ),
                off_frequency_observation_count=(
                    evaluation.off_frequency_observation_count
                ),
                measurement_ids=list(evaluation.measurement_ids),
                completeness_reference_basis=(
                    [
                        _methodology_reference_out(reference)
                        for reference in evaluation.hourly_inputs[
                            0
                        ].completeness_reference_basis
                    ]
                    if evaluation.hourly_inputs
                    else []
                ),
                application_provenance=(
                    [
                        _application_provenance_out(provenance)
                        for provenance in evaluation.hourly_inputs[
                            0
                        ].application_provenance
                    ]
                    if evaluation.hourly_inputs
                    else []
                ),
                hourly_inputs=[
                    _hourly_completeness_out(hourly_input)
                    for hourly_input in evaluation.hourly_inputs
                ],
            )
            for evaluation in result.candidate_sensor_evaluations
        ],
        data_qualification_status=result.data_qualification_status.value,
        limitations=list(result.product.limitations),
        selected_aggregation_period=(
            result.product.aggregation_period if is_calculated else None
        ),
        selected_calculation_code=(
            result.product.calculation_code if is_calculated else None
        ),
    )


def _completed_day_candidate_out(
    evaluation: UsEpaCompletedDaySensorEvaluation,
) -> UsEpaCompletedDaySensorEvaluationOut:
    window = evaluation.local_day_resolution.window
    daily = evaluation.completed_day_calculation
    completeness = daily.completeness if daily is not None else None
    return UsEpaCompletedDaySensorEvaluationOut(
        sensor_id=evaluation.sensor.sensor_id,
        external_sensor_id=evaluation.sensor.external_sensor_id,
        aggregation_period=evaluation.sensor.aggregation_period,
        metadata_is_verified_and_complete=(
            evaluation.metadata_is_verified_and_complete
        ),
        eligibility_status=(
            "eligible" if evaluation.is_daily_eligible else "ineligible"
        ),
        blocking_reasons=[
            reason.value for reason in evaluation.blocking_reasons
        ],
        audit_flags=[flag.value for flag in evaluation.audit_flags],
        represented_local_date=(
            window.represented_local_date if window is not None else None
        ),
        device_timezone=evaluation.sensor.device_timezone,
        expected_hour_count=evaluation.expected_hour_count,
        valid_hour_count=evaluation.valid_hour_count,
        required_valid_hour_count=(
            completeness.required_valid_hour_count
            if completeness is not None
            else 0
        ),
        required_completeness_fraction=(
            completeness.required_completeness_fraction
            if completeness is not None
            else None
        ),
        achieved_completeness_fraction=(
            evaluation.achieved_completeness_fraction
        ),
        daily_concentration=(
            daily.daily_concentration if daily is not None else None
        ),
        normalized_unit=(daily.normalized_unit if daily is not None else None),
        measurement_ids=list(evaluation.measurement_ids),
        valid_sample_count=evaluation.valid_sample_count,
        duplicate_observation_count=evaluation.duplicate_observation_count,
        rejected_observation_count=evaluation.rejected_observation_count,
        off_frequency_observation_count=(
            evaluation.off_frequency_observation_count
        ),
        daily_completeness_rule_code=(
            completeness.completeness_rule_code
            if completeness is not None
            else None
        ),
        reference_basis=(
            [
                _methodology_reference_out(reference)
                for reference in daily.reference_basis
            ]
            if daily is not None
            else []
        ),
        application_provenance=(
            [
                _application_provenance_out(provenance)
                for provenance in daily.application_provenance
            ]
            if daily is not None
            else []
        ),
        hourly_inputs=[
            _hourly_completeness_out(hourly_input)
            for hourly_input in evaluation.hourly_inputs
        ],
    )


def _completed_day_history_candidate_out(
    evaluation: UsEpaCompletedDaySensorEvaluation,
) -> UsEpaCompletedDayHistoryCandidateEvaluationOut:
    base_candidate = _completed_day_candidate_out(evaluation)
    return UsEpaCompletedDayHistoryCandidateEvaluationOut(
        **base_candidate.model_dump(),
        hourly_concentration_provenance=(
            evaluation.sensor.hourly_concentration_provenance
        ),
        hourly_timestamp_semantics=evaluation.sensor.hourly_timestamp_semantics,
        expected_frequency_seconds=evaluation.sensor.expected_frequency_seconds,
        measurement_duration_seconds=(
            evaluation.sensor.measurement_duration_seconds
        ),
        source_aggregation_duration_seconds=(
            evaluation.sensor.source_aggregation_duration_seconds
        ),
        measurement_timestamp_semantics=(
            evaluation.sensor.measurement_timestamp_semantics
        ),
        measurement_metadata_status=evaluation.sensor.measurement_metadata_status,
        input_unit_code=evaluation.sensor.input_unit_code,
        input_unit_symbol=evaluation.sensor.input_unit_symbol,
    )


def _us_epa_completed_day_result_out(
    result: UsEpaCompletedDayDeviceResult,
) -> DeviceAirQualityIndexOut:
    calculation = result.calculation
    is_calculated = calculation is not None and calculation.is_calculated
    parameter_code = result.product.parameter_code or ""
    representative_evaluation = next(
        (
            evaluation
            for evaluation in result.candidate_sensor_evaluations
            if result.selected_sensor is not None
            and evaluation.sensor.sensor_id == result.selected_sensor.sensor_id
        ),
        None,
    )
    if representative_evaluation is None and result.candidate_sensor_evaluations:
        representative_evaluation = sorted(
            result.candidate_sensor_evaluations,
            key=lambda evaluation: (
                -int(evaluation.metadata_is_verified_and_complete),
                -evaluation.valid_hour_count,
                -evaluation.achieved_completeness_fraction,
                evaluation.sensor.sensor_id,
            ),
        )[0]
    representative_daily = (
        representative_evaluation.completed_day_calculation
        if representative_evaluation is not None
        else None
    )
    completeness = (
        representative_daily.completeness
        if representative_daily is not None
        else None
    )
    window = result.local_day_window
    primary_reason = next(
        (
            reason
            for reason in result.blocking_reasons
            if reason.value != "no_eligible_sensor_stream"
        ),
        result.blocking_reasons[0] if result.blocking_reasons else None,
    )
    diagnostic_coverage_status = (
        calculation.coverage_status.value
        if calculation is not None
        else (
            "partial"
            if completeness is not None and completeness.valid_hour_count > 0
            else "none"
        )
    )
    selected_coverage_status = (
        diagnostic_coverage_status if is_calculated else "none"
    )
    pollutant_result = PollutantIndexResultOut(
        standard_code=US_EPA_STANDARD.code,
        methodology_version=US_EPA_STANDARD.methodology_version,
        parameter_code=parameter_code,
        normalized_concentration=(
            calculation.normalized_concentration if is_calculated else None
        ),
        normalized_unit=(calculation.normalized_unit if is_calculated else None),
        result_kind=US_EPA_STANDARD.result_kind.value,
        numeric_value=(calculation.numeric_value if calculation else None),
        category_code=(calculation.category_code if calculation else None),
        category_label=(calculation.category_label if calculation else None),
        eligibility_status="eligible" if is_calculated else "ineligible",
        exclusion_reason=(primary_reason.value if primary_reason else None),
    )
    return DeviceAirQualityIndexOut(
        standard_code=US_EPA_STANDARD.code,
        methodology_version=US_EPA_STANDARD.methodology_version,
        result_kind=US_EPA_STANDARD.result_kind.value,
        device_id=result.device_id,
        device_name=result.device_name,
        device_friendly_name=result.device_friendly_name,
        latitude=result.latitude,
        longitude=result.longitude,
        device_timezone=result.device_timezone,
        source_name=result.source_name,
        observed_at=result.observed_at,
        numeric_value=(calculation.numeric_value if calculation else None),
        category_code=(calculation.category_code if calculation else None),
        category_label=(calculation.category_label if calculation else None),
        eligibility_status="eligible" if is_calculated else "ineligible",
        exclusion_reasons=[
            reason.value for reason in result.blocking_reasons
        ],
        dominant_pollutants=[parameter_code] if is_calculated else [],
        pollutant_results=[pollutant_result],
        coverage=CoverageInformationOut(
            coverage_status=selected_coverage_status,
            available_pollutants=[parameter_code] if is_calculated else [],
            missing_pollutants=[],
            ineligible_pollutants=[] if is_calculated else [parameter_code],
            missing_or_ineligible_pollutants=(
                [] if is_calculated else [parameter_code]
            ),
            display_qualification="not_evaluated",
        ),
        # The legacy generic provenance model contains an explicitly hourly
        # concentration field, so daily provenance is exposed in the dedicated
        # completed-day candidate collection instead.
        sensor_provenance=[],
        parameter_code=parameter_code,
        product_code=result.product.product_code,
        product_display_name=result.product.display_name,
        product_kind=result.product.product_kind,
        methodology_code=result.product.methodology_code,
        methodology_revision=result.product.methodology_revision,
        methodology_effective_date=result.product.methodology_effective_date,
        methodology_references=[
            _methodology_reference_out(reference)
            for reference in result.product.methodology_references
        ],
        calculation_status="calculated" if is_calculated else "unavailable",
        coverage_status=selected_coverage_status,
        exclusion_reason=(primary_reason.value if primary_reason else None),
        aqi_scale_status=(
            calculation.aqi_scale_status.value
            if calculation is not None and calculation.aqi_scale_status is not None
            else None
        ),
        expected_observation_count=(
            completeness.expected_hour_count
            if is_calculated and completeness is not None
            else None
        ),
        valid_observation_count=(
            completeness.valid_hour_count
            if is_calculated and completeness is not None
            else None
        ),
        window_started_at=(
            window.utc_window_started_at
            if is_calculated and window is not None
            else None
        ),
        window_ended_at=(
            window.utc_window_ended_at
            if is_calculated and window is not None
            else None
        ),
        normalized_concentration=(
            calculation.normalized_concentration if is_calculated else None
        ),
        normalized_unit=(calculation.normalized_unit if is_calculated else None),
        preprocessed_concentration=(
            calculation.preprocessed_concentration if is_calculated else None
        ),
        sensor_id=(
            result.selected_sensor.sensor_id
            if is_calculated and result.selected_sensor
            else None
        ),
        external_sensor_id=(
            result.selected_sensor.external_sensor_id
            if is_calculated and result.selected_sensor
            else None
        ),
        measurement_ids=(list(result.measurement_ids) if is_calculated else []),
        valid_sample_count=(
            representative_evaluation.valid_sample_count
            if is_calculated and representative_evaluation is not None
            else 0
        ),
        selected_sensor_reason=(
            result.selected_sensor_reason if is_calculated else None
        ),
        valid_hourly_slot_count=(
            completeness.valid_hour_count
            if is_calculated and completeness is not None
            else None
        ),
        missing_hourly_slot_count=(
            completeness.expected_hour_count - completeness.valid_hour_count
            if is_calculated and completeness is not None
            else None
        ),
        data_qualification_status=result.data_qualification_status.value,
        limitations=list(result.product.limitations),
        represented_local_date=(
            window.represented_local_date if window is not None else None
        ),
        local_day_started_at=(
            window.local_day_started_at if window is not None else None
        ),
        local_day_ended_at=(
            window.local_day_ended_at if window is not None else None
        ),
        utc_window_started_at=(
            window.utc_window_started_at if window is not None else None
        ),
        utc_window_ended_at=(
            window.utc_window_ended_at if window is not None else None
        ),
        expected_hour_count=(
            window.expected_hour_count if window is not None else None
        ),
        valid_hour_count=(
            completeness.valid_hour_count if completeness is not None else 0
        ),
        required_valid_hour_count=(
            completeness.required_valid_hour_count
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
        daily_concentration=(
            representative_daily.daily_concentration
            if representative_daily is not None
            else None
        ),
        daily_completeness_rule_code=(
            completeness.completeness_rule_code
            if completeness is not None
            else None
        ),
        blocking_reasons=[reason.value for reason in result.blocking_reasons],
        audit_flags=[flag.value for flag in result.audit_flags],
        reference_basis=(
            [
                _methodology_reference_out(reference)
                for reference in representative_daily.reference_basis
            ]
            if representative_daily is not None
            else []
        ),
        application_provenance=[
            _application_provenance_out(provenance)
            for provenance in result.application_provenance
        ],
        completed_day_candidate_sensor_evaluations=[
            _completed_day_candidate_out(evaluation)
            for evaluation in result.candidate_sensor_evaluations
        ],
        selected_aggregation_period=(
            result.product.aggregation_period if is_calculated else None
        ),
        selected_calculation_code=(
            result.product.calculation_code if is_calculated else None
        ),
    )


def _representative_completed_day_evaluation(
    result: UsEpaCompletedDayDeviceResult,
) -> Optional[UsEpaCompletedDaySensorEvaluation]:
    if result.selected_sensor is not None:
        return next(
            (
                evaluation
                for evaluation in result.candidate_sensor_evaluations
                if evaluation.sensor.sensor_id == result.selected_sensor.sensor_id
            ),
            None,
        )
    if not result.candidate_sensor_evaluations:
        return None
    return sorted(
        result.candidate_sensor_evaluations,
        key=lambda evaluation: (
            -int(evaluation.metadata_is_verified_and_complete),
            -int(evaluation.is_daily_eligible),
            -evaluation.valid_hour_count,
            -evaluation.achieved_completeness_fraction,
            evaluation.sensor.sensor_id,
        ),
    )[0]


def _selected_completed_day_sensor_out(
    result: UsEpaCompletedDayDeviceResult,
) -> Optional[UsEpaCompletedDaySelectedSensorOut]:
    sensor = result.selected_sensor
    if sensor is None:
        return None
    return UsEpaCompletedDaySelectedSensorOut(
        sensor_id=sensor.sensor_id,
        external_sensor_id=sensor.external_sensor_id,
        aggregation_period=sensor.aggregation_period,
        hourly_concentration_provenance=sensor.hourly_concentration_provenance,
        hourly_timestamp_semantics=sensor.hourly_timestamp_semantics,
        expected_frequency_seconds=sensor.expected_frequency_seconds,
        measurement_duration_seconds=sensor.measurement_duration_seconds,
        source_aggregation_duration_seconds=(
            sensor.source_aggregation_duration_seconds
        ),
        measurement_timestamp_semantics=sensor.measurement_timestamp_semantics,
        measurement_metadata_status=sensor.measurement_metadata_status,
        input_unit_code=sensor.input_unit_code,
        input_unit_symbol=sensor.input_unit_symbol,
    )


def _us_epa_completed_day_history_result_out(
    result: UsEpaCompletedDayDeviceResult,
    *,
    detail: Literal["summary", "full"],
) -> Union[
    UsEpaCompletedDayHistoryResultOut,
    UsEpaCompletedDayHistoryFullResultOut,
]:
    represented_local_date = result.represented_local_date
    if represented_local_date is None:
        raise RuntimeError("Historical result has no represented local date")
    representative = _representative_completed_day_evaluation(result)
    representative_daily = (
        representative.completed_day_calculation
        if representative is not None
        else None
    )
    completeness = (
        representative_daily.completeness
        if representative_daily is not None
        else None
    )
    window = result.local_day_window
    expected_hour_count = (
        window.expected_hour_count if window is not None else None
    )
    valid_hour_count = (
        representative.valid_hour_count if representative is not None else 0
    )
    required_valid_hour_count = (
        completeness.required_valid_hour_count
        if completeness is not None
        else (
            calculate_required_daily_hour_count(expected_hour_count)
            if expected_hour_count is not None
            else None
        )
    )
    required_completeness_fraction = (
        completeness.required_completeness_fraction
        if completeness is not None
        else (
            float(DAILY_REQUIRED_COMPLETENESS_FRACTION)
            if expected_hour_count is not None
            else None
        )
    )
    achieved_completeness_fraction = (
        completeness.achieved_completeness_fraction
        if completeness is not None
        else (
            valid_hour_count / expected_hour_count
            if expected_hour_count
            else None
        )
    )
    calculation = result.calculation
    is_calculated = calculation is not None and calculation.is_calculated
    coverage_status = (
        calculation.coverage_status.value
        if calculation is not None
        else ("partial" if valid_hour_count else "none")
    )
    summary = UsEpaCompletedDayHistoryResultOut(
        represented_local_date=represented_local_date,
        local_day_started_at=(
            window.local_day_started_at if window is not None else None
        ),
        local_day_ended_at=(
            window.local_day_ended_at if window is not None else None
        ),
        utc_window_started_at=(
            window.utc_window_started_at if window is not None else None
        ),
        utc_window_ended_at=(
            window.utc_window_ended_at if window is not None else None
        ),
        expected_hour_count=expected_hour_count,
        valid_hour_count=valid_hour_count,
        required_valid_hour_count=required_valid_hour_count,
        required_completeness_fraction=required_completeness_fraction,
        achieved_completeness_fraction=achieved_completeness_fraction,
        daily_concentration=(
            representative_daily.daily_concentration
            if representative_daily is not None
            else None
        ),
        preprocessed_concentration=(
            calculation.preprocessed_concentration
            if calculation is not None
            else None
        ),
        normalized_unit=(
            calculation.normalized_unit
            if calculation is not None
            else (
                representative_daily.normalized_unit
                if representative_daily is not None
                else None
            )
        ),
        calculation_status="calculated" if is_calculated else "unavailable",
        coverage_status=coverage_status,
        numeric_value=(calculation.numeric_value if calculation else None),
        category_code=(calculation.category_code if calculation else None),
        category_label=(calculation.category_label if calculation else None),
        aqi_scale_status=(
            calculation.aqi_scale_status.value
            if calculation is not None
            and calculation.aqi_scale_status is not None
            else None
        ),
        selected_sensor_id=(
            result.selected_sensor.sensor_id
            if result.selected_sensor is not None
            else None
        ),
        blocking_reasons=[reason.value for reason in result.blocking_reasons],
        audit_flags=[flag.value for flag in result.audit_flags],
    )
    if detail == "summary":
        return summary
    return UsEpaCompletedDayHistoryFullResultOut(
        **summary.model_dump(),
        selected_sensor=_selected_completed_day_sensor_out(result),
        selected_sensor_reason=result.selected_sensor_reason,
        measurement_ids=list(result.measurement_ids),
        reference_basis=(
            [
                _methodology_reference_out(reference)
                for reference in representative_daily.reference_basis
            ]
            if representative_daily is not None
            else []
        ),
        application_provenance=[
            _application_provenance_out(provenance)
            for provenance in result.application_provenance
        ],
        candidate_sensor_evaluations=[
            _completed_day_history_candidate_out(evaluation)
            for evaluation in result.candidate_sensor_evaluations
        ],
    )


def _us_epa_completed_day_history_response(
    results: list[UsEpaCompletedDayDeviceResult],
    *,
    product: AirQualityIndexProduct,
    start_local_date: date,
    end_local_date: date,
    detail: Literal["summary", "full"],
) -> Union[
    UsEpaCompletedDayHistorySummaryOut,
    UsEpaCompletedDayHistoryFullOut,
]:
    results_by_device: dict[int, list[UsEpaCompletedDayDeviceResult]] = {}
    for result in results:
        results_by_device.setdefault(result.device_id, []).append(result)
    for device_results in results_by_device.values():
        device_results.sort(
            key=lambda item: item.represented_local_date or date.min
        )

    requested_day_count = (end_local_date - start_local_date).days + 1
    returned_result_count = len(results)
    calculated_result_count = sum(
        1
        for result in results
        if result.calculation is not None and result.calculation.is_calculated
    )
    response_fields = dict(
        standard_code=US_EPA_STANDARD.code,
        methodology_version=US_EPA_STANDARD.methodology_version,
        result_kind=US_EPA_STANDARD.result_kind.value,
        product_code=product.product_code,
        product_display_name=product.display_name,
        product_kind=product.product_kind,
        parameter_code=product.parameter_code or "",
        methodology_code=product.methodology_code,
        methodology_revision=product.methodology_revision,
        methodology_effective_date=product.methodology_effective_date,
        start_local_date=start_local_date,
        end_local_date=end_local_date,
        requested_day_count=requested_day_count,
        returned_device_count=len(results_by_device),
        returned_result_count=returned_result_count,
        calculated_result_count=calculated_result_count,
        unavailable_result_count=(
            returned_result_count - calculated_result_count
        ),
        maximum_supported_day_count=MAXIMUM_HISTORICAL_LOCAL_DATE_COUNT,
    )
    if detail == "summary":
        summary_series = []
        for current_device_id in sorted(results_by_device):
            device_results = results_by_device[current_device_id]
            device = device_results[0]
            summary_series.append(
                UsEpaCompletedDayHistoryDeviceSeriesOut(
                    device_id=device.device_id,
                    device_name=device.device_name,
                    device_friendly_name=device.device_friendly_name,
                    latitude=device.latitude,
                    longitude=device.longitude,
                    device_timezone=device.device_timezone,
                    source_name=device.source_name,
                    results=[
                        _us_epa_completed_day_history_result_out(
                            result,
                            detail="summary",
                        )
                        for result in device_results
                    ],
                )
            )
        return UsEpaCompletedDayHistorySummaryOut(
            **response_fields,
            detail="summary",
            device_series=summary_series,
        )

    full_series = []
    for current_device_id in sorted(results_by_device):
        device_results = results_by_device[current_device_id]
        device = device_results[0]
        full_series.append(
            UsEpaCompletedDayHistoryFullDeviceSeriesOut(
                device_id=device.device_id,
                device_name=device.device_name,
                device_friendly_name=device.device_friendly_name,
                latitude=device.latitude,
                longitude=device.longitude,
                device_timezone=device.device_timezone,
                source_name=device.source_name,
                results=[
                    _us_epa_completed_day_history_result_out(
                        result,
                        detail="full",
                    )
                    for result in device_results
                ],
            )
        )
    return UsEpaCompletedDayHistoryFullOut(
        **response_fields,
        detail="full",
        methodology_references=[
            _methodology_reference_out(reference)
            for reference in product.methodology_references
        ],
        limitations=list(product.limitations),
        device_series=full_series,
    )


def _ozone_candidate_out(candidate: OzoneAqiCandidate) -> UsEpaOzoneCandidateOut:
    return UsEpaOzoneCandidateOut(
        candidate_status=candidate.candidate_status.value,
        aggregation_period=candidate.aggregation_period,
        interval_started_at=candidate.interval_started_at,
        interval_ended_at=candidate.interval_ended_at,
        normalized_concentration=candidate.normalized_concentration,
        normalized_unit=candidate.normalized_unit,
        preprocessed_concentration=candidate.preprocessed_concentration,
        numeric_value=candidate.numeric_value,
        category_code=candidate.category_code,
        category_label=candidate.category_label,
        aqi_scale_status=(
            candidate.aqi_scale_status.value if candidate.aqi_scale_status else None
        ),
        coverage_status=candidate.coverage_status.value,
        expected_hour_count=candidate.expected_hour_count,
        valid_hour_count=candidate.valid_hour_count,
        exclusion_reason=(candidate.exclusion_reason.value if candidate.exclusion_reason else None),
        zero_substitution_used=candidate.zero_substitution_used,
        reference_basis=[
            _methodology_reference_out(reference)
            for reference in candidate.reference_basis
        ],
    )


def _ozone_sensor_evaluation_out(
    evaluation: UsEpaOzoneSensorEvaluation,
) -> UsEpaOzoneSensorEvaluationOut:
    sensor = evaluation.sensor
    calculation = evaluation.calculation
    return UsEpaOzoneSensorEvaluationOut(
        sensor_id=sensor.sensor_id,
        external_sensor_id=sensor.external_sensor_id,
        aggregation_period=sensor.aggregation_period,
        input_unit_code=sensor.input_unit_code,
        input_unit_symbol=sensor.input_unit_symbol,
        hourly_concentration_provenance=sensor.hourly_concentration_provenance,
        hourly_timestamp_semantics=sensor.hourly_timestamp_semantics,
        expected_frequency_seconds=sensor.expected_frequency_seconds,
        measurement_duration_seconds=sensor.measurement_duration_seconds,
        source_aggregation_duration_seconds=sensor.source_aggregation_duration_seconds,
        measurement_timestamp_semantics=sensor.measurement_timestamp_semantics,
        measurement_metadata_status=sensor.measurement_metadata_status,
        metadata_is_verified_and_complete=evaluation.metadata_is_verified_and_complete,
        calculation_status=calculation.calculation_status,
        blocking_reasons=[reason.value for reason in evaluation.blocking_reasons],
        audit_flags=[flag.value for flag in evaluation.audit_flags],
        valid_hour_count=evaluation.valid_hour_count,
        valid_sample_count=evaluation.valid_sample_count,
        duplicate_observation_count=evaluation.duplicate_observation_count,
        rejected_observation_count=evaluation.rejected_observation_count,
        off_frequency_observation_count=evaluation.off_frequency_observation_count,
        measurement_ids=list(evaluation.measurement_ids),
        ozone_8_hour_candidate=_ozone_candidate_out(calculation.eight_hour_candidate),
        ozone_1_hour_candidate=_ozone_candidate_out(calculation.one_hour_candidate),
        selected_aggregation_period=calculation.selected_aggregation_period,
        hourly_inputs=[
            _hourly_completeness_out(hourly_input)
            for hourly_input in evaluation.hourly_inputs
        ],
    )


def _us_epa_ozone_result_out(
    result: UsEpaOzoneDeviceResult,
) -> DeviceAirQualityIndexOut:
    calculation = result.calculation
    selected = calculation.selected_candidate
    is_calculated = selected is not None
    parameter_code = "o3"
    primary_reason = result.blocking_reasons[0] if result.blocking_reasons else None
    selected_coverage_status = (
        selected.coverage_status.value if selected else "none"
    )
    selected_expected_count = selected.expected_hour_count if selected else None
    selected_valid_count = selected.valid_hour_count if selected else None
    pollutant_result = PollutantIndexResultOut(
        standard_code=US_EPA_STANDARD.code,
        methodology_version=US_EPA_STANDARD.methodology_version,
        parameter_code=parameter_code,
        normalized_concentration=(selected.normalized_concentration if selected else None),
        normalized_unit=(selected.normalized_unit if selected else None),
        result_kind=US_EPA_STANDARD.result_kind.value,
        numeric_value=(selected.numeric_value if selected else None),
        category_code=(selected.category_code if selected else None),
        category_label=(selected.category_label if selected else None),
        eligibility_status="eligible" if is_calculated else "ineligible",
        exclusion_reason=(primary_reason.value if primary_reason else None),
    )
    return DeviceAirQualityIndexOut(
        standard_code=US_EPA_STANDARD.code,
        methodology_version=US_EPA_STANDARD.methodology_version,
        result_kind=US_EPA_STANDARD.result_kind.value,
        device_id=result.device_id,
        device_name=result.device_name,
        device_friendly_name=result.device_friendly_name,
        latitude=result.latitude,
        longitude=result.longitude,
        device_timezone=result.device_timezone,
        source_name=result.source_name,
        observed_at=result.observed_at,
        numeric_value=(selected.numeric_value if selected else None),
        category_code=(selected.category_code if selected else None),
        category_label=(selected.category_label if selected else None),
        eligibility_status="eligible" if is_calculated else "ineligible",
        exclusion_reasons=[reason.value for reason in result.blocking_reasons],
        dominant_pollutants=[parameter_code] if is_calculated else [],
        pollutant_results=[pollutant_result],
        coverage=CoverageInformationOut(
            coverage_status=selected_coverage_status,
            available_pollutants=[parameter_code] if is_calculated else [],
            missing_pollutants=[],
            ineligible_pollutants=[] if is_calculated else [parameter_code],
            missing_or_ineligible_pollutants=[] if is_calculated else [parameter_code],
            display_qualification="not_evaluated",
        ),
        sensor_provenance=[],
        parameter_code=parameter_code,
        product_code=result.product.product_code,
        product_display_name=result.product.display_name,
        product_kind=result.product.product_kind,
        methodology_code=result.product.methodology_code,
        methodology_revision=result.product.methodology_revision,
        methodology_effective_date=result.product.methodology_effective_date,
        methodology_references=[
            _methodology_reference_out(reference)
            for reference in result.product.methodology_references
        ],
        calculation_status=calculation.calculation_status,
        coverage_status=selected_coverage_status,
        exclusion_reason=(primary_reason.value if primary_reason else None),
        aqi_scale_status=(
            selected.aqi_scale_status.value
            if selected and selected.aqi_scale_status else None
        ),
        expected_observation_count=selected_expected_count,
        valid_observation_count=selected_valid_count,
        window_started_at=(selected.interval_started_at if selected else None),
        window_ended_at=(selected.interval_ended_at if selected else None),
        normalized_concentration=(selected.normalized_concentration if selected else None),
        normalized_unit=(selected.normalized_unit if selected else None),
        preprocessed_concentration=(selected.preprocessed_concentration if selected else None),
        sensor_id=(
            result.selected_sensor.sensor_id
            if is_calculated and result.selected_sensor
            else None
        ),
        external_sensor_id=(
            result.selected_sensor.external_sensor_id
            if is_calculated and result.selected_sensor
            else None
        ),
        measurement_ids=(list(result.measurement_ids) if is_calculated else []),
        valid_sample_count=result.valid_sample_count if is_calculated else 0,
        selected_sensor_reason=(
            result.selected_sensor_reason if is_calculated else None
        ),
        valid_hourly_slot_count=selected_valid_count,
        missing_hourly_slot_count=(
            selected_expected_count - selected_valid_count
            if selected_expected_count is not None and selected_valid_count is not None
            else None
        ),
        data_qualification_status="not_evaluated",
        limitations=list(result.product.limitations),
        blocking_reasons=[reason.value for reason in result.blocking_reasons],
        audit_flags=list(dict.fromkeys(
            flag.value
            for evaluation in result.candidate_sensor_evaluations
            for flag in evaluation.audit_flags
        )),
        selected_aggregation_period=calculation.selected_aggregation_period,
        ozone_8_hour_candidate=_ozone_candidate_out(calculation.eight_hour_candidate),
        ozone_1_hour_candidate=_ozone_candidate_out(calculation.one_hour_candidate),
        ozone_candidate_sensor_evaluations=[
            _ozone_sensor_evaluation_out(evaluation)
            for evaluation in result.candidate_sensor_evaluations
        ],
    )


def _gas_sensor_evaluation_out(
    evaluation: UsEpaGasSensorEvaluation,
) -> UsEpaGasSensorEvaluationOut:
    sensor = evaluation.sensor
    return UsEpaGasSensorEvaluationOut(
        sensor_id=sensor.sensor_id,
        external_sensor_id=sensor.external_sensor_id,
        parameter_code=evaluation.parameter_code,
        aggregation_period=sensor.aggregation_period,
        input_unit_code=sensor.input_unit_code,
        input_unit_symbol=sensor.input_unit_symbol,
        hourly_concentration_provenance=sensor.hourly_concentration_provenance,
        hourly_timestamp_semantics=sensor.hourly_timestamp_semantics,
        expected_frequency_seconds=sensor.expected_frequency_seconds,
        measurement_duration_seconds=sensor.measurement_duration_seconds,
        source_aggregation_duration_seconds=sensor.source_aggregation_duration_seconds,
        measurement_timestamp_semantics=sensor.measurement_timestamp_semantics,
        measurement_metadata_status=sensor.measurement_metadata_status,
        measurement_metadata_managed_by=sensor.measurement_metadata_managed_by,
        metadata_is_verified_and_complete=evaluation.metadata_is_verified_and_complete,
        calculation_status=(
            "calculated" if evaluation.is_calculated else "unavailable"
        ),
        blocking_reasons=[reason.value for reason in evaluation.blocking_reasons],
        audit_flags=[flag.value for flag in evaluation.audit_flags],
        valid_hour_count=evaluation.valid_hour_count,
        valid_sample_count=evaluation.valid_sample_count,
        duplicate_observation_count=evaluation.duplicate_observation_count,
        rejected_observation_count=evaluation.rejected_observation_count,
        off_frequency_observation_count=evaluation.off_frequency_observation_count,
        measurement_ids=list(evaluation.measurement_ids),
        hourly_inputs=[
            _hourly_completeness_out(hourly_input)
            for hourly_input in evaluation.hourly_inputs
        ],
    )


def _us_epa_gas_result_out(
    result: UsEpaGasDeviceResult,
) -> DeviceAirQualityIndexOut:
    window_calculation = result.calculation
    calculation = window_calculation.calculation
    is_calculated = calculation is not None and calculation.is_calculated
    selected_coverage_status = (
        window_calculation.coverage_status.value if is_calculated else "none"
    )
    primary_reason = (
        None
        if is_calculated
        else result.blocking_reasons[0]
        if result.blocking_reasons
        else None
    )
    pollutant_result = PollutantIndexResultOut(
        standard_code=US_EPA_STANDARD.code,
        methodology_version=US_EPA_STANDARD.methodology_version,
        parameter_code=result.parameter_code,
        normalized_concentration=(
            calculation.normalized_concentration if is_calculated else None
        ),
        normalized_unit=(calculation.normalized_unit if is_calculated else None),
        result_kind=US_EPA_STANDARD.result_kind.value,
        numeric_value=(calculation.numeric_value if calculation else None),
        category_code=(calculation.category_code if calculation else None),
        category_label=(calculation.category_label if calculation else None),
        eligibility_status="eligible" if is_calculated else "ineligible",
        exclusion_reason=(primary_reason.value if primary_reason else None),
    )
    return DeviceAirQualityIndexOut(
        standard_code=US_EPA_STANDARD.code,
        methodology_version=US_EPA_STANDARD.methodology_version,
        result_kind=US_EPA_STANDARD.result_kind.value,
        device_id=result.device_id,
        device_name=result.device_name,
        device_friendly_name=result.device_friendly_name,
        latitude=result.latitude,
        longitude=result.longitude,
        device_timezone=result.device_timezone,
        source_name=result.source_name,
        observed_at=result.observed_at,
        numeric_value=(calculation.numeric_value if calculation else None),
        category_code=(calculation.category_code if calculation else None),
        category_label=(calculation.category_label if calculation else None),
        eligibility_status="eligible" if is_calculated else "ineligible",
        exclusion_reasons=[reason.value for reason in result.blocking_reasons],
        dominant_pollutants=[result.parameter_code] if is_calculated else [],
        pollutant_results=[pollutant_result],
        coverage=CoverageInformationOut(
            coverage_status=selected_coverage_status,
            available_pollutants=[result.parameter_code] if is_calculated else [],
            missing_pollutants=[],
            ineligible_pollutants=[] if is_calculated else [result.parameter_code],
            missing_or_ineligible_pollutants=(
                [] if is_calculated else [result.parameter_code]
            ),
            display_qualification="not_evaluated",
        ),
        sensor_provenance=[],
        parameter_code=result.parameter_code,
        product_code=result.product.product_code,
        product_display_name=result.product.display_name,
        product_kind=result.product.product_kind,
        methodology_code=result.product.methodology_code,
        methodology_revision=result.product.methodology_revision,
        methodology_effective_date=result.product.methodology_effective_date,
        methodology_references=[
            _methodology_reference_out(reference)
            for reference in result.product.methodology_references
        ],
        calculation_status="calculated" if is_calculated else "unavailable",
        coverage_status=selected_coverage_status,
        exclusion_reason=(primary_reason.value if primary_reason else None),
        aqi_scale_status=(
            calculation.aqi_scale_status.value
            if calculation and calculation.aqi_scale_status
            else None
        ),
        expected_observation_count=(
            window_calculation.expected_hour_count if is_calculated else None
        ),
        valid_observation_count=(
            window_calculation.valid_hour_count if is_calculated else None
        ),
        window_started_at=(
            window_calculation.interval_started_at if is_calculated else None
        ),
        window_ended_at=(
            window_calculation.interval_ended_at if is_calculated else None
        ),
        normalized_concentration=(
            calculation.normalized_concentration if is_calculated else None
        ),
        normalized_unit=(calculation.normalized_unit if is_calculated else None),
        preprocessed_concentration=(
            calculation.preprocessed_concentration if is_calculated else None
        ),
        sensor_id=(
            result.selected_sensor.sensor_id
            if is_calculated and result.selected_sensor
            else None
        ),
        external_sensor_id=(
            result.selected_sensor.external_sensor_id
            if is_calculated and result.selected_sensor
            else None
        ),
        measurement_ids=(list(result.measurement_ids) if is_calculated else []),
        valid_sample_count=result.valid_sample_count if is_calculated else 0,
        selected_sensor_reason=(
            result.selected_sensor_reason if is_calculated else None
        ),
        valid_hourly_slot_count=(
            window_calculation.valid_hour_count if is_calculated else None
        ),
        missing_hourly_slot_count=(
            window_calculation.expected_hour_count - window_calculation.valid_hour_count
            if is_calculated
            else None
        ),
        data_qualification_status="not_evaluated",
        limitations=list(result.product.limitations),
        blocking_reasons=[reason.value for reason in result.blocking_reasons],
        audit_flags=list(
            dict.fromkeys(
                flag.value
                for evaluation in result.candidate_sensor_evaluations
                for flag in evaluation.audit_flags
            )
        ),
        selected_aggregation_period=(
            "8h"
            if is_calculated and result.parameter_code == "co"
            else "1h"
            if is_calculated and result.parameter_code == "no2"
            else None
        ),
        selected_calculation_code=(
            result.product.calculation_code if is_calculated else None
        ),
        gas_candidate_sensor_evaluations=[
            _gas_sensor_evaluation_out(evaluation)
            for evaluation in result.candidate_sensor_evaluations
        ],
    )


def _so2_candidate_out(
    candidate: SulfurDioxideAqiCandidate,
) -> UsEpaSo2CandidateOut:
    return UsEpaSo2CandidateOut(
        candidate_status=candidate.candidate_status.value,
        calculation_code=candidate.calculation_code,
        aggregation_period=candidate.aggregation_period,
        interval_started_at=candidate.interval_started_at,
        interval_ended_at=candidate.interval_ended_at,
        evaluation_interval_started_at=candidate.evaluation_interval_started_at,
        evaluation_interval_ended_at=candidate.evaluation_interval_ended_at,
        normalized_concentration=candidate.normalized_concentration,
        normalized_unit=candidate.normalized_unit,
        preprocessed_concentration=candidate.preprocessed_concentration,
        numeric_value=candidate.numeric_value,
        category_code=candidate.category_code,
        category_label=candidate.category_label,
        aqi_scale_status=(
            candidate.aqi_scale_status.value if candidate.aqi_scale_status else None
        ),
        coverage_status=candidate.coverage_status.value,
        expected_hour_count=candidate.expected_hour_count,
        valid_hour_count=candidate.valid_hour_count,
        exclusion_reason=(
            candidate.exclusion_reason.value if candidate.exclusion_reason else None
        ),
        measurement_ids=list(candidate.measurement_ids),
        reference_basis=[
            _methodology_reference_out(reference)
            for reference in candidate.reference_basis
        ],
    )


def _so2_sensor_evaluation_out(
    evaluation: UsEpaGasSensorEvaluation,
) -> UsEpaSo2SensorEvaluationOut:
    calculation = evaluation.calculation
    if not isinstance(calculation, SulfurDioxideWindowCalculation):
        raise TypeError("SO2 sensor serializer received another gas calculation")
    return UsEpaSo2SensorEvaluationOut(
        **_gas_sensor_evaluation_out(evaluation).model_dump(),
        so2_1_hour_candidate=_so2_candidate_out(calculation.one_hour_candidate),
        so2_24_hour_candidate=_so2_candidate_out(
            calculation.twenty_four_hour_candidate
        ),
        selected_aggregation_period=calculation.selected_aggregation_period,
        selected_calculation_code=calculation.selected_calculation_code,
    )


def _us_epa_so2_result_out(
    result: UsEpaGasDeviceResult,
) -> DeviceAirQualityIndexOut:
    calculation = result.calculation
    if not isinstance(calculation, SulfurDioxideWindowCalculation):
        raise TypeError("SO2 result serializer received another gas calculation")
    selected = calculation.selected_candidate
    is_calculated = selected is not None
    selected_coverage_status = (
        calculation.coverage_status.value if is_calculated else "none"
    )
    primary_reason = (
        None
        if is_calculated
        else result.blocking_reasons[0]
        if result.blocking_reasons
        else None
    )
    pollutant_result = PollutantIndexResultOut(
        standard_code=US_EPA_STANDARD.code,
        methodology_version=US_EPA_STANDARD.methodology_version,
        parameter_code="so2",
        normalized_concentration=(selected.normalized_concentration if selected else None),
        normalized_unit=(selected.normalized_unit if selected else None),
        result_kind=US_EPA_STANDARD.result_kind.value,
        numeric_value=(selected.numeric_value if selected else None),
        category_code=(selected.category_code if selected else None),
        category_label=(selected.category_label if selected else None),
        eligibility_status="eligible" if is_calculated else "ineligible",
        exclusion_reason=(primary_reason.value if primary_reason else None),
    )
    return DeviceAirQualityIndexOut(
        standard_code=US_EPA_STANDARD.code,
        methodology_version=US_EPA_STANDARD.methodology_version,
        result_kind=US_EPA_STANDARD.result_kind.value,
        device_id=result.device_id,
        device_name=result.device_name,
        device_friendly_name=result.device_friendly_name,
        latitude=result.latitude,
        longitude=result.longitude,
        device_timezone=result.device_timezone,
        source_name=result.source_name,
        observed_at=(selected.interval_ended_at if selected else result.window_ended_at),
        numeric_value=(selected.numeric_value if selected else None),
        category_code=(selected.category_code if selected else None),
        category_label=(selected.category_label if selected else None),
        eligibility_status="eligible" if is_calculated else "ineligible",
        exclusion_reasons=[reason.value for reason in result.blocking_reasons],
        dominant_pollutants=["so2"] if is_calculated else [],
        pollutant_results=[pollutant_result],
        coverage=CoverageInformationOut(
            coverage_status=selected_coverage_status,
            available_pollutants=["so2"] if is_calculated else [],
            missing_pollutants=[],
            ineligible_pollutants=[] if is_calculated else ["so2"],
            missing_or_ineligible_pollutants=[] if is_calculated else ["so2"],
            display_qualification="not_evaluated",
        ),
        sensor_provenance=[],
        parameter_code="so2",
        product_code=result.product.product_code,
        product_display_name=result.product.display_name,
        product_kind=result.product.product_kind,
        methodology_code=result.product.methodology_code,
        methodology_revision=result.product.methodology_revision,
        methodology_effective_date=result.product.methodology_effective_date,
        methodology_references=[
            _methodology_reference_out(reference)
            for reference in result.product.methodology_references
        ],
        calculation_status=calculation.calculation_status,
        coverage_status=selected_coverage_status,
        exclusion_reason=(primary_reason.value if primary_reason else None),
        aqi_scale_status=(
            selected.aqi_scale_status.value
            if selected and selected.aqi_scale_status
            else None
        ),
        expected_observation_count=(
            calculation.expected_hour_count if is_calculated else None
        ),
        valid_observation_count=(
            calculation.valid_hour_count if is_calculated else None
        ),
        window_started_at=(selected.interval_started_at if selected else None),
        window_ended_at=(selected.interval_ended_at if selected else None),
        normalized_concentration=(selected.normalized_concentration if selected else None),
        normalized_unit=(selected.normalized_unit if selected else None),
        preprocessed_concentration=(
            selected.preprocessed_concentration if selected else None
        ),
        sensor_id=(
            result.selected_sensor.sensor_id
            if is_calculated and result.selected_sensor
            else None
        ),
        external_sensor_id=(
            result.selected_sensor.external_sensor_id
            if is_calculated and result.selected_sensor
            else None
        ),
        measurement_ids=(list(result.measurement_ids) if is_calculated else []),
        valid_sample_count=result.valid_sample_count if is_calculated else 0,
        selected_sensor_reason=(
            result.selected_sensor_reason if is_calculated else None
        ),
        valid_hourly_slot_count=(
            calculation.valid_hour_count if is_calculated else None
        ),
        missing_hourly_slot_count=(
            calculation.expected_hour_count - calculation.valid_hour_count
            if is_calculated
            else None
        ),
        data_qualification_status="not_evaluated",
        limitations=list(result.product.limitations),
        blocking_reasons=[reason.value for reason in result.blocking_reasons],
        audit_flags=list(
            dict.fromkeys(
                flag.value
                for evaluation in result.candidate_sensor_evaluations
                for flag in evaluation.audit_flags
            )
        ),
        selected_aggregation_period=calculation.selected_aggregation_period,
        selected_calculation_code=calculation.selected_calculation_code,
        so2_1_hour_candidate=_so2_candidate_out(calculation.one_hour_candidate),
        so2_24_hour_candidate=_so2_candidate_out(
            calculation.twenty_four_hour_candidate
        ),
        so2_candidate_sensor_evaluations=[
            _so2_sensor_evaluation_out(evaluation)
            for evaluation in result.candidate_sensor_evaluations
        ],
    )


def _us_epa_collection(
    results: list[UsEpaDeviceAqiResult]
    | list[UsEpaCompletedDayDeviceResult]
    | list[UsEpaOzoneDeviceResult]
    | list[UsEpaGasDeviceResult],
    product_code: str,
) -> AirQualityIndexCollectionOut:
    product = next(
        product
        for product in US_EPA_STANDARD.products
        if product.product_code == product_code
    )
    return AirQualityIndexCollectionOut(
        standard_code=US_EPA_STANDARD.code,
        methodology_version=US_EPA_STANDARD.methodology_version,
        result_kind=US_EPA_STANDARD.result_kind.value,
        count=len(results),
        results=[
            _us_epa_completed_day_result_out(result)
            if isinstance(result, UsEpaCompletedDayDeviceResult)
            else _us_epa_so2_result_out(result)
            if isinstance(result, UsEpaGasDeviceResult)
            and result.parameter_code == "so2"
            else _us_epa_gas_result_out(result)
            if isinstance(result, UsEpaGasDeviceResult)
            else _us_epa_ozone_result_out(result)
            if isinstance(result, UsEpaOzoneDeviceResult)
            else _us_epa_result_out(result)
            for result in results
        ],
        product_code=product.product_code,
        product_display_name=product.display_name,
        product_kind=product.product_kind,
        methodology_code=product.methodology_code,
        methodology_revision=product.methodology_revision,
        methodology_effective_date=product.methodology_effective_date,
        methodology_references=[
            _methodology_reference_out(reference)
            for reference in product.methodology_references
        ],
        limitations=list(product.limitations),
    )


def _product_out(product: AirQualityIndexProduct) -> AirQualityIndexProductOut:
    return AirQualityIndexProductOut(
        product_code=product.product_code,
        display_name=product.display_name,
        parameter_code=product.parameter_code,
        calculation_code=product.calculation_code,
        aggregation_period=product.aggregation_period,
        aggregation_display_name=product.aggregation_display_name,
        result_scope=product.result_scope,
        is_parameter_default=product.is_parameter_default,
        availability_status=product.availability_status,
        availability_reason=product.availability_reason,
        product_kind=product.product_kind,
        history_status=product.history_status,
        history_interval=product.history_interval,
        maximum_history_interval_count=product.maximum_history_interval_count,
        methodology_code=product.methodology_code,
        methodology_revision=product.methodology_revision,
        methodology_effective_date=product.methodology_effective_date,
        methodology_references=[
            _methodology_reference_out(reference)
            for reference in product.methodology_references
        ],
        limitations=list(product.limitations),
    )


def _analytics_product(
    standard_code: str,
    product_code: str,
) -> tuple[AirQualityIndexStandard, AirQualityIndexProduct]:
    standards = (
        US_EPA_STANDARD,
        EEA_EUROPEAN_STANDARD,
        PHILIPPINES_DENR_STANDARD,
    )
    standard = next(
        (item for item in standards if item.code == standard_code),
        None,
    )
    if standard is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown air-quality index standard: {standard_code}",
        )
    product = next(
        (
            item
            for item in standard.products
            if item.product_code == product_code
        ),
        None,
    )
    if product is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown product {product_code!r} for standard "
                f"{standard_code!r}."
            ),
        )
    if product.availability_status != "available" or product.history_status != "available":
        raise HTTPException(
            status_code=400,
            detail=(
                f"History is unavailable for product {product.product_code}: "
                f"{product.availability_reason or product.history_status}"
            ),
        )
    return standard, product


def _normalized_analytics_range(
    request: AirQualityIndexAnalyticsHistoryRequest,
    products: list[AirQualityIndexProduct],
) -> tuple[datetime, datetime]:
    return _normalized_bounded_aqi_range(
        request.range_started_at,
        request.range_ended_at,
        products,
        maximum_hourly_days=366,
    )


def _normalized_bounded_aqi_range(
    range_started_at: datetime,
    range_ended_at: datetime,
    products: list[AirQualityIndexProduct],
    *,
    maximum_hourly_days: int = 90,
) -> tuple[datetime, datetime]:
    if (
        range_started_at.tzinfo is None
        or range_ended_at.tzinfo is None
    ):
        raise HTTPException(
            status_code=400,
            detail="Analytics history range timestamps must include a UTC offset.",
        )
    range_started_at = range_started_at.astimezone(timezone.utc)
    range_ended_at = range_ended_at.astimezone(timezone.utc)
    if range_started_at >= range_ended_at:
        raise HTTPException(
            status_code=400,
            detail="range_started_at must be earlier than range_ended_at.",
        )
    has_hourly_product = any(
        product.history_interval == "utc_hour" for product in products
    )
    # A 366-date device-local range can span one extra UTC hour across a
    # daylight-saving transition. The exact represented-date count is checked
    # after each selected device timezone is resolved.
    maximum_duration = timedelta(
        hours=maximum_hourly_days * 24 if has_hourly_product else 366 * 24 + 1
    )
    if range_ended_at - range_started_at > maximum_duration:
        maximum_label = f"{maximum_hourly_days} days" if has_hourly_product else "366 days"
        detail: str | dict = f"The selected AQI series support at most {maximum_label}."
        if maximum_hourly_days != 90:
            detail = {
                "error_code": "aqi_history_range_exceeded",
                "error_context": {"maximum_days": maximum_hourly_days if has_hourly_product else 366},
                "message": detail,
            }
        raise HTTPException(status_code=400, detail=detail)
    return range_started_at, range_ended_at


def _missing_analytics_point(
    *,
    interval_started_at: datetime,
    interval_ended_at: datetime,
    represented_local_date: Optional[date] = None,
    exclusion_reason: str = "missing_measurements",
) -> AirQualityIndexAnalyticsPointOut:
    return AirQualityIndexAnalyticsPointOut(
        observed_at=interval_ended_at,
        interval_started_at=interval_started_at,
        interval_ended_at=interval_ended_at,
        represented_local_date=represented_local_date,
        calculation_status="unavailable",
        eligibility_status="ineligible",
        coverage_status="none",
        exclusion_reason=exclusion_reason,
    )


def _compact_analytics_point(
    result: DeviceAirQualityIndexOut,
    *,
    product: AirQualityIndexProduct,
    european_hour_started_at: bool = False,
) -> AirQualityIndexAnalyticsPointOut:
    selected_pollutant = next(
        (
            pollutant
            for pollutant in result.pollutant_results
            if pollutant.parameter_code == product.parameter_code
        ),
        None,
    )
    is_overall = product.result_scope == "overall"
    selected_numeric_value = (
        result.numeric_value
        if is_overall or selected_pollutant is None
        else selected_pollutant.numeric_value
    )
    selected_category_code = (
        result.category_code
        if is_overall or selected_pollutant is None
        else selected_pollutant.category_code
    )
    selected_category_label = (
        result.category_label
        if is_overall or selected_pollutant is None
        else selected_pollutant.category_label
    )
    eligibility_status = (
        result.eligibility_status
        if is_overall or selected_pollutant is None
        else selected_pollutant.eligibility_status
    )
    exclusion_reason = (
        result.exclusion_reason
        or (
            selected_pollutant.exclusion_reason
            if selected_pollutant is not None
            else None
        )
        or (result.exclusion_reasons[0] if result.exclusion_reasons else None)
    )
    if european_hour_started_at:
        interval_started_at = result.observed_at
        interval_ended_at = result.observed_at + timedelta(hours=1)
    else:
        interval_ended_at = result.window_ended_at or result.observed_at
        interval_started_at = (
            result.window_started_at
            or interval_ended_at - timedelta(hours=1)
        )
    if (
        result.standard_code == EEA_EUROPEAN_STANDARD.code
        and not is_overall
        and selected_pollutant is None
    ):
        # Location coverage does not supply a result for a missing pollutant.
        # Preserve that coverage context without borrowing the overall category.
        return AirQualityIndexAnalyticsPointOut(
            observed_at=interval_ended_at,
            interval_started_at=interval_started_at,
            interval_ended_at=interval_ended_at,
            calculation_status="unavailable",
            eligibility_status="ineligible",
            coverage_status=result.coverage.coverage_status,
            exclusion_reason="missing_measurements",
            selected_calculation_code=product.calculation_code,
            selected_aggregation_period=product.aggregation_period,
            available_pollutants=result.coverage.available_pollutants,
            missing_pollutants=result.coverage.missing_pollutants,
            ineligible_pollutants=result.coverage.ineligible_pollutants,
        )
    calculation_status = result.calculation_status or (
        "calculated"
        if selected_numeric_value is not None or selected_category_code is not None
        else "unavailable"
    )
    concentration_result = selected_pollutant
    if is_overall:
        concentration_result = None
        if len(result.dominant_pollutants) == 1:
            concentration_result = next(
                (
                    pollutant
                    for pollutant in result.pollutant_results
                    if pollutant.parameter_code == result.dominant_pollutants[0]
                ),
                None,
            )
    return AirQualityIndexAnalyticsPointOut(
        observed_at=interval_ended_at,
        interval_started_at=interval_started_at,
        interval_ended_at=interval_ended_at,
        represented_local_date=result.represented_local_date,
        numeric_value=selected_numeric_value,
        category_code=selected_category_code,
        category_label=selected_category_label,
        normalized_concentration=(
            concentration_result.normalized_concentration
            if concentration_result is not None
            else result.normalized_concentration if not is_overall else None
        ),
        preprocessed_concentration=(
            concentration_result.preprocessed_concentration
            if concentration_result is not None
            and concentration_result.preprocessed_concentration is not None
            else result.preprocessed_concentration if not is_overall else None
        ),
        normalized_unit=(
            concentration_result.normalized_unit
            if concentration_result is not None
            else result.normalized_unit if not is_overall else None
        ),
        calculation_status=calculation_status,
        eligibility_status=eligibility_status,
        coverage_status=result.coverage.coverage_status,
        exclusion_reason=exclusion_reason,
        selected_calculation_code=(
            result.selected_calculation_code or product.calculation_code
        ),
        selected_aggregation_period=(
            result.selected_aggregation_period or product.aggregation_period
        ),
        dominant_pollutants=(
            result.dominant_pollutants if is_overall else []
        ),
        available_pollutants=result.coverage.available_pollutants,
        missing_pollutants=result.coverage.missing_pollutants,
        ineligible_pollutants=result.coverage.ineligible_pollutants,
    )


def _hourly_analytics_points(
    session: Session,
    *,
    standard_code: str,
    product: AirQualityIndexProduct,
    device_id: int,
    range_started_at: datetime,
    range_ended_at: datetime,
    result_outs: Optional[List[DeviceAirQualityIndexOut]] = None,
) -> list[AirQualityIndexAnalyticsPointOut]:
    if result_outs is None:
        result_outs = _hourly_analytics_result_outs(
            session,
            standard_code=standard_code,
            product=product,
            device_ids=[device_id],
            range_started_at=range_started_at,
            range_ended_at=range_ended_at,
        )
    selected_result_outs = [
        result for result in result_outs if result.device_id == device_id
    ]
    compact_points = [
        _compact_analytics_point(
            result,
            product=product,
            european_hour_started_at=(
                standard_code == EEA_EUROPEAN_STANDARD.code
            ),
        )
        for result in selected_result_outs
    ]

    points_by_interval_end = {
        point.interval_ended_at.astimezone(timezone.utc): point
        for point in compact_points
    }
    completed_hour = range_started_at.replace(minute=0, second=0, microsecond=0)
    if completed_hour < range_started_at:
        completed_hour += timedelta(hours=1)
    if standard_code == EEA_EUROPEAN_STANDARD.code:
        completed_hour += timedelta(hours=1)
    points: list[AirQualityIndexAnalyticsPointOut] = []
    now_completed_hour = datetime.now(timezone.utc).replace(
        minute=0,
        second=0,
        microsecond=0,
    )
    while completed_hour < range_ended_at:
        point = points_by_interval_end.get(completed_hour)
        if point is None:
            point = _missing_analytics_point(
                interval_started_at=completed_hour - timedelta(hours=1),
                interval_ended_at=completed_hour,
                exclusion_reason=(
                    "incomplete_interval"
                    if completed_hour > now_completed_hour
                    else "missing_measurements"
                ),
            )
        points.append(point)
        completed_hour += timedelta(hours=1)
    return points


def _hourly_analytics_result_outs(
    session: Session,
    *,
    standard_code: str,
    product: AirQualityIndexProduct,
    device_ids: List[int],
    range_started_at: datetime,
    range_ended_at: datetime,
) -> List[DeviceAirQualityIndexOut]:
    """Calculate one product group with fixed metadata and raw-input queries."""
    result_limit = 2160 * len(device_ids)
    try:
        if standard_code == PHILIPPINES_DENR_STANDARD.code:
            return [
                _philippine_result_out(result)
                for result in calculate_philippine_aqi_history(
                    session,
                    product_code=product.product_code,
                    start_utc=range_started_at,
                    end_utc=range_ended_at,
                    device_ids=device_ids,
                    limit=result_limit,
                )
            ]
        if standard_code == EEA_EUROPEAN_STANDARD.code:
            raw_results = calculate_eea_european_index_history(
                session,
                start_utc=range_started_at,
                end_utc=range_ended_at,
                device_ids=device_ids,
                limit=result_limit,
            )
            return [_result_out(result) for result in raw_results]
        elif product.calculation_code == "ozone_latest_completed_window":
            return [
                _us_epa_ozone_result_out(result)
                for result in calculate_us_epa_ozone_history(
                    session,
                    product_code=product.product_code,
                    start_utc=range_started_at,
                    end_utc=range_ended_at,
                    device_ids=device_ids,
                    limit=result_limit,
                )
            ]
        elif product.parameter_code in {"co", "no2", "so2"}:
            return [
                _us_epa_gas_result_out(result)
                for result in calculate_us_epa_gas_history(
                    session,
                    product_code=product.product_code,
                    start_utc=range_started_at,
                    end_utc=range_ended_at,
                    device_ids=device_ids,
                    limit=result_limit,
                )
            ]
        else:
            return [
                _us_epa_result_out(result)
                for result in calculate_us_epa_aqi_history(
                    session,
                    product_code=product.product_code,
                    start_utc=range_started_at,
                    end_utc=range_ended_at,
                    device_ids=device_ids,
                    limit=result_limit,
                )
            ]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _bounded_hourly_analytics_result_outs(
    session: Session,
    *,
    standard_code: str,
    product: AirQualityIndexProduct,
    device_ids: List[int],
    range_started_at: datetime,
    range_ended_at: datetime,
) -> List[DeviceAirQualityIndexOut]:
    """Retrieve long Analytics ranges within the existing 90-day service limit.

    Overlap one hour so both start-labelled EEA and end-labelled current
    products retain the boundary period. Each service still builds its own
    scientific lookback inputs. Deduplicate only identical device/hour results.
    """
    results_by_device_hour: dict[tuple[int, datetime], DeviceAirQualityIndexOut] = {}
    batch_start = range_started_at
    while batch_start < range_ended_at:
        batch_end = min(batch_start + timedelta(days=90), range_ended_at)
        for result in _hourly_analytics_result_outs(
            session,
            standard_code=standard_code,
            product=product,
            device_ids=device_ids,
            range_started_at=batch_start,
            range_ended_at=batch_end,
        ):
            results_by_device_hour[(result.device_id, result.observed_at)] = result
        if batch_end == range_ended_at:
            break
        batch_start = batch_end - timedelta(hours=1)
    return list(results_by_device_hour.values())


def _completed_day_analytics_points(
    session: Session,
    *,
    product: AirQualityIndexProduct,
    device: Device,
    range_started_at: datetime,
    range_ended_at: datetime,
) -> list[AirQualityIndexAnalyticsPointOut]:
    if product.product_code.startswith(f"{PHILIPPINES_DENR_STANDARD.code}."):
        try:
            results = calculate_philippine_aqi_history(
                session,
                product_code=product.product_code,
                start_utc=range_started_at,
                end_utc=range_ended_at,
                device_id=device.device_id,
                limit=366,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [
            _compact_analytics_point(_philippine_result_out(result), product=product)
            for result in results
        ]
    try:
        device_timezone = ZoneInfo(device.timezone or "")
    except ZoneInfoNotFoundError:
        return [
            _missing_analytics_point(
                interval_started_at=range_started_at,
                interval_ended_at=range_ended_at,
                exclusion_reason="invalid_device_timezone",
            )
        ]
    local_range_start = range_started_at.astimezone(device_timezone)
    local_range_end = range_ended_at.astimezone(device_timezone)
    first_local_date = local_range_start.date()
    if (
        local_range_start.hour == 0
        and local_range_start.minute == 0
        and local_range_start.second == 0
        and local_range_start.microsecond == 0
    ):
        # A completion boundary exactly at the inclusive range start belongs
        # to the preceding represented local date.
        first_local_date -= timedelta(days=1)
    # The local date containing the exclusive range end is not yet complete.
    last_local_date = local_range_end.date() - timedelta(days=1)
    represented_date_count = (last_local_date - first_local_date).days + 1
    if represented_date_count > product.maximum_history_interval_count:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Product {product.product_code} supports at most "
                f"{product.maximum_history_interval_count} represented local dates."
            ),
        )
    if represented_date_count <= 0:
        return []
    try:
        results = calculate_us_epa_completed_day_history(
            session,
            product_code=product.product_code,
            start_local_date=first_local_date,
            end_local_date=last_local_date,
            device_id=device.device_id,
            limit=366,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    points: list[AirQualityIndexAnalyticsPointOut] = []
    for result in results:
        window = result.local_day_window
        if window is None:
            continue
        interval_ended_at = window.utc_window_ended_at
        if not (range_started_at <= interval_ended_at < range_ended_at):
            continue
        compact = _compact_analytics_point(
            _us_epa_completed_day_result_out(result),
            product=product,
        )
        compact.observed_at = interval_ended_at
        compact.interval_started_at = window.utc_window_started_at
        compact.interval_ended_at = interval_ended_at
        compact.represented_local_date = result.represented_local_date
        points.append(compact)
    return points


def _analytics_series_out(
    session: Session,
    *,
    requested_series: AirQualityIndexAnalyticsSeriesRequest,
    standard: AirQualityIndexStandard,
    product: AirQualityIndexProduct,
    device: Device,
    range_started_at: datetime,
    range_ended_at: datetime,
    hourly_result_outs: Optional[List[DeviceAirQualityIndexOut]] = None,
) -> AirQualityIndexAnalyticsSeriesOut:
    points = (
        _completed_day_analytics_points(
            session,
            product=product,
            device=device,
            range_started_at=range_started_at,
            range_ended_at=range_ended_at,
        )
        if product.history_interval in {
            "represented_device_local_date",
            "represented_local_date",
        }
        else _hourly_analytics_points(
            session,
            standard_code=requested_series.standard_code,
            product=product,
            device_id=device.device_id,
            range_started_at=range_started_at,
            range_ended_at=range_ended_at,
            result_outs=hourly_result_outs,
        )
    )
    return AirQualityIndexAnalyticsSeriesOut(
        standard_code=standard.code,
        standard_display_name=standard.display_name,
        methodology_version=standard.methodology_version,
        product_code=product.product_code,
        product_display_name=product.display_name,
        parameter_code=product.parameter_code,
        calculation_code=product.calculation_code,
        aggregation_period=product.aggregation_period,
        result_kind=standard.result_kind.value,
        result_scope=product.result_scope,
        history_interval=product.history_interval,
        device_id=device.device_id,
        device_name=device.name,
        device_friendly_name=device.friendly_name,
        device_timezone=device.timezone,
        source_name=(
            device.manual_data_source_name
            or (device.external_api.name if device.external_api else None)
        ),
        points=points,
    )


@router.get("/standards", response_model=List[AirQualityIndexStandardOut])
def list_air_quality_index_standards() -> List[AirQualityIndexStandardOut]:
    standards = (
        (US_EPA_STANDARD, None, "AQI"),
        (EEA_EUROPEAN_STANDARD, "1h", NORMALIZED_UNIT),
        (PHILIPPINES_DENR_STANDARD, None, "AQI"),
    )
    return [
        AirQualityIndexStandardOut(
            standard_code=standard.code,
            display_name=standard.display_name,
            methodology_version=standard.methodology_version,
            result_kind=standard.result_kind.value,
            averaging_minutes=(
                None if standard.result_kind.value == "numeric" else standard.averaging_minutes
            ),
            required_averaging_period=required_averaging_period,
            supported_parameter_codes=list(standard.pollutants),
            normalized_unit=normalized_unit,
            categories=[
                IndexCategoryOut(
                    code=category.code,
                    label=category.label,
                    internal_severity_rank=category.internal_severity_rank,
                    color=category.color,
                    index_min=category.index_min,
                    index_max=category.index_max,
                )
                for category in standard.categories
            ],
            products=[_product_out(product) for product in standard.products],
            default_product_code=standard.default_product_code,
            is_default=standard.is_default,
            methodology_code=standard.methodology_code,
            methodology_revision=standard.methodology_revision,
            methodology_effective_date=standard.methodology_effective_date,
            methodology_references=[
                _methodology_reference_out(reference)
                for reference in standard.methodology_references
            ],
            limitations=list(standard.limitations),
        )
        for standard, required_averaging_period, normalized_unit in standards
    ]


@router.post(
    "/analytics-history",
    response_model=AirQualityIndexAnalyticsHistoryOut,
)
def air_quality_index_analytics_history(
    request: AirQualityIndexAnalyticsHistoryRequest,
    session: Session = Depends(get_session),
) -> AirQualityIndexAnalyticsHistoryOut:
    """Return compact, gap-complete history for one to six AQI series."""
    unique_requests: list[AirQualityIndexAnalyticsSeriesRequest] = []
    seen_series: set[tuple[str, str, int]] = set()
    standards_and_products: list[tuple[AirQualityIndexStandard, AirQualityIndexProduct]] = []
    for requested_series in request.series:
        normalized_series = AirQualityIndexAnalyticsSeriesRequest(
            standard_code=requested_series.standard_code.strip().lower(),
            product_code=requested_series.product_code.strip().lower(),
            device_id=requested_series.device_id,
        )
        series_key = (
            normalized_series.standard_code,
            normalized_series.product_code,
            normalized_series.device_id,
        )
        if series_key in seen_series:
            continue
        standard, product = _analytics_product(
            normalized_series.standard_code,
            normalized_series.product_code,
        )
        seen_series.add(series_key)
        unique_requests.append(normalized_series)
        standards_and_products.append((standard, product))

    range_started_at, range_ended_at = _normalized_analytics_range(
        request,
        [product for _standard, product in standards_and_products],
    )
    resolved_devices: list[Device] = []
    hourly_device_ids_by_product: dict[tuple[str, str], list[int]] = {}
    for requested_series, (_standard, product) in zip(
        unique_requests,
        standards_and_products,
    ):
        device = session.get(Device, requested_series.device_id)
        if device is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown AQI Analytics device_id: {requested_series.device_id}",
            )
        resolved_devices.append(device)
        if product.history_interval == "utc_hour":
            product_key = (
                requested_series.standard_code,
                requested_series.product_code,
            )
            product_device_ids = hourly_device_ids_by_product.setdefault(
                product_key,
                [],
            )
            if device.device_id not in product_device_ids:
                product_device_ids.append(device.device_id)

    hourly_results_by_product: dict[
        tuple[str, str], List[DeviceAirQualityIndexOut]
    ] = {}
    for product_key, product_device_ids in hourly_device_ids_by_product.items():
        standard_code, product_code = product_key
        _standard, product = _analytics_product(standard_code, product_code)
        hourly_results_by_product[product_key] = _bounded_hourly_analytics_result_outs(
            session,
            standard_code=standard_code,
            product=product,
            device_ids=product_device_ids,
            range_started_at=range_started_at,
            range_ended_at=range_ended_at,
        )

    response_series: list[AirQualityIndexAnalyticsSeriesOut] = []
    for requested_series, (standard, product), device in zip(
        unique_requests,
        standards_and_products,
        resolved_devices,
    ):
        product_key = (
            requested_series.standard_code,
            requested_series.product_code,
        )
        response_series.append(
            _analytics_series_out(
                session,
                requested_series=requested_series,
                standard=standard,
                product=product,
                device=device,
                range_started_at=range_started_at,
                range_ended_at=range_ended_at,
                hourly_result_outs=hourly_results_by_product.get(product_key),
            )
        )
    return AirQualityIndexAnalyticsHistoryOut(
        range_started_at=range_started_at,
        range_ended_at=range_ended_at,
        requested_series_count=len(request.series),
        returned_series_count=len(response_series),
        series=response_series,
    )


@router.get("/{standard_code}/latest", response_model=AirQualityIndexCollectionOut)
def latest_air_quality_index(
    standard_code: str,
    product_code: Optional[str] = Query(
        default=None,
        description=(
            "AQI product code. When omitted, the standard's backend-defined "
            "default product is used."
        ),
    ),
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[str] = None,
    until: Optional[datetime] = Query(
        default=None,
        description=(
            "UTC evaluation cutoff. Hourly products exclude the containing "
            "hour; completed-day products select the preceding device-local date."
        ),
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    all_results: bool = False,
    session: Session = Depends(get_session),
) -> AirQualityIndexCollectionOut:
    """Return each matching device's latest result for the selected product."""
    # Map needs the complete spatial picture, without a temporal cutoff.
    result_limit = None if all_results else limit
    _require_supported_standard(standard_code)
    if standard_code == US_EPA_STANDARD_CODE:
        selected_product_code = (
            product_code or US_EPA_DEFAULT_PRODUCT_CODE
        ).strip().lower()
        if not any(
            product.product_code == selected_product_code
            for product in US_EPA_STANDARD.products
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Unknown U.S. EPA AQI product: "
                    f"{selected_product_code}"
                ),
            )
        selected_product = next(
            product
            for product in US_EPA_STANDARD.products
            if product.product_code == selected_product_code
        )
        if selected_product.product_kind == "completed_day":
            results = calculate_latest_us_epa_completed_day_aqi(
                session,
                product_code=selected_product_code,
                reference_time_utc=until,
                device_id=device_id,
                external_api_name=external_api_name,
                bbox=_parse_bbox(bbox),
                limit=result_limit,
            )
        elif selected_product.calculation_code == "ozone_latest_completed_window":
            results = calculate_latest_us_epa_ozone_aqi(
                session,
                product_code=selected_product_code,
                reference_time_utc=until,
                device_id=device_id,
                external_api_name=external_api_name,
                bbox=_parse_bbox(bbox),
                limit=result_limit,
            )
        elif selected_product.calculation_code == (
            "co_latest_completed_8_hour_window"
        ):
            results = calculate_latest_us_epa_carbon_monoxide_aqi(
                session,
                product_code=selected_product_code,
                reference_time_utc=until,
                device_id=device_id,
                external_api_name=external_api_name,
                bbox=_parse_bbox(bbox),
                limit=result_limit,
            )
        elif selected_product.calculation_code == "no2_latest_completed_hour":
            results = calculate_latest_us_epa_nitrogen_dioxide_aqi(
                session,
                product_code=selected_product_code,
                reference_time_utc=until,
                device_id=device_id,
                external_api_name=external_api_name,
                bbox=_parse_bbox(bbox),
                limit=result_limit,
            )
        elif selected_product.calculation_code == (
            "so2_latest_completed_24_hour_window"
        ):
            results = calculate_latest_us_epa_sulfur_dioxide_aqi(
                session,
                product_code=selected_product_code,
                reference_time_utc=until,
                device_id=device_id,
                external_api_name=external_api_name,
                bbox=_parse_bbox(bbox),
                limit=result_limit,
            )
        else:
            results = calculate_latest_us_epa_aqi(
                session,
                product_code=selected_product_code,
                reference_time_utc=until,
                device_id=device_id,
                external_api_name=external_api_name,
                bbox=_parse_bbox(bbox),
                limit=result_limit,
            )
        return _us_epa_collection(results, selected_product_code)

    if standard_code == PHILIPPINES_DENR_STANDARD_CODE:
        selected_product_code = (
            product_code or PHILIPPINES_DENR_STANDARD.default_product_code
        ).strip().lower()
        try:
            results = calculate_latest_philippine_aqi(
                session,
                product_code=selected_product_code,
                reference_time_utc=until,
                device_id=device_id,
                external_api_name=external_api_name,
                bbox=_parse_bbox(bbox),
                limit=result_limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _philippine_collection(results, selected_product_code)

    results = calculate_latest_eea_european_index(
        session,
        reference_time_utc=until,
        device_id=device_id,
        external_api_name=external_api_name,
        bbox=_parse_bbox(bbox),
        limit=result_limit,
    )
    return _collection(results)


@router.get(
    "/us_epa/history",
    response_model=Union[
        UsEpaCompletedDayHistorySummaryOut,
        UsEpaCompletedDayHistoryFullOut,
    ],
)
def us_epa_completed_day_history(
    product_code: str = Query(
        description="Completed-day PM2.5 or PM10 U.S. EPA AQI product code."
    ),
    start_local_date: date = Query(
        description="Inclusive represented local-date range start."
    ),
    end_local_date: date = Query(
        description="Inclusive represented local-date range end."
    ),
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[str] = None,
    detail: Literal["summary", "full"] = Query(default="summary"),
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> Union[
    UsEpaCompletedDayHistorySummaryOut,
    UsEpaCompletedDayHistoryFullOut,
]:
    """Return gap-complete completed-day AQI series by device-local date."""
    selected_product_code = product_code.strip().lower()
    try:
        results = calculate_us_epa_completed_day_history(
            session,
            product_code=selected_product_code,
            start_local_date=start_local_date,
            end_local_date=end_local_date,
            device_id=device_id,
            external_api_name=external_api_name,
            bbox=_parse_bbox(bbox),
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    product = next(
        product
        for product in US_EPA_STANDARD.products
        if product.product_code == selected_product_code
    )
    return _us_epa_completed_day_history_response(
        results,
        product=product,
        start_local_date=start_local_date,
        end_local_date=end_local_date,
        detail=detail,
    )


@router.get("/us_epa/current-history", response_model=AirQualityIndexCollectionOut)
def us_epa_current_condition_history(
    product_code: str = Query(
        description="U.S. EPA current-condition AQI product code."
    ),
    start: datetime = Query(description="Inclusive UTC evaluation range start."),
    end: datetime = Query(description="Exclusive UTC evaluation range end."),
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[str] = None,
    limit: int = Query(default=1000, ge=1, le=10000),
    session: Session = Depends(get_session),
) -> AirQualityIndexCollectionOut:
    """Return up to 90 days of methodology-consistent hourly U.S. evaluations."""
    selected_product_code = product_code.strip().lower()
    selected_product = next(
        (
            product
            for product in US_EPA_STANDARD.products
            if product.product_code == selected_product_code
        ),
        None,
    )
    if selected_product is None:
        raise HTTPException(
            status_code=400,
            detail="A valid U.S. EPA current-condition product_code is required.",
        )
    if selected_product.product_kind == "completed_day":
        raise HTTPException(
            status_code=400,
            detail=(
                "Completed-day history uses represented local dates at "
                "/air-quality-index/us_epa/history."
            ),
        )
    normalized_start, normalized_end = _normalized_bounded_aqi_range(
        start,
        end,
        [selected_product],
    )
    try:
        if selected_product.calculation_code == "ozone_latest_completed_window":
            results = calculate_us_epa_ozone_history(
                session,
                product_code=selected_product_code,
                start_utc=normalized_start,
                end_utc=normalized_end,
                device_id=device_id,
                external_api_name=external_api_name,
                bbox=_parse_bbox(bbox),
                limit=limit,
            )
        elif selected_product.parameter_code in {"co", "no2", "so2"}:
            results = calculate_us_epa_gas_history(
                session,
                product_code=selected_product_code,
                start_utc=normalized_start,
                end_utc=normalized_end,
                device_id=device_id,
                external_api_name=external_api_name,
                bbox=_parse_bbox(bbox),
                limit=limit,
            )
        else:
            results = calculate_us_epa_aqi_history(
                session,
                product_code=selected_product_code,
                start_utc=normalized_start,
                end_utc=normalized_end,
                device_id=device_id,
                external_api_name=external_api_name,
                bbox=_parse_bbox(bbox),
                limit=limit,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _us_epa_collection(results, selected_product_code)


@router.get("/{standard_code}/history", response_model=AirQualityIndexCollectionOut)
def air_quality_index_history(
    standard_code: str,
    start: datetime = Query(description="Inclusive UTC range start."),
    end: datetime = Query(description="Exclusive UTC range end."),
    product_code: Optional[str] = Query(
        default=None,
        description="Selected AQI product context.",
    ),
    device_id: Optional[int] = None,
    external_api_name: Optional[str] = None,
    bbox: Optional[str] = None,
    limit: int = Query(default=1000, ge=1, le=10000),
    session: Session = Depends(get_session),
) -> AirQualityIndexCollectionOut:
    """Return supported standard history fully contained in the requested range."""
    if standard_code == PHILIPPINES_DENR_STANDARD.code:
        selected_product_code = (
            product_code or PHILIPPINES_DENR_STANDARD.default_product_code
        ).strip().lower()
        try:
            results = calculate_philippine_aqi_history(
                session,
                product_code=selected_product_code,
                start_utc=start,
                end_utc=end,
                device_id=device_id,
                external_api_name=external_api_name,
                bbox=_parse_bbox(bbox),
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _philippine_collection(results, selected_product_code)
    if standard_code != EEA_EUROPEAN_STANDARD.code:
        raise HTTPException(
            status_code=404,
            detail=(
                "Air-quality index history is not available for standard: "
                f"{standard_code}"
            ),
        )
    try:
        results = calculate_eea_european_index_history(
            session,
            start_utc=start,
            end_utc=end,
            device_id=device_id,
            external_api_name=external_api_name,
            bbox=_parse_bbox(bbox),
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _collection(results)
