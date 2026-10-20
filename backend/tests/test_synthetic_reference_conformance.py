from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import models
from reference_data.fixture_io import read_fixture_manifest, read_fixture_measurements
from reference_data.loader import load_reference_fixture
from services.air_quality_index.hourly_pm_completeness import (
    HourlyCompletenessAuditFlag,
    RawHourlyObservation,
    construct_subhourly_pm_hour,
)
from services.measurement_aggregation import (
    execute_measurement_aggregation,
    load_measurement_aggregation_capabilities,
    resolve_measurement_aggregation,
)


FIXTURE_ROOT = (
    Path(__file__).parent / "fixtures" / "reference_data" / "synthetic" / "purpleair_2m"
)


def _observations_by_sensor_ref():
    manifest = read_fixture_manifest(FIXTURE_ROOT)
    measurements = read_fixture_measurements(FIXTURE_ROOT, manifest)
    grouped = {}
    for measurement_id, measurement in enumerate(measurements, start=1):
        grouped.setdefault(measurement.sensor_ref, []).append(
            RawHourlyObservation(
                measurement_id=measurement_id,
                observed_at=measurement.observed_at,
                concentration=measurement.value,
                is_valid=measurement.is_valid,
            )
        )
    return grouped


def _construct(sensor_ref: str, hour: int):
    return construct_subhourly_pm_hour(
        _observations_by_sensor_ref()[sensor_ref],
        interval_started_at=datetime(2026, 7, 1, hour, tzinfo=timezone.utc),
        parameter_code="pm25",
        input_unit="ug_m3",
        expected_frequency_seconds=120,
        measurement_duration_seconds=120,
        source_aggregation_duration_seconds=120,
        timestamp_semantics="provider_received_at",
    )


def test_synthetic_two_minute_completeness_boundaries():
    complete = _construct("complete_pm25", 0)
    threshold = _construct("threshold_pm25", 1)
    insufficient = _construct("insufficient_pm25", 2)
    missing = _construct("missing_pm25", 3)
    assert (complete.expected_observation_count, complete.valid_observation_count, complete.eligibility_status) == (30, 30, "eligible")
    assert (threshold.required_valid_observation_count, threshold.valid_observation_count, threshold.eligibility_status) == (23, 23, "eligible")
    assert (insufficient.valid_observation_count, insufficient.eligibility_status) == (22, "ineligible")
    assert missing.missing_position_count == 10


def test_invalid_duplicate_and_off_frequency_observations_do_not_inflate_completeness():
    duplicate = _construct("duplicate_pm25", 4)
    invalid = _construct("invalid_pm25", 5)
    off_frequency = _construct("off_frequency_pm25", 6)
    assert duplicate.valid_observation_count == 1
    assert duplicate.audit_flags == (HourlyCompletenessAuditFlag.DUPLICATE_OBSERVATION_INTERVAL,)
    assert invalid.valid_observation_count == 0
    assert HourlyCompletenessAuditFlag.INVALID_OBSERVATIONS_REJECTED in invalid.audit_flags
    assert off_frequency.valid_observation_count == 0
    assert HourlyCompletenessAuditFlag.OFF_FREQUENCY_OBSERVATIONS in off_frequency.audit_flags


def test_synthetic_fixture_rolls_up_2m_to_1h_to_24h_and_unknown_native_stays_raw(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'conformance.sqlite'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        unit = models.Unit(code="ug_m3", symbol="ug/m3", name="Micrograms per cubic meter")
        session.add(unit)
        session.flush()
        parameter = models.Parameter(code="pm25", display_name="PM2.5", default_unit_id=unit.unit_id)
        two_minute = models.AggregationPeriod(code="2m", display_name="2 Minutes", duration_minutes=2, is_rolling=False)
        hourly = models.AggregationPeriod(code="1h", display_name="1 Hour", duration_minutes=60, is_rolling=False)
        daily = models.AggregationPeriod(code="24h", display_name="24 Hours", duration_minutes=1440, is_rolling=False)
        session.add_all([parameter, two_minute, hourly, daily])
        session.flush()
        session.add_all([
            models.ParameterAggregationRollup(parameter_id=parameter.parameter_id, from_aggregation_period_id=two_minute.aggregation_period_id, to_aggregation_period_id=hourly.aggregation_period_id),
            models.ParameterAggregationRollup(parameter_id=parameter.parameter_id, from_aggregation_period_id=hourly.aggregation_period_id, to_aggregation_period_id=daily.aggregation_period_id),
            models.ParameterAggregationRule(parameter_id=parameter.parameter_id, aggregation_period_id=daily.aggregation_period_id, rounding_method="round", rounding_precision=1, truncation_method="none"),
        ])
        session.commit()
        loaded = load_reference_fixture(session, FIXTURE_ROOT)

        aggregation_sensor_id = loaded.sensor_ids["aggregation_pm25"]
        points = execute_measurement_aggregation(
            session,
            sensor_ids=[aggregation_sensor_id],
            parameter_code="pm25",
            native_aggregation_code="2m",
            result_aggregation_code="24h",
        )
        assert len(points) == 1
        assert points[0].value == 10.0
        assert points[0].sample_count == 720
        assert resolve_measurement_aggregation(session, "pm25", "2m", "24h").path == ("2m", "1h", "24h")

        session.add(models.ParameterAggregationRollup(parameter_id=parameter.parameter_id, from_aggregation_period_id=two_minute.aggregation_period_id, to_aggregation_period_id=daily.aggregation_period_id))
        session.commit()
        assert resolve_measurement_aggregation(session, "pm25", "2m", "24h").path == ("2m", "24h")

        capabilities = load_measurement_aggregation_capabilities(session, parameter_code="pm25")
        unknown = next(item for item in capabilities if item["native_aggregation_code"] is None)
        assert [item["result_aggregation_code"] for item in unknown["supported_aggregations"]] == ["raw"]
