"""Independent EEA gas acceptance vectors: 44 minutes fail, 45 qualify."""

from datetime import datetime, timedelta, timezone
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from api.main import app
from models import Measurement, QCRule
from sources.openaq.openaq_upserts import upsert_measurement_with_policy_detailed
from services.air_quality_index.eea_gas_hourly import construct_eea_gas_hour
from services.air_quality_index.hourly_measurements import HourlySensorStreamMetadata
from services.air_quality_index.hourly_pm_completeness import RawHourlyObservation

from services.air_quality_index.eea_european_service import (
    calculate_eea_european_index_history,
    calculate_latest_eea_european_index,
    _qualified_hourly_input,
)
from test_eea_european_api import aqi_database, _add_stream


HOUR = datetime(2026, 1, 2, 10, tzinfo=timezone.utc)


@pytest.mark.parametrize("parameter", ["o3", "no2", "so2"])
@pytest.mark.parametrize("minutes,expected_category", [(1, None), (44, None), (45, "good"), (60, "good")])
def test_native_minute_acceptance(aqi_database, parameter, minutes, expected_category):
    session_factory, seeded = aqi_database
    with session_factory() as session:
        _add_stream(
            session, seeded, parameter_code=parameter, unit_code="ug_m3",
            aggregation_code="1m",
            values=[(HOUR + timedelta(minutes=i + 1), 5.0, True) for i in range(minutes)],
        )
        session.commit()
        history = calculate_eea_european_index_history(
            session, start_utc=HOUR, end_utc=HOUR + timedelta(hours=1),
            current_time_utc=HOUR + timedelta(hours=1, minutes=30),
        )
        latest = calculate_latest_eea_european_index(
            session, current_time_utc=HOUR + timedelta(hours=1, minutes=30),
        )
    for results in (history, latest):
        assert len(results) == 1
        result = results[0].air_quality_index_result.pollutant_results[0]
        assert result.category_code == expected_category
        assert result.eligibility_status.value == ("eligible" if expected_category else "ineligible")
        provenance = results[0].sensor_provenance[0]
        assert provenance.expected_observation_count == 60
        assert provenance.valid_observation_count == minutes
        assert provenance.required_valid_observation_count == 45
        assert provenance.achieved_completeness_fraction == minutes / 60
        if expected_category is None:
            assert result.exclusion_reason.value == "hourly_completeness_not_met"
            assert provenance.hourly_concentration == 5.0  # diagnostic mean only


def _sensor(**overrides):
    return replace(HourlySensorStreamMetadata(
        sensor_id=1, external_sensor_id=None, aggregation_period="1m",
        hourly_concentration_provenance=None, hourly_timestamp_semantics=None,
        expected_frequency_seconds=60, measurement_duration_seconds=60,
        source_aggregation_duration_seconds=60,
        measurement_timestamp_semantics="interval_end",
        measurement_metadata_status="provider_documented",
        measurement_metadata_managed_by="test_fixture",
        input_unit_code="ug_m3", input_unit_symbol="µg/m³", parameter_code="o3",
        device_id=1, device_name="Test", device_friendly_name=None,
        latitude=None, longitude=None, device_timezone="Europe/Paris", source_name="Test",
    ), **overrides)


def _minutes(count, *, valid=True):
    return [RawHourlyObservation(i + 1, HOUR + timedelta(minutes=i + 1), 5.0, valid)
            for i in range(count)]


@pytest.mark.parametrize("parameter", ["o3", "no2", "so2"])
@pytest.mark.parametrize("distinct,duplicates", [(1, 44), (44, 20), (45, 20)])
def test_duplicate_minutes_never_inflate_coverage(parameter, distinct, duplicates):
    observations = _minutes(distinct)
    observations += [replace(observations[0], measurement_id=100 + i, concentration=500.0)
                     for i in range(duplicates)]
    forward = construct_eea_gas_hour(_sensor(parameter_code=parameter), observations, hour_started_at=HOUR)
    reversed_result = construct_eea_gas_hour(
        _sensor(parameter_code=parameter), list(reversed(observations)), hour_started_at=HOUR,
    )
    assert forward == reversed_result
    assert forward.valid_observation_count == distinct
    assert forward.is_eligible is (distinct == 45)
    assert forward.hourly_concentration == 5.0  # lower-ID original wins ties
    assert len(forward.duplicate_measurement_ids) == duplicates


