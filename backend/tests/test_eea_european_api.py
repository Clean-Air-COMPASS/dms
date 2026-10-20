from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from api.main import app
from db import get_session
from models import (
    AggregationPeriod,
    Base,
    Device,
    ExternalAPI,
    Measurement,
    Parameter,
    ParameterAggregationRule,
    Sensor,
    Unit,
)
from services.air_quality_index.eea_european_service import (
    calculate_eea_european_index_history,
    calculate_latest_eea_european_index,
)
from services.aqi_engine import calculate_latest_us_epa_aqi
from services.air_quality_index.hourly_measurements import (
    retrieve_eea_averaged_completed_hour_inputs,
)


UTC = timezone.utc


@pytest.fixture()
def aqi_database():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    # Some deployed/legacy CompassAQ databases permit a null external_api_id
    # for manual devices. Build this isolated schema with that shape so the AQI
    # retrieval tests prove their outer-join behavior directly.
    external_api_id_column = Device.__table__.c.external_api_id
    original_external_api_nullable = external_api_id_column.nullable
    external_api_id_column.nullable = True
    try:
        Base.metadata.create_all(engine)
    finally:
        external_api_id_column.nullable = original_external_api_nullable
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        source = ExternalAPI(name="Test AQ Network", base_url="https://example.test", params={})
        ug = Unit(code="ug_m3", symbol="µg/m³", name="Micrograms per cubic meter")
        mg = Unit(code="mg_m3", symbol="mg/m³", name="Milligrams per cubic meter")
        ppm = Unit(code="ppm", symbol="ppm", name="Parts per million")
        session.add_all((source, ug, mg, ppm))
        session.flush()
        units = {unit.code: unit for unit in (ug, mg, ppm)}
        parameters = {}
        for code in ("pm25", "pm10", "o3", "no2", "so2"):
            parameter = Parameter(
                code=code,
                display_name=code.upper(),
                default_unit_id=ug.unit_id,
            )
            session.add(parameter)
            parameters[code] = parameter
        aggregation_periods = {}
        aggregation_period_definitions = (
            ("1m", "1 Minute", 1, False),
            ("2m", "2 Minute", 2, False),
            ("1h", "1 Hour", 60, False),
            ("8h", "8 Hour", 480, False),
            ("24h", "24 Hour", 1440, False),
            ("rolling_24h", "Rolling 24 Hour", 1440, True),
            ("aqi", "AQI", 60, False),
            ("unknown_5m", "Unrecognized Five Minute", 5, False),
        )
        for code, display_name, duration_minutes, is_rolling in aggregation_period_definitions:
            aggregation_period = AggregationPeriod(
                code=code,
                display_name=display_name,
                duration_minutes=duration_minutes,
                is_rolling=is_rolling,
            )
            session.add(aggregation_period)
            aggregation_periods[code] = aggregation_period
        session.flush()
        preprocessing_rules = {
            "pm25": ("none", None, "truncate", 1),
            "pm10": ("none", None, "truncate", 0),
            "o3": ("round", 3, "none", None),
            "no2": ("round", 1, "none", None),
            "so2": ("round", 1, "none", None),
        }
        for parameter_code, rule in preprocessing_rules.items():
            session.add(
                ParameterAggregationRule(
                    parameter_id=parameters[parameter_code].parameter_id,
                    aggregation_period_id=aggregation_periods["1h"].aggregation_period_id,
                    rounding_method=rule[0],
                    rounding_precision=rule[1],
                    truncation_method=rule[2],
                    truncation_precision=rule[3],
                    active=True,
                )
            )
        device = Device(
            name="European test station",
            friendly_name="Test Station",
            external_id="european-test-station",
            external_api_id=source.external_api_id,
            timezone="Europe/Paris",
        )
        other_device = Device(
            name="Outside station",
            external_id="outside-test-station",
            external_api_id=source.external_api_id,
            timezone="UTC",
        )
        manual_device = Device(
            name="Manual European station",
            external_id="manual-european-test-station",
            external_api_id=None,
            manual_data_source_name="Neighborhood Lab",
            timezone="Europe/London",
        )
        linked_manual_device = Device(
            name="Linked manual European station",
            external_id="linked-manual-european-test-station",
            external_api_id=source.external_api_id,
            manual_data_source_name="Community Project",
            timezone="Europe/London",
        )
        session.add_all((device, other_device, manual_device, linked_manual_device))
        from services.device_locations import set_device_location

        for located_device, latitude, longitude in (
            (device, 48.85, 2.35),
            (other_device, 10.0, 10.0),
            (manual_device, 51.5, -0.1),
            (linked_manual_device, 52.5, -1.9),
        ):
            set_device_location(
                session,
                located_device,
                latitude=latitude,
                longitude=longitude,
            )
        session.commit()

    def override_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield session_factory, {
            "source": source,
            "units": units,
            "parameters": parameters,
            "aggregation_periods": aggregation_periods,
            "device": device,
            "other_device": other_device,
            "manual_device": manual_device,
            "linked_manual_device": linked_manual_device,
        }
    finally:
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()


