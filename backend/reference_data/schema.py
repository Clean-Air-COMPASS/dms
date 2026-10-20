"""Versioned, provider-neutral schema for frozen reference fixtures."""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


REFERENCE_FIXTURE_SCHEMA_VERSION = "2i.1"
RESTRICTED_PURPLEAIR_CLASSIFICATION = (
    "restricted_private_not_approved_for_public_redistribution"
)


class StrictFixtureModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FixtureOrigin(StrictFixtureModel):
    origin_kind: Literal["synthetic", "provider_capture", "provider_mirror"]
    captured_at: datetime | None = None
    description: str

    @field_validator("captured_at")
    @classmethod
    def captured_at_must_be_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value)):
            raise ValueError("captured_at must be an explicit UTC timestamp")
        return value


class FixtureReferenceArea(StrictFixtureModel):
    fixture_ref: str | None = None
    name: str
    description: str
    timezone: str = "UTC"
    active_provider_sensor_id: str | None = None


class FixtureLicense(StrictFixtureModel):
    status: str
    attribution: str | None = None
    redistribution_approved: bool


class FixtureProviderChainEntry(StrictFixtureModel):
    provider: str
    role: Literal["origin", "transport", "hardware", "fixture"]


class FixtureProvenance(StrictFixtureModel):
    created_by: str
    methodology: str
    source_reference: str | None = None


class FixtureDevice(StrictFixtureModel):
    fixture_ref: str
    external_id: str
    name: str
    friendly_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    timezone: str = "UTC"
    reference_area_ref: str | None = None
    provider_name: str | None = None
    owner_name: str | None = None
    hardware_provider: str | None = None
    source_metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def coordinates_are_complete(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be supplied together")
        return self


class FixtureSensor(StrictFixtureModel):
    fixture_ref: str
    device_ref: str
    external_sensor_id: str
    parameter_code: str
    unit_code: str
    aggregation_period_code: str | None = None
    expected_frequency_seconds: int | None = Field(default=None, gt=0)
    measurement_duration_seconds: int | None = Field(default=None, gt=0)
    source_aggregation_duration_seconds: int | None = Field(default=None, gt=0)
    measurement_timestamp_semantics: str | None = None
    measurement_metadata_status: str | None = None
    measurement_metadata_managed_by: str = "reference_fixture_loader"
    provider_parameter_name: str | None = None
    provider_unit: str | None = None
    hardware_provider: str | None = None
    temporal_qualification: dict[str, Any] | None = None
    capture_statistics: dict[str, Any] | None = None


class FixtureCapture(StrictFixtureModel):
    selection_manifest_sha256: str
    source_discovery_commit: str
    endpoint_template: str
    window_start: datetime
    window_end: datetime
    page_size: int = Field(gt=0)
    max_pages_per_sensor: int = Field(gt=0)
    absolute_request_ceiling: int = Field(gt=0)
    retry_count: Literal[0]
    request_count: int = Field(ge=0)
    captured_at: datetime
    sensor_results: list[dict[str, Any]]
    pricing: dict[str, Any] | None = None

    @field_validator("window_start", "window_end", "captured_at")
    @classmethod
    def timestamps_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("capture timestamps must be explicit UTC timestamps")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def window_must_be_positive(self):
        if self.window_end <= self.window_start:
            raise ValueError("capture window_end must be after window_start")
        if self.request_count > self.absolute_request_ceiling:
            raise ValueError("capture request_count exceeds absolute_request_ceiling")
        return self


class ReferenceFixtureManifest(StrictFixtureModel):
    schema_version: Literal[REFERENCE_FIXTURE_SCHEMA_VERSION]
    dataset_id: str
    provider: str
    provider_profile: str
    access_classification: str
    origin: FixtureOrigin
    reference_area: FixtureReferenceArea
    reference_areas: list[FixtureReferenceArea] = Field(default_factory=list)
    license: FixtureLicense
    provider_chain: list[FixtureProviderChainEntry]
    provenance: FixtureProvenance
    capture: FixtureCapture | None = None
    capture_history: list[dict[str, Any]] = Field(default_factory=list)
    coverage_matrix: dict[str, dict[str, bool]] | None = None
    coverage_gaps: dict[str, dict[str, str]] | None = None
    known_limitations: list[str] = Field(default_factory=list)
    devices: list[FixtureDevice]
    sensors: list[FixtureSensor]
    measurements_file: str = "measurements.jsonl"
    measurements_sha256: str

    @model_validator(mode="after")
    def references_are_unique_and_resolvable(self):
        device_refs = [device.fixture_ref for device in self.devices]
        sensor_refs = [sensor.fixture_ref for sensor in self.sensors]
        if len(device_refs) != len(set(device_refs)):
            raise ValueError("device fixture_ref values must be unique")
        if len(sensor_refs) != len(set(sensor_refs)):
            raise ValueError("sensor fixture_ref values must be unique")
        unknown_devices = {
            sensor.device_ref for sensor in self.sensors if sensor.device_ref not in device_refs
        }
        if unknown_devices:
            raise ValueError(f"unknown device references: {sorted(unknown_devices)}")
        return self


class FixtureMeasurement(StrictFixtureModel):
    sensor_ref: str
    observed_at: datetime
    value: float
    is_valid: bool = True
    qc_flags: dict[str, Any] | None = None
    qc_version: str | None = None
    repeat_count: int = Field(default=1, ge=1)
    interval_seconds: int | None = Field(default=None, gt=0)
    provider_observation_ref: str | None = None
    source_page: int | None = Field(default=None, gt=0)
    source_result_index: int | None = Field(default=None, ge=0)
    provider_parameter: dict[str, Any] | None = None
    provider_period: dict[str, Any] | None = None
    provider_field: str | None = None
    provider_timestamp: int | float | str | None = None
    provider_flag_info: dict[str, Any] | None = None
    provider_coordinates: dict[str, Any] | None = None
    provider_summary: dict[str, Any] | None = None
    provider_coverage: dict[str, Any] | None = None

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("observed_at must be an explicit UTC timestamp")
        return value.astimezone(timezone.utc)

    @field_validator("value")
    @classmethod
    def value_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("measurement value must be finite")
        return value

    @model_validator(mode="after")
    def repeated_records_need_an_interval(self):
        if self.repeat_count > 1 and self.interval_seconds is None:
            raise ValueError("repeat_count greater than one requires interval_seconds")
        return self