def test_duplicate_nearby_timestamps_share_one_expected_minute():
    observations = _minutes(44)
    observations += [replace(observations[0], measurement_id=100, observed_at=HOUR + timedelta(seconds=61))]
    result = construct_eea_gas_hour(_sensor(), observations, hour_started_at=HOUR)
    assert result.valid_observation_count == 44
    assert result.duplicate_measurement_ids == (100,)
    assert not result.is_eligible


@pytest.mark.parametrize("parameter", ["o3", "no2", "so2"])
@pytest.mark.parametrize("action,expected_valid,expected_category", [
    ("mark_invalid", 44, None), ("flag_for_review", 45, "good"),
])
def test_real_qc_failure_action_controls_minute_eligibility(
    aqi_database, parameter, action, expected_valid, expected_category,
):
    session_factory, seeded = aqi_database
    with session_factory() as session:
        sensor = _add_stream(
            session, seeded, parameter_code=parameter, unit_code="ug_m3",
            aggregation_code="1m", values=[],
        )
        session.add(QCRule(
            check_code="max_value", sensor_id=sensor.sensor_id,
            enabled_override=True,
            settings={"max": 4.0}, failure_action_override=action,
            policy_unit_id=seeded["units"]["ug_m3"].unit_id,
        ))
        session.flush()
        for i in range(45):
            measurement = Measurement(
                sensor_id=sensor.sensor_id, observed_at=HOUR + timedelta(minutes=i + 1),
                value=5.0 if i == 44 else 3.0,
            )
            upsert_measurement_with_policy_detailed(
                session, measurement, device=seeded["device"], sensor=sensor,
            )
        session.flush()
        assert measurement.is_valid is (action == "flag_for_review")
        assert "max_value" in measurement.qc_flags
        result = calculate_latest_eea_european_index(
            session, current_time_utc=HOUR + timedelta(hours=1),
        )[0]
    assert result.sensor_provenance[0].valid_observation_count == expected_valid
    assert result.air_quality_index_result.pollutant_results[0].category_code == expected_category


@pytest.mark.parametrize("semantics", ["interval_start", "interval_end"])
def test_completed_utc_hour_boundaries_and_current_hour(aqi_database, semantics):
    session_factory, seeded = aqi_database
    offset = 0 if semantics == "interval_start" else 1
    with session_factory() as session:
        sensor = _add_stream(
            session, seeded, parameter_code="o3", unit_code="ug_m3", aggregation_code="1m",
            values=[(HOUR + timedelta(minutes=i + offset), 5.0, True) for i in range(60)]
            + [(HOUR + timedelta(minutes=60 + offset), 500.0, True)],
        )
        sensor.measurement_timestamp_semantics = semantics
        session.commit()
        for now in (HOUR + timedelta(hours=1), HOUR + timedelta(hours=1, minutes=30)):
            result = calculate_latest_eea_european_index(session, current_time_utc=now)[0]
            assert result.observed_at == HOUR
            assert result.sensor_provenance[0].valid_observation_count == 60
            assert result.air_quality_index_result.category_code == "good"
        assert calculate_latest_eea_european_index(
            session, current_time_utc=HOUR + timedelta(minutes=59),
        ) == []