def _add_stream(
    session: Session,
    seeded: dict,
    *,
    parameter_code: str,
    unit_code: str,
    values: list[tuple[datetime, float, bool]],
    device_key: str = "device",
    external_sensor_id: str | None = None,
    aggregation_code: str | None = "1h",
) -> Sensor:
    aggregation_period = (
        seeded["aggregation_periods"][aggregation_code]
        if aggregation_code is not None
        else None
    )
    sensor = Sensor(
        device_id=seeded[device_key].device_id,
        parameter_id=seeded["parameters"][parameter_code].parameter_id,
        unit_id=seeded["units"][unit_code].unit_id,
        aggregation_period_id=(
            aggregation_period.aggregation_period_id
            if aggregation_period is not None
            else None
        ),
        external_sensor_id=external_sensor_id,
        hourly_concentration_provenance=(
            "provider_reported_hourly_average"
            if aggregation_code == "1h"
            else None
        ),
        hourly_timestamp_semantics=(
            "hour_start" if aggregation_code == "1h" else None
        ),
        expected_frequency_seconds=(
            seeded["aggregation_periods"][aggregation_code].duration_minutes * 60
            if aggregation_code in {"1m", "2m"}
            else None
        ),
        measurement_duration_seconds=(
            seeded["aggregation_periods"][aggregation_code].duration_minutes * 60
            if aggregation_code in {"1m", "2m"}
            else None
        ),
        source_aggregation_duration_seconds=(
            seeded["aggregation_periods"][aggregation_code].duration_minutes * 60
            if aggregation_code in {"1m", "2m"}
            else None
        ),
        measurement_timestamp_semantics=(
            "provider_received_at"
            if aggregation_code == "2m"
            else "interval_end"
            if aggregation_code == "1m"
            else None
        ),
        measurement_metadata_status=(
            "provider_documented"
            if aggregation_code in {"1m", "2m", "1h"}
            else None
        ),
        measurement_metadata_managed_by=(
            "test_fixture"
            if aggregation_code in {"1m", "2m", "1h"}
            else None
        ),
    )
    session.add(sensor)
    session.flush()
    session.add_all(
        Measurement(sensor_id=sensor.sensor_id, observed_at=observed_at, value=value, is_valid=is_valid)
        for observed_at, value, is_valid in values
    )
    session.flush()
    return sensor


def _regular_values(
    hour_started_at: datetime,
    *,
    frequency_seconds: int,
    valid_position_count: int,
    concentration: float = 20.0,
) -> list[tuple[datetime, float, bool]]:
    """Build interval-end observations at distinct expected positions."""
    return [
        (
            hour_started_at + timedelta(seconds=frequency_seconds * position),
            concentration,
            True,
        )
        for position in range(1, valid_position_count + 1)
    ]


def test_standards_endpoint_describes_categorical_european_methodology(aqi_database):
    with TestClient(app) as client:
        response = client.get("/air-quality-index/standards")
    assert response.status_code == 200
    body = response.json()
    assert [standard["standard_code"] for standard in body] == [
        "us_epa",
        "eea_european",
        "philippines_denr",
    ]
    us_standard, european_standard, philippine_standard = body
    assert us_standard["is_default"] is True
    assert us_standard["default_product_code"] == "us_epa.pm25.nowcast"
    assert us_standard["required_averaging_period"] is None
    assert us_standard["averaging_minutes"] is None
    assert {
        product["product_code"] for product in us_standard["products"]
    } == {
        "us_epa.pm25.nowcast",
        "us_epa.pm10.nowcast",
        "us_epa.o3.latest",
        "us_epa.co.latest",
        "us_epa.no2.latest",
        "us_epa.so2.latest",
        "us_epa.pm25.completed_day",
        "us_epa.pm10.completed_day",
    }
    assert european_standard["methodology_version"] == "eea_2024_bands"
    assert european_standard["result_kind"] == "categorical"
    assert european_standard["required_averaging_period"] == "1h"
    assert european_standard["supported_parameter_codes"] == ["pm25", "pm10", "o3", "no2", "so2"]
    assert european_standard["default_product_code"] == "eea_european.overall.hourly"
    assert [product["parameter_code"] for product in european_standard["products"]] == [
        None,
        "pm25",
        "pm10",
        "o3",
        "no2",
        "so2",
    ]
    assert european_standard["categories"][-1] == {
        "code": "extremely_poor",
        "label": "Extremely poor",
        "internal_severity_rank": 6,
        "color": "#7D2181",
        "index_min": None,
        "index_max": None,
    }
    assert philippine_standard["display_name"] == "Philippines Air Quality Index"
    assert philippine_standard["methodology_version"] == "denr_emb_aqi_2021"
    assert philippine_standard["is_default"] is False
    assert philippine_standard["default_product_code"] == (
        "philippines_denr.pm25.completed_day"
    )
    assert philippine_standard["supported_parameter_codes"] == [
        "pm25",
        "pm10",
        "so2",
        "o3",
        "co",
        "no2",
    ]
    assert philippine_standard["categories"][-1]["label"] == "Emergency"
    assert philippine_standard["categories"][-1]["index_min"] == 301
    assert philippine_standard["categories"][-1]["index_max"] == 500
    assert all(
        product["result_scope"] == "pollutant"
        for product in philippine_standard["products"]
    )