@pytest.mark.parametrize("parameter", ["o3", "no2", "so2"])
@pytest.mark.parametrize("semantics", ["hour_start", "hour_end"])
def test_provider_hourly_uses_one_documented_hour_not_sixty_minutes(aqi_database, parameter, semantics):
    session_factory, seeded = aqi_database
    timestamp = HOUR if semantics == "hour_start" else HOUR + timedelta(hours=1)
    with session_factory() as session:
        sensor = _add_stream(
            session, seeded, parameter_code=parameter, unit_code="ug_m3",
            values=[(timestamp, 5.0, True)],
        )
        sensor.hourly_timestamp_semantics = semantics
        session.commit()
        result = calculate_latest_eea_european_index(
            session, current_time_utc=HOUR + timedelta(hours=1),
        )[0]
    assert result.observed_at == HOUR
    assert result.air_quality_index_result.category_code == "good"
    provenance = result.sensor_provenance[0]
    assert provenance.expected_observation_count == 1
    assert provenance.valid_observation_count == 1
    assert provenance.required_valid_observation_count == 1
    assert provenance.completeness_rule_code == "compass_aq.eea_gas.hourly_provider_reported"


@pytest.mark.parametrize("metadata,expected_reason", [
    ({"hourly_concentration_provenance": None}, "hourly_aggregation_provenance_missing"),
    ({"measurement_metadata_status": None}, "hourly_aggregation_provenance_missing"),
    ({"measurement_metadata_managed_by": None}, "hourly_aggregation_provenance_missing"),
    ({"hourly_timestamp_semantics": None}, "timestamp_semantics_unknown"),
    ({"source_aggregation_duration_seconds": 60}, "unsupported_pollutant_duration_frequency_combination"),
])
def test_provider_hourly_missing_or_contradictory_metadata_is_ineligible(metadata, expected_reason):
    sensor = _sensor(
        aggregation_period="1h", hourly_concentration_provenance="provider_reported_hourly_average",
        hourly_timestamp_semantics="hour_start", expected_frequency_seconds=None,
        measurement_duration_seconds=None, source_aggregation_duration_seconds=None,
    )
    result = _qualified_hourly_input(
        replace(sensor, **metadata), [RawHourlyObservation(1, HOUR, 5.0, True)], hour_started_at=HOUR,
    )
    assert result.exclusion_reason.value == expected_reason
    assert result.completeness is None


@pytest.mark.parametrize("metadata,expected_reason", [
    ({"expected_frequency_seconds": None}, "expected_frequency_missing"),
    ({"source_aggregation_duration_seconds": 30}, "unsupported_pollutant_duration_frequency_combination"),
    ({"measurement_duration_seconds": 120}, "unsupported_pollutant_duration_frequency_combination"),
    ({"expected_frequency_seconds": 120}, "unsupported_pollutant_duration_frequency_combination"),
    ({"measurement_metadata_status": None}, "unsupported_pollutant_duration_frequency_combination"),
    ({"measurement_timestamp_semantics": None}, "timestamp_semantics_unknown"),
    ({"measurement_timestamp_semantics": "provider_received_at"}, "timestamp_semantics_unknown"),
    ({"aggregation_period": "2m"}, "unsupported_aggregation_period"),
])
def test_native_malformed_interval_metadata_is_ineligible(metadata, expected_reason):
    result = _qualified_hourly_input(_sensor(**metadata), _minutes(60), hour_started_at=HOUR)
    assert result.exclusion_reason.value == expected_reason


def test_provider_hourly_off_boundary_is_ineligible():
    sensor = _sensor(
        aggregation_period="1h", hourly_concentration_provenance="provider_reported_hourly_average",
        hourly_timestamp_semantics="hour_start", expected_frequency_seconds=3600,
        measurement_duration_seconds=3600, source_aggregation_duration_seconds=3600,
    )
    result = construct_eea_gas_hour(sensor, _minutes(1), hour_started_at=HOUR)
    assert not result.is_eligible
    assert result.exclusion_reason.value == "off_frequency_observations"


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_invalid_concentrations_cannot_supply_the_45th_minute(value):
    observations = _minutes(45)
    observations[-1] = replace(observations[-1], concentration=value)
    result = construct_eea_gas_hour(_sensor(), observations, hour_started_at=HOUR)
    assert result.valid_observation_count == 44
    assert not result.is_eligible
    assert result.rejected_measurement_ids == (45,)


def test_gas_mean_preserves_eea_mass_conversion_without_rounding():
    observations = [replace(item, concentration=0.060001) for item in _minutes(45)]
    result = _qualified_hourly_input(
        _sensor(input_unit_code="mg_m3"), observations, hour_started_at=HOUR,
    )
    assert result.exclusion_reason is None
    assert result.hourly_concentration == pytest.approx(60.001)
    assert result.completeness.normalized_unit == "µg/m³"


def test_multiple_valid_provider_rows_remain_ambiguous():
    sensor = _sensor(
        aggregation_period="1h", hourly_concentration_provenance="provider_reported_hourly_average",
        hourly_timestamp_semantics="hour_start", expected_frequency_seconds=3600,
        measurement_duration_seconds=3600, source_aggregation_duration_seconds=3600,
    )
    observations = [RawHourlyObservation(i, HOUR, 5.0, True) for i in (1, 2)]
    result = construct_eea_gas_hour(sensor, observations, hour_started_at=HOUR)
    assert not result.is_eligible
    assert result.exclusion_reason.value == "duplicate_observation_interval"


@pytest.mark.parametrize("minutes", [0, 20, 44, 45])
def test_api_history_latest_and_overall_exclude_ineligible_gas(aqi_database, minutes):
    session_factory, seeded = aqi_database
    with session_factory() as session:
        _add_stream(session, seeded, parameter_code="pm25", unit_code="ug_m3", values=[(HOUR, 5.0, True)])
        _add_stream(
            session, seeded, parameter_code="o3", unit_code="ug_m3", aggregation_code="1m",
            values=[(HOUR + timedelta(minutes=i + 1), 500.0, i < minutes) for i in range(45)],
        )
        session.commit()
    with TestClient(app) as client:
        for endpoint, params in (
            ("history", {"start": HOUR.isoformat(), "end": (HOUR + timedelta(hours=1)).isoformat()}),
            ("latest", {"until": (HOUR + timedelta(hours=1)).isoformat()}),
        ):
            response = client.get(f"/air-quality-index/eea_european/{endpoint}", params=params)
            assert response.status_code == 200
            result = response.json()["results"][0]
            assert result["category_code"] == ("extremely_poor" if minutes == 45 else "good")
            assert result["dominant_pollutants"] == (["o3"] if minutes == 45 else ["pm25"])
            assert result["coverage"]["coverage_status"] == "partial"
            gas = next(p for p in result["pollutant_results"] if p["parameter_code"] == "o3")
            provenance = next(p for p in result["sensor_provenance"] if p["parameter_code"] == "o3")
            assert provenance["valid_observation_count"] == minutes
            assert provenance["required_valid_observation_count"] == 45
            if minutes < 45:
                assert gas["category_code"] is None
                assert "o3" in result["coverage"]["ineligible_pollutants"]


def test_latest_all_invalid_gas_hour_does_not_fall_back_to_older_eligible_hour(aqi_database):
    session_factory, seeded = aqi_database
    with session_factory() as session:
        _add_stream(
            session, seeded, parameter_code="no2", unit_code="ug_m3", aggregation_code="1m",
            values=[(HOUR - timedelta(hours=1) + timedelta(minutes=i + 1), 5.0, True) for i in range(60)]
            + [(HOUR + timedelta(minutes=1), 5.0, False)],
        )
        session.commit()
        result = calculate_latest_eea_european_index(session, current_time_utc=HOUR + timedelta(hours=1))[0]
    assert result.observed_at == HOUR
    assert result.air_quality_index_result.category_code is None
    assert result.sensor_provenance[0].valid_observation_count == 0
    assert result.air_quality_index_result.pollutant_results[0].exclusion_reason.value == "no_valid_observations"