def test_philippine_completed_day_history_uses_manila_boundaries(aqi_database):
    session_factory, seeded = aqi_database
    local_day_start_utc = datetime(2026, 1, 1, 16, tzinfo=UTC)
    values = [
        (local_day_start_utc + timedelta(hours=index), 25.0, True)
        for index in range(24)
    ]
    with session_factory() as session:
        _add_stream(
            session,
            seeded,
            parameter_code="pm25",
            unit_code="ug_m3",
            external_sensor_id="manila-provider-hourly-pm25",
            aggregation_code="1h",
            values=values,
        )
        session.commit()

    with TestClient(app) as client:
        response = client.get(
            "/air-quality-index/philippines_denr/history",
            params={
                "product_code": "philippines_denr.pm25.completed_day",
                "start": local_day_start_utc.isoformat(),
                "end": (local_day_start_utc + timedelta(hours=25)).isoformat(),
                "device_id": seeded["device"].device_id,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["standard_code"] == "philippines_denr"
    assert body["count"] == 2
    assert body["results"][0]["represented_local_date"] == "2026-01-01"
    assert body["results"][0]["calculation_status"] == "unavailable"
    result = body["results"][1]
    assert result["represented_local_date"] == "2026-01-02"
    assert result["utc_window_started_at"] == "2026-01-01T16:00:00Z"
    assert result["utc_window_ended_at"] == "2026-01-02T16:00:00Z"
    assert result["valid_hour_count"] == 24
    assert result["coverage_status"] == "complete"
    assert result["numeric_value"] == 50.0
    assert result["category_label"] == "Good"
    assert result["dominant_pollutants"] == []
    provenance = result["sensor_provenance"][0]
    assert provenance["input_unit_code"] == "ug_m3"
    assert provenance["expected_observation_count"] == 24
    assert provenance["valid_observation_count"] == 24
    assert provenance["required_valid_observation_count"] == 18
    assert provenance["completeness_rule_code"] == (
        "philippines_denr_representative_day"
    )
    assert "philippine_candidate_sensor_evaluations" not in result


def test_philippine_history_rejects_more_than_the_product_maximum(aqi_database):
    with TestClient(app) as client:
        response = client.get(
            "/air-quality-index/philippines_denr/history",
            params={
                "product_code": "philippines_denr.pm25.completed_day",
                "start": "2025-01-01T16:00:00Z",
                "end": "2026-01-04T16:00:00Z",
            },
        )

    assert response.status_code == 400
    assert "supports at most 366 history intervals" in response.json()["detail"]


def test_shared_retrieval_averages_valid_samples_and_preserves_provenance(aqi_database):
    session_factory, seeded = aqi_database
    with session_factory() as session:
        sensor = _add_stream(
            session,
            seeded,
            parameter_code="pm25",
            unit_code="ug_m3",
            external_sensor_id="pm-stream",
            aggregation_code="1m",
            values=[
                (datetime(2026, 1, 2, 10, 5, tzinfo=UTC), 10.0, True),
                (datetime(2026, 1, 2, 10, 25, tzinfo=UTC), 20.0, False),
                (datetime(2026, 1, 2, 10, 55, tzinfo=UTC), 30.0, True),
            ],
        )
        session.commit()
        valid_ids = tuple(
            session.scalars(
                select(Measurement.measurement_id)
                .where(Measurement.sensor_id == sensor.sensor_id, Measurement.is_valid.is_(True))
                .order_by(Measurement.measurement_id)
            ).all()
        )
        inputs = retrieve_eea_averaged_completed_hour_inputs(
            session,
            parameter_codes=("pm25",),
            start_hour_utc=datetime(2026, 1, 2, 10, tzinfo=UTC),
            end_hour_utc=datetime(2026, 1, 2, 11, tzinfo=UTC),
        )

    assert len(inputs) == 1
    assert inputs[0].hourly_concentration == 20.0
    assert inputs[0].sample_count == 2
    assert inputs[0].measurement_ids == valid_ids
    assert inputs[0].observed_at == datetime(2026, 1, 2, 10, tzinfo=UTC)
    assert inputs[0].sensor_aggregation_period == "1m"


def test_provider_hour_end_observation_is_retrieved_at_inclusive_boundary_and_represents_prior_hour(
    aqi_database,
):
    session_factory, seeded = aqi_database
    represented_hour = datetime(2026, 8, 2, 11, tzinfo=UTC)
    interval_end = represented_hour + timedelta(hours=1)
    with session_factory() as session:
        sensor = _add_stream(
            session,
            seeded,
            parameter_code="o3",
            unit_code="ug_m3",
            external_sensor_id="provider-hour-end-o3",
            aggregation_code="1h",
            values=[(interval_end, 28.16, True)],
        )
        sensor.hourly_timestamp_semantics = "hour_end"
        sensor.measurement_timestamp_semantics = "interval_end"
        session.commit()

        inputs = retrieve_eea_averaged_completed_hour_inputs(
            session,
            parameter_codes=("o3",),
            start_hour_utc=represented_hour,
            end_hour_utc=interval_end,
            device_id=seeded["device"].device_id,
        )
        history = calculate_eea_european_index_history(
            session,
            start_utc=represented_hour,
            end_utc=interval_end,
            device_id=seeded["device"].device_id,
            current_time_utc=interval_end + timedelta(hours=1),
        )
        latest = calculate_latest_eea_european_index(
            session,
            reference_time_utc=interval_end,
            device_id=seeded["device"].device_id,
            current_time_utc=interval_end + timedelta(hours=1),
        )

    assert len(inputs) == 1
    assert inputs[0].observed_at == represented_hour
    assert inputs[0].hourly_concentration == 28.16
    assert inputs[0].measurement_timestamp_semantics == "hour_end"
    assert len(history) == 1
    assert history[0].observed_at == represented_hour
    assert len(latest) == 1
    assert latest[0].observed_at == represented_hour


def test_two_minute_complete_hour_is_eligible_in_european_api_and_matches_us_completeness(
    aqi_database,
):
    session_factory, seeded = aqi_database
    hour = datetime(2026, 7, 30, 17, tzinfo=UTC)
    with session_factory() as session:
        sensor = _add_stream(
            session,
            seeded,
            parameter_code="pm25",
            unit_code="ug_m3",
            aggregation_code="2m",
            values=_regular_values(
                hour,
                frequency_seconds=120,
                valid_position_count=30,
            ),
        )
        session.commit()
        european_results = calculate_latest_eea_european_index(
            session,
            device_id=seeded["device"].device_id,
            current_time_utc=hour + timedelta(hours=1, minutes=5),
        )
        us_results = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            device_id=seeded["device"].device_id,
            current_time_utc=hour + timedelta(hours=1, minutes=5),
        )

    european = european_results[0]
    pollutant = european.air_quality_index_result.pollutant_results[0]
    provenance = european.sensor_provenance[0]
    us_latest_hour = us_results[0].completeness_evaluation.hourly_inputs[0]
    assert pollutant.eligibility_status.value == "eligible"
    assert pollutant.normalized_concentration == 20.0
    assert pollutant.category_code == "moderate"
    assert pollutant.exclusion_reason is None
    assert provenance.selected_sensor_id == sensor.sensor_id
    assert provenance.selected_sensor_aggregation_period == "2m"
    assert provenance.expected_observation_count == 30
    assert provenance.valid_observation_count == 30
    assert provenance.required_valid_observation_count == 23
    assert provenance.required_completeness_fraction == 0.75
    assert provenance.achieved_completeness_fraction == 1.0
    assert provenance.input_frequency_seconds == 120
    assert us_latest_hour.is_eligible is True
    assert us_latest_hour.valid_observation_count == provenance.valid_observation_count
    assert us_latest_hour.required_valid_observation_count == (
        provenance.required_valid_observation_count
    )

    with TestClient(app) as client:
        response = client.get(
            "/air-quality-index/eea_european/latest",
            params={
                "product_code": "eea_european.pm25.hourly",
                "device_id": seeded["device"].device_id,
                "until": (hour + timedelta(hours=1, minutes=5)).isoformat(),
            },
        )
    assert response.status_code == 200
    api_result = response.json()["results"][0]
    api_provenance = api_result["sensor_provenance"][0]
    assert api_result["eligibility_status"] == "eligible"
    assert api_result["category_code"] == "moderate"
    assert api_provenance["selected_sensor_aggregation_period"] == "2m"
    assert api_provenance["expected_observation_count"] == 30
    assert api_provenance["valid_observation_count"] == 30
    assert api_provenance["required_valid_observation_count"] == 23
    assert api_provenance["measurement_ids"]
    assert api_provenance["completeness_rule_code"] == (
        "compass_aq.us_epa_input.pm.hourly_75_percent"
    )


def test_two_minute_23_of_30_is_eligible_and_22_of_30_is_ineligible(aqi_database):
    session_factory, seeded = aqi_database
    first_hour = datetime(2026, 7, 30, 15, tzinfo=UTC)
    second_hour = first_hour + timedelta(hours=1)
    with session_factory() as session:
        _add_stream(
            session,
            seeded,
            parameter_code="pm25",
            unit_code="ug_m3",
            aggregation_code="2m",
            values=(
                _regular_values(
                    first_hour,
                    frequency_seconds=120,
                    valid_position_count=23,
                )
                + _regular_values(
                    second_hour,
                    frequency_seconds=120,
                    valid_position_count=22,
                )
            ),
        )
        session.commit()
        results = calculate_eea_european_index_history(
            session,
            start_utc=first_hour,
            end_utc=second_hour + timedelta(hours=1),
            current_time_utc=second_hour + timedelta(days=1),
        )
        evaluation_time = second_hour + timedelta(hours=1, minutes=5)
        european_latest = calculate_latest_eea_european_index(
            session,
            device_id=seeded["device"].device_id,
            current_time_utc=evaluation_time,
        )[0]
        us_latest = calculate_latest_us_epa_aqi(
            session,
            product_code="us_epa.pm25.nowcast",
            device_id=seeded["device"].device_id,
            current_time_utc=evaluation_time,
        )[0]

    by_hour = {result.observed_at: result for result in results}
    eligible = by_hour[first_hour].sensor_provenance[0]
    ineligible_result = by_hour[second_hour]
    ineligible = ineligible_result.sensor_provenance[0]
    assert eligible.valid_observation_count == 23
    assert eligible.eligible_sensor_ids == (eligible.selected_sensor_id,)
    assert ineligible.valid_observation_count == 22
    assert ineligible.eligible_sensor_ids == ()
    assert ineligible_result.air_quality_index_result.pollutant_results[
        0
    ].exclusion_reason.value == "hourly_completeness_not_met"
    european_latest_evaluation = european_latest.sensor_provenance[
        0
    ].sensor_stream_evaluations[0]
    us_latest_evaluation = us_latest.completeness_evaluation.hourly_inputs[0]
    assert european_latest_evaluation.eligibility_status.value == "ineligible"
    assert us_latest_evaluation.is_eligible is False
    assert european_latest_evaluation.valid_observation_count == (
        us_latest_evaluation.valid_observation_count
    )
    assert european_latest_evaluation.exclusion_reason == (
        us_latest_evaluation.exclusion_reason
    )


def test_duplicate_invalid_and_off_frequency_observations_do_not_inflate_european_count(
    aqi_database,
):
    session_factory, seeded = aqi_database
    hour = datetime(2026, 7, 30, 17, tzinfo=UTC)
    values = _regular_values(
        hour,
        frequency_seconds=120,
        valid_position_count=23,
    )
    values.extend(
        (
            (hour + timedelta(seconds=130), 999.0, True),
            (hour + timedelta(seconds=48 * 60), 999.0, False),
            (hour + timedelta(seconds=1), 999.0, True),
        )
    )
    with session_factory() as session:
        _add_stream(
            session,
            seeded,
            parameter_code="pm25",
            unit_code="ug_m3",
            aggregation_code="2m",
            values=values,
        )
        session.commit()
        result = calculate_eea_european_index_history(
            session,
            start_utc=hour,
            end_utc=hour + timedelta(hours=1),
            current_time_utc=hour + timedelta(days=1),
        )[0]

    provenance = result.sensor_provenance[0]
    evaluation = provenance.sensor_stream_evaluations[0]
    assert provenance.valid_observation_count == 23
    assert len(provenance.measurement_ids) == 23
    assert [flag.value for flag in provenance.audit_flags] == [
        "duplicate_observation_interval",
        "off_frequency_observations",
        "invalid_observations_rejected",
    ]
    assert len(evaluation.duplicate_measurement_ids) == 1
    assert len(evaluation.rejected_measurement_ids) == 1
    assert len(evaluation.off_frequency_measurement_ids) == 1


def test_one_minute_and_provider_hourly_pm_use_shared_completeness(aqi_database):
    session_factory, seeded = aqi_database
    minute_hour = datetime(2026, 7, 30, 15, tzinfo=UTC)
    provider_hour = minute_hour + timedelta(hours=1)
    with session_factory() as session:
        _add_stream(
            session,
            seeded,
            parameter_code="pm25",
            unit_code="ug_m3",
            aggregation_code="1m",
            values=_regular_values(
                minute_hour,
                frequency_seconds=60,
                valid_position_count=45,
            ),
        )
        _add_stream(
            session,
            seeded,
            parameter_code="pm10",
            unit_code="ug_m3",
            aggregation_code="1h",
            values=[(provider_hour, 40.0, True)],
        )
        session.commit()
        results = calculate_eea_european_index_history(
            session,
            start_utc=minute_hour,
            end_utc=provider_hour + timedelta(hours=1),
            current_time_utc=provider_hour + timedelta(days=1),
        )

    by_hour = {result.observed_at: result for result in results}
    minute_provenance = by_hour[minute_hour].sensor_provenance[0]
    provider_provenance = by_hour[provider_hour].sensor_provenance[0]
    assert minute_provenance.expected_observation_count == 60
    assert minute_provenance.required_valid_observation_count == 45
    assert minute_provenance.valid_observation_count == 45
    assert provider_provenance.expected_observation_count == 1
    assert provider_provenance.required_valid_observation_count == 1
    assert provider_provenance.valid_observation_count == 1


@pytest.mark.parametrize(
    (
        "aggregation_code",
        "frequency_seconds",
        "measurement_duration_seconds",
        "source_aggregation_duration_seconds",
    ),
    (
        ("unknown_5m", 700, 700, 700),
        ("2m", 120, 3600, 3600),
    ),
)
def test_unsupported_pm_frequency_or_duration_remains_explicitly_ineligible(
    aqi_database,
    aggregation_code: str,
    frequency_seconds: int,
    measurement_duration_seconds: int,
    source_aggregation_duration_seconds: int,
):
    session_factory, seeded = aqi_database
    hour = datetime(2026, 7, 30, 17, tzinfo=UTC)
    with session_factory() as session:
        sensor = _add_stream(
            session,
            seeded,
            parameter_code="pm25",
            unit_code="ug_m3",
            aggregation_code=aggregation_code,
            values=[(hour + timedelta(seconds=frequency_seconds), 20.0, True)],
        )
        sensor.expected_frequency_seconds = frequency_seconds
        sensor.measurement_duration_seconds = measurement_duration_seconds
        sensor.source_aggregation_duration_seconds = source_aggregation_duration_seconds
        sensor.measurement_timestamp_semantics = "interval_end"
        sensor.measurement_metadata_status = "provider_documented"
        sensor.measurement_metadata_managed_by = "test_fixture"
        session.commit()
        result = calculate_eea_european_index_history(
            session,
            start_utc=hour,
            end_utc=hour + timedelta(hours=1),
            current_time_utc=hour + timedelta(days=1),
        )[0]

    pollutant = result.air_quality_index_result.pollutant_results[0]
    assert pollutant.eligibility_status.value == "ineligible"
    assert pollutant.exclusion_reason.value == (
        "unsupported_pollutant_duration_frequency_combination"
    )
    provenance = result.sensor_provenance[0]
    assert provenance.input_frequency_seconds == frequency_seconds
    assert provenance.measurement_duration_seconds == measurement_duration_seconds
    assert (
        provenance.source_aggregation_duration_seconds
        == source_aggregation_duration_seconds
    )


def test_incompatible_and_unknown_periods_are_rejected_with_provenance(aqi_database):
    session_factory, seeded = aqi_database
    start = datetime(2026, 1, 4, 0, tzinfo=UTC)
    incompatible_periods = ("8h", "24h", "rolling_24h", "aqi", "unknown_5m", None)
    with session_factory() as session:
        for hour_offset, aggregation_code in enumerate(incompatible_periods):
            _add_stream(
                session,
                seeded,
                parameter_code="pm25",
                unit_code="ug_m3",
                aggregation_code=aggregation_code,
                values=[(start.replace(hour=hour_offset, minute=10), 12.0, True)],
            )
        session.commit()
        device_hour_results = calculate_eea_european_index_history(
            session,
            start_utc=start,
            end_utc=start.replace(hour=6),
            current_time_utc=datetime(2026, 1, 5, tzinfo=UTC),
        )

    results_by_hour = {
        device_hour_result.observed_at.hour: device_hour_result
        for device_hour_result in device_hour_results
    }
    assert len(results_by_hour) == len(incompatible_periods)
    for hour_offset, aggregation_code in enumerate(incompatible_periods):
        device_hour_result = results_by_hour[hour_offset]
        pollutant_result = device_hour_result.air_quality_index_result.pollutant_results[0]
        stream_evaluation = device_hour_result.sensor_provenance[0].sensor_stream_evaluations[0]
        assert pollutant_result.exclusion_reason.value == "expected_frequency_missing"
        assert stream_evaluation.aggregation_period == aggregation_code
        assert stream_evaluation.exclusion_reason.value == "expected_frequency_missing"

    with TestClient(app) as client:
        response = client.get(
            "/air-quality-index/eea_european/history",
            params={
                "start": "2026-01-04T00:00:00Z",
                "end": "2026-01-04T01:00:00Z",
                "device_id": seeded["device"].device_id,
            },
        )
    assert response.status_code == 200
    stream_evaluation = response.json()["results"][0]["sensor_provenance"][0][
        "sensor_stream_evaluations"
    ][0]
    assert stream_evaluation["aggregation_period"] == "8h"
    assert stream_evaluation["exclusion_reason"] == "expected_frequency_missing"


def test_history_selects_one_stream_without_averaging_duplicates_and_reports_coverage(aqi_database):
    session_factory, seeded = aqi_database
    hour = datetime(2026, 1, 2, 10, tzinfo=UTC)
    with session_factory() as session:
        rejected_pm25 = _add_stream(
            session,
            seeded,
            parameter_code="pm25",
            unit_code="ppm",
            external_sensor_id="rejected-unit",
            values=[(hour, 0.02, True)],
        )
        selected_pm25 = _add_stream(
            session,
            seeded,
            parameter_code="pm25",
            unit_code="ug_m3",
            external_sensor_id="preferred-by-id",
            values=[(hour, 20.0, True)],
        )
        duplicate_pm25 = _add_stream(
            session,
            seeded,
            parameter_code="pm25",
            unit_code="ug_m3",
            external_sensor_id="duplicate",
            values=[(hour, 100.0, True)],
        )
        _add_stream(
            session,
            seeded,
            parameter_code="pm10",
            unit_code="ug_m3",
            values=[(hour, 50.0, True)],
        )
        _add_stream(
            session,
            seeded,
            parameter_code="o3",
            unit_code="ppm",
            values=[(hour.replace(minute=20), 0.04, True)],
        )
        session.commit()
        results = calculate_eea_european_index_history(
            session,
            start_utc=hour,
            end_utc=hour.replace(hour=11),
            current_time_utc=datetime(2026, 1, 3, tzinfo=UTC),
        )

    assert len(results) == 1
    result = results[0]
    assert result.air_quality_index_result.category_code == "moderate"
    assert result.air_quality_index_result.numeric_value is None
    assert result.air_quality_index_result.dominant_pollutants == ("pm25", "pm10")
    assert result.air_quality_index_result.coverage.coverage_status.value == "partial"
    assert result.air_quality_index_result.coverage.ineligible_pollutants == ("o3",)
    assert result.air_quality_index_result.coverage.missing_pollutants == ("no2", "so2")
    provenance = result.sensor_provenance[0]
    assert provenance.selected_sensor_id == selected_pm25.sensor_id
    assert provenance.candidate_sensor_ids == (
        rejected_pm25.sensor_id,
        selected_pm25.sensor_id,
        duplicate_pm25.sensor_id,
    )
    assert provenance.duplicate_eligible_sensor_ids == (duplicate_pm25.sensor_id,)
    assert provenance.sensor_stream_evaluations[0].sensor_id == rejected_pm25.sensor_id
    assert provenance.sensor_stream_evaluations[0].exclusion_reason.value == "unsupported_unit"

    with TestClient(app) as client:
        response = client.get(
            "/air-quality-index/eea_european/history",
            params={
                "start": "2026-01-02T10:00:00Z",
                "end": "2026-01-02T11:00:00Z",
                "device_id": seeded["device"].device_id,
            },
        )
    assert response.status_code == 200
    response_provenance = response.json()["results"][0]["sensor_provenance"][0]
    assert response_provenance["selected_sensor_id"] == selected_pm25.sensor_id
    rejected_evaluation = response_provenance["sensor_stream_evaluations"][0]
    assert rejected_evaluation["sensor_id"] == rejected_pm25.sensor_id
    assert rejected_evaluation["aggregation_period"] == "1h"
    assert rejected_evaluation["eligibility_status"] == "ineligible"
    assert rejected_evaluation["exclusion_reason"] == "unsupported_unit"


def test_latest_excludes_current_hour_and_mg_conversion_is_explicit(aqi_database):
    session_factory, seeded = aqi_database
    with session_factory() as session:
        _add_stream(
            session,
            seeded,
            parameter_code="pm25",
            unit_code="mg_m3",
            values=[
                (datetime(2026, 1, 2, 11, tzinfo=UTC), 0.016, True),
                (datetime(2026, 1, 2, 12, tzinfo=UTC), 0.2, True),
            ],
        )
        session.commit()
        results = calculate_latest_eea_european_index(
            session,
            current_time_utc=datetime(2026, 1, 2, 12, 30, tzinfo=UTC),
        )

    assert len(results) == 1
    assert results[0].observed_at == datetime(2026, 1, 2, 11, tzinfo=UTC)
    pollutant = results[0].air_quality_index_result.pollutant_results[0]
    assert pollutant.normalized_concentration == 16.0
    assert pollutant.category_code == "moderate"

    with TestClient(app) as client:
        response = client.get(
            "/air-quality-index/eea_european/latest",
            params={
                "device_id": seeded["device"].device_id,
                "until": "2026-01-02T12:30:00Z",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["results"][0]["observed_at"] == "2026-01-02T11:00:00Z"
    assert body["results"][0]["numeric_value"] is None
    assert body["results"][0]["pollutant_results"][0]["normalized_concentration"] == 16.0


def test_no_eligible_pollutants_remains_an_explicit_result(aqi_database):
    session_factory, seeded = aqi_database
    hour = datetime(2026, 1, 2, 10, tzinfo=UTC)
    with session_factory() as session:
        first = _add_stream(
            session,
            seeded,
            parameter_code="o3",
            unit_code="ppm",
            values=[(hour.replace(minute=5), 0.04, True)],
        )
        second = _add_stream(
            session,
            seeded,
            parameter_code="o3",
            unit_code="ppm",
            values=[(hour.replace(minute=10), 0.05, True)],
        )
        session.commit()
        results = calculate_eea_european_index_history(
            session,
            start_utc=hour,
            end_utc=hour.replace(hour=11),
            current_time_utc=datetime(2026, 1, 3, tzinfo=UTC),
        )

    result = results[0]
    assert result.air_quality_index_result.eligibility_status.value == "ineligible"
    assert [reason.value for reason in result.air_quality_index_result.exclusion_reasons] == [
        "unsupported_unit",
        "no_eligible_pollutants",
    ]
    assert result.air_quality_index_result.coverage.coverage_status.value == "none"
    assert result.air_quality_index_result.numeric_value is None
    assert result.sensor_provenance[0].selected_sensor_id == first.sensor_id
    assert result.sensor_provenance[0].eligible_sensor_ids == ()
    assert result.sensor_provenance[0].candidate_sensor_ids == (first.sensor_id, second.sensor_id)


def test_history_api_filters_and_validation(aqi_database):
    session_factory, seeded = aqi_database
    hour = datetime(2026, 1, 2, 10, tzinfo=UTC)
    with session_factory() as session:
        _add_stream(
            session,
            seeded,
            parameter_code="no2",
            unit_code="ug_m3",
            values=[(hour, 101.0, True)],
        )
        _add_stream(
            session,
            seeded,
            parameter_code="pm25",
            unit_code="ug_m3",
            device_key="other_device",
            values=[(hour, 1.0, True)],
        )
        session.commit()

    url = "/air-quality-index/eea_european/history"
    params = {
        "start": "2026-01-02T10:00:00Z",
        "end": "2026-01-02T11:00:00Z",
        "bbox": "2,48,3,49",
        "external_api_name": "test aq network",
    }
    with TestClient(app) as client:
        response = client.get(url, params=params)
        invalid_standard = client.get(url.replace("eea_european", "unknown"), params=params)
        invalid_range = client.get(url, params={"start": params["end"], "end": params["start"]})
        invalid_bbox = client.get(url, params={**params, "bbox": "3,49,2,48"})
        malformed_date = client.get(url, params={"start": "not-a-date", "end": params["end"]})
        invalid_limit = client.get(url, params={**params, "limit": 0})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["results"][0]["device_id"] == seeded["device"].device_id
    assert body["results"][0]["numeric_value"] is None
    assert body["results"][0]["category_code"] == "very_poor"
    assert invalid_standard.status_code == 404
    assert invalid_range.status_code == 400
    assert invalid_bbox.status_code == 400
    assert malformed_date.status_code == 422
    assert invalid_limit.status_code == 422


def test_analytics_history_exposes_processed_concentration_for_every_european_pollutant(
    aqi_database,
):
    session_factory, seeded = aqi_database
    observed_at = datetime(2026, 1, 6, 10, tzinfo=UTC)
    source_concentrations = {
        "pm25": 5.099999,
        "pm10": 15.999999,
        "o3": 60.000499,
        "no2": 10.049999,
        "so2": 20.049999,
    }
    expected_processed = source_concentrations
    with session_factory() as session:
        for parameter_code, concentration in source_concentrations.items():
            _add_stream(
                session,
                seeded,
                parameter_code=parameter_code,
                unit_code="ug_m3",
                values=[(observed_at, concentration, True)],
            )
        session.commit()

    series = [
        {
            "standard_code": "eea_european",
            "product_code": f"eea_european.{parameter_code}.hourly",
            "device_id": seeded["device"].device_id,
        }
        for parameter_code in source_concentrations
    ]
    series.append(
        {
            "standard_code": "eea_european",
            "product_code": "eea_european.overall.hourly",
            "device_id": seeded["device"].device_id,
        }
    )
    with TestClient(app) as client:
        response = client.post(
            "/air-quality-index/analytics-history",
            json={
                "range_started_at": observed_at.isoformat(),
                "range_ended_at": (observed_at + timedelta(hours=2)).isoformat(),
                "series": series,
            },
        )

    assert response.status_code == 200
    by_product = {
        item["product_code"]: item
        for item in response.json()["series"]
    }
    for parameter_code, source_concentration in source_concentrations.items():
        point = by_product[f"eea_european.{parameter_code}.hourly"]["points"][0]
        assert point["normalized_concentration"] == pytest.approx(source_concentration)
        assert point["preprocessed_concentration"] == expected_processed[parameter_code]
        assert point["category_code"] == "fair"
    overall_point = by_product["eea_european.overall.hourly"]["points"][0]
    assert overall_point["preprocessed_concentration"] is None


def test_analytics_missing_pollutant_does_not_inherit_overall_category(aqi_database):
    session_factory, seeded = aqi_database
    observed_at = datetime(2026, 1, 6, 10, tzinfo=UTC)
    with session_factory() as session:
        _add_stream(session, seeded, parameter_code="pm25", unit_code="ug_m3",
                    values=[(observed_at, 5.0, True)])
        session.commit()
    response = TestClient(app).post("/air-quality-index/analytics-history", json={
        "range_started_at": observed_at.isoformat(),
        "range_ended_at": (observed_at + timedelta(hours=2)).isoformat(),
        "series": [{"standard_code": "eea_european", "product_code": f"eea_european.{parameter}.hourly",
                    "device_id": seeded["device"].device_id} for parameter in ("overall", "pm25", "o3")],
    })
    assert response.status_code == 200, response.text
    points = {series["parameter_code"]: series["points"][0] for series in response.json()["series"]}
    assert points[None]["category_code"] == "good"
    assert points["pm25"]["category_code"] == "good"
    assert points["pm25"]["preprocessed_concentration"] == 5.0
    missing = points["o3"]
    for field in ("numeric_value", "category_code", "category_label", "normalized_concentration",
                  "preprocessed_concentration", "normalized_unit"):
        assert missing[field] is None
    assert missing["calculation_status"] == "unavailable"
    assert missing["eligibility_status"] == "ineligible"
    assert missing["exclusion_reason"] == "missing_measurements"
    assert missing["coverage_status"] == "partial"
    assert missing["available_pollutants"] == ["pm25"]
    assert "o3" in missing["missing_pollutants"]


def test_long_analytics_history_preserves_valid_and_unavailable_hours_at_batch_edges(aqi_database):
    session_factory, seeded = aqi_database
    start = datetime(2026, 1, 1, tzinfo=UTC)
    boundary = start + timedelta(days=90)
    valid_hours = [start, boundary - timedelta(hours=1), boundary, start + timedelta(days=270)]
    with session_factory() as session:
        _add_stream(session, seeded, parameter_code="o3", unit_code="ug_m3",
                    values=[(hour, 40.0, True) for hour in valid_hours]
                    + [(start + timedelta(hours=2), 40.0, False)])
        session.commit()
    response = TestClient(app).post("/air-quality-index/analytics-history", json={
        "range_started_at": start.isoformat(),
        "range_ended_at": (start + timedelta(days=278)).isoformat(),
        "series": [{"standard_code": "eea_european", "product_code": "eea_european.o3.hourly",
                    "device_id": seeded["device"].device_id}],
    })
    assert response.status_code == 200, response.text
    points = response.json()["series"][0]["points"]
    calculated = [point for point in points if point["calculation_status"] == "calculated"]
    assert [datetime.fromisoformat(point["interval_started_at"]) for point in calculated] == valid_hours
    assert any(point["calculation_status"] == "unavailable" for point in points)
    assert len({point["interval_ended_at"] for point in points}) == len(points)


def test_native_subhourly_history_keeps_observations_and_explains_qc_exclusion(aqi_database):
    session_factory, seeded = aqi_database
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with session_factory() as session:
        sensor = _add_stream(session, seeded, parameter_code="pm25", unit_code="ug_m3",
                             aggregation_code="2m",
                             values=[(start + timedelta(minutes=index * 2), 10.0 + index, index != 4)
                                     for index in range(30)])
        session.commit()
        sensor_id = sensor.sensor_id
    client = TestClient(app)
    path = f"/sensors/{sensor_id}/history"
    response = client.get(path, params={"aggregation": "2m", "start": start.isoformat(),
                                       "end": (start + timedelta(hours=1)).isoformat(), "include_qc": True})
    assert response.status_code == 200, response.text
    assert len(response.json()["data"]) == 29
    assert response.json()["result_aggregation_code"] == "2m"
    excluded = client.get(path, params={"aggregation": "2m", "start": (start + timedelta(minutes=8)).isoformat(),
                                      "end": (start + timedelta(minutes=8)).isoformat()})
    assert excluded.json()["history_status"] == "no_eligible_observations"
    empty = client.get(path, params={"aggregation": "2m", "start": (start - timedelta(hours=2)).isoformat(),
                                   "end": (start - timedelta(hours=1)).isoformat()})
    assert empty.json()["history_status"] == "no_observations"


def test_manual_devices_are_included_and_filtered_as_other(aqi_database):
    session_factory, seeded = aqi_database
    observed_at = datetime(2026, 1, 6, 10, tzinfo=UTC)
    with session_factory() as session:
        _add_stream(
            session,
            seeded,
            parameter_code="pm25",
            unit_code="ug_m3",
            device_key="manual_device",
            values=[(observed_at, 18.0, True)],
        )
        _add_stream(
            session,
            seeded,
            parameter_code="pm25",
            unit_code="ug_m3",
            device_key="device",
            values=[(observed_at, 4.0, True)],
        )
        _add_stream(
            session,
            seeded,
            parameter_code="pm25",
            unit_code="ug_m3",
            device_key="linked_manual_device",
            values=[(observed_at, 8.0, True)],
        )
        session.commit()

    history_url = "/air-quality-index/eea_european/history"
    history_range = {
        "start": "2026-01-06T10:00:00Z",
        "end": "2026-01-06T11:00:00Z",
    }
    latest_url = "/air-quality-index/eea_european/latest"
    latest_cutoff = {"until": "2026-01-06T11:00:00Z"}
    with TestClient(app) as client:
        history_all = client.get(history_url, params=history_range)
        history_other = client.get(
            history_url,
            params={**history_range, "external_api_name": "Other"},
        )
        history_provider = client.get(
            history_url,
            params={**history_range, "external_api_name": "test aq network"},
        )
        latest_all = client.get(latest_url, params=latest_cutoff)
        latest_other = client.get(
            latest_url,
            params={**latest_cutoff, "external_api_name": "other"},
        )
        latest_provider = client.get(
            latest_url,
            params={**latest_cutoff, "external_api_name": "Test AQ Network"},
        )

    for response in (
        history_all,
        history_other,
        history_provider,
        latest_all,
        latest_other,
        latest_provider,
    ):
        assert response.status_code == 200

    manual_device_id = seeded["manual_device"].device_id
    linked_manual_device_id = seeded["linked_manual_device"].device_id
    provider_device_id = seeded["device"].device_id
    assert {result["device_id"] for result in history_all.json()["results"]} == {
        manual_device_id,
        linked_manual_device_id,
        provider_device_id,
    }
    assert {result["device_id"] for result in history_other.json()["results"]} == {
        manual_device_id,
        linked_manual_device_id,
    }
    assert {result["source_name"] for result in history_other.json()["results"]} == {"Other"}
    assert [result["device_id"] for result in history_provider.json()["results"]] == [
        provider_device_id
    ]
    assert {result["device_id"] for result in latest_all.json()["results"]} == {
        manual_device_id,
        linked_manual_device_id,
        provider_device_id,
    }
    assert {result["device_id"] for result in latest_other.json()["results"]} == {
        manual_device_id,
        linked_manual_device_id,
    }
    assert [result["device_id"] for result in latest_provider.json()["results"]] == [
        provider_device_id
    ]
