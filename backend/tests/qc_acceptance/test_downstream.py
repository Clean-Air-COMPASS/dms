from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import models
from qaqc.admin_policy import OverrideValue, PolicyScope, replace_generic_scope_overrides
from services.air_quality_index.eea_european_service import (
    calculate_eea_european_index_history,
)
from services.air_quality_index.hourly_measurements import retrieve_raw_measurement_inputs
from services.air_quality_index.hourly_pm_completeness import (
    RawHourlyObservation,
    construct_subhourly_pm_hour,
    select_raw_observations_for_hour,
)
from services.air_quality_index.us_epa_ozone import (
    construct_provider_hourly_ozone_hour,
)
from services.measurement_aggregation import execute_measurement_aggregation
from sources.openaq.openaq_upserts import upsert_measurement_with_policy_detailed
from .support import ensure_catalog, ensure_source


def _sensor(
    session,
    source,
    parameter,
    unit,
    period,
    label,
    *,
    subhourly=False,
):
    device = models.Device(
        name=label,
        external_id=label.lower().replace(" ", "-"),
        external_api_id=source.external_api_id,
        timezone="UTC",
    )
    session.add(device)
    session.flush()
    sensor = models.Sensor(
        device_id=device.device_id,
        parameter_id=parameter.parameter_id,
        unit_id=unit.unit_id,
        aggregation_period_id=period.aggregation_period_id,
        external_sensor_id=f"{device.external_id}:{parameter.code}",
        hourly_concentration_provenance=(
            None if subhourly else "provider_reported_hourly_average"
        ),
        hourly_timestamp_semantics=None if subhourly else "hour_start",
        expected_frequency_seconds=120 if subhourly else 3600,
        measurement_duration_seconds=120 if subhourly else 3600,
        source_aggregation_duration_seconds=120 if subhourly else 3600,
        measurement_timestamp_semantics=(
            "provider_received_at" if subhourly else "interval_end"
        ),
        measurement_metadata_status="provider_documented",
        measurement_metadata_managed_by="qc_acceptance_fixture",
    )
    session.add(sensor)
    session.flush()
    return device, sensor


def _max_rule(session, sensor, unit, maximum, action):
    rule = models.QCRule(
        check_code="max_value",
        sensor_id=sensor.sensor_id,
        enabled_override=True,
        failure_action_override=action,
        settings={"max": maximum},
        policy_unit_id=unit.unit_id,
    )
    session.add(rule)
    session.flush()
    return rule


def _ingest(session, device, sensor, value, observed_at):
    measurement = models.Measurement(
        sensor_id=sensor.sensor_id,
        value=value,
        observed_at=observed_at,
    )
    result = upsert_measurement_with_policy_detailed(
        session, measurement, device=device, sensor=sensor
    )
    session.flush()
    assert result.action == "insert"
    return measurement


@pytest.mark.qc_acceptance(
    id="downstream-aggregation-validity",
    source="PurpleAir-shaped two-minute sensor",
    parameter="pm25",
    qc_layer="sensor_override",
    expected="Invalid values are excluded before aggregation while flag-only values remain included",
)
def test_aggregation_excludes_invalid_and_includes_flag_only_measurements(
    acceptance_session_factory, acceptance_evidence
):
    Session = acceptance_session_factory
    with Session() as session:
        units, parameters, periods = ensure_catalog(session)
        source = ensure_source(session, "purpleair", "PurpleAir")
        device, sensor = _sensor(
            session,
            source,
            parameters["pm25"],
            units["ug_m3"],
            periods["2m"],
            "Aggregation acceptance sensor",
            subhourly=True,
        )
        rollup = session.scalar(
            select(models.ParameterAggregationRollup).where(
                models.ParameterAggregationRollup.parameter_id
                == parameters["pm25"].parameter_id,
                models.ParameterAggregationRollup.from_aggregation_period_id
                == periods["2m"].aggregation_period_id,
                models.ParameterAggregationRollup.to_aggregation_period_id
                == periods["1h"].aggregation_period_id,
            )
        )
        if rollup is None:
            session.add(models.ParameterAggregationRollup(
                parameter_id=parameters["pm25"].parameter_id,
                from_aggregation_period_id=periods["2m"].aggregation_period_id,
                to_aggregation_period_id=periods["1h"].aggregation_period_id,
            ))
        aggregation_rule = session.scalar(
            select(models.ParameterAggregationRule).where(
                models.ParameterAggregationRule.parameter_id
                == parameters["pm25"].parameter_id,
                models.ParameterAggregationRule.aggregation_period_id
                == periods["1h"].aggregation_period_id,
            )
        )
        if aggregation_rule is None:
            aggregation_rule = models.ParameterAggregationRule(
                parameter_id=parameters["pm25"].parameter_id,
                aggregation_period_id=periods["1h"].aggregation_period_id,
            )
            session.add(aggregation_rule)
        aggregation_rule.truncation_method = "truncate"
        aggregation_rule.truncation_precision = 1
        aggregation_rule.active = True
        rule = _max_rule(
            session, sensor, units["ug_m3"], maximum=50.0, action="mark_invalid"
        )
        session.commit()

        start = datetime(2026, 8, 19, 17, tzinfo=timezone.utc)
        valid_one = _ingest(session, device, sensor, 10.0, start + timedelta(minutes=2))
        invalid = _ingest(session, device, sensor, 100.0, start + timedelta(minutes=4))
        valid_two = _ingest(session, device, sensor, 20.0, start + timedelta(minutes=6))
        rule.failure_action_override = "flag_for_review"
        session.flush()
        flag_only = _ingest(session, device, sensor, 100.0, start + timedelta(minutes=8))
        session.commit()

        valid_only = execute_measurement_aggregation(
            session,
            sensor_ids=[sensor.sensor_id],
            parameter_code="pm25",
            native_aggregation_code="2m",
            result_aggregation_code="1h",
            since=start,
            until=start + timedelta(hours=1),
        )[0]
        diagnostic = execute_measurement_aggregation(
            session,
            sensor_ids=[sensor.sensor_id],
            parameter_code="pm25",
            native_aggregation_code="2m",
            result_aggregation_code="1h",
            since=start,
            until=start + timedelta(hours=1),
            include_invalid=True,
        )[0]
        assert valid_one.is_valid and valid_two.is_valid and flag_only.is_valid
        assert invalid.is_valid is False
        assert valid_only.sample_count == 3
        assert valid_only.valid_sample_count == 3
        assert valid_only.invalid_sample_count == 0
        assert valid_only.value == pytest.approx(43.3)
        assert diagnostic.sample_count == 4
        assert diagnostic.valid_sample_count == 3
        assert diagnostic.invalid_sample_count == 1
        assert diagnostic.value == pytest.approx(57.5)
        acceptance_evidence.update(
            {
                "database": session.get_bind().dialect.name,
                "valid_sample_count": valid_only.valid_sample_count,
                "excluded_measurement_id": invalid.measurement_id,
                "included_flag_only_measurement_id": flag_only.measurement_id,
            }
        )


@pytest.mark.qc_acceptance(
    id="downstream-pm-completeness-aqi",
    source="PurpleAir-shaped two-minute streams",
    parameter="pm25,pm10",
    qc_layer="sensor_override",
    expected="QC-invalid samples reduce valid hourly positions; flag-only failures remain eligible in shared U.S./European PM foundations",
)
def test_qc_validity_controls_pm_completeness_and_european_aqi(
    acceptance_session_factory, acceptance_evidence
):
    Session = acceptance_session_factory
    with Session() as session:
        units, parameters, periods = ensure_catalog(session)
        source = ensure_source(session, "purpleair", "PurpleAir")
        streams = {}
        for parameter_code in ("pm25", "pm10"):
            device, sensor = _sensor(
                session,
                source,
                parameters[parameter_code],
                units["ug_m3"],
                periods["2m"],
                f"{parameter_code} completeness sensor",
                subhourly=True,
            )
            rule = _max_rule(
                session,
                sensor,
                units["ug_m3"],
                maximum=50.0,
                action="mark_invalid",
            )
            streams[parameter_code] = (device, sensor, rule)
        # EEA presentation applies the existing parameter formatting rule after
        # the shared provider-neutral completeness decision.
        aggregation_rule = session.scalar(
            select(models.ParameterAggregationRule).where(
                models.ParameterAggregationRule.parameter_id
                == parameters["pm25"].parameter_id,
                models.ParameterAggregationRule.aggregation_period_id
                == periods["1h"].aggregation_period_id,
            )
        )
        if aggregation_rule is None:
            aggregation_rule = models.ParameterAggregationRule(
                parameter_id=parameters["pm25"].parameter_id,
                aggregation_period_id=periods["1h"].aggregation_period_id,
            )
            session.add(aggregation_rule)
        aggregation_rule.truncation_method = "truncate"
        aggregation_rule.truncation_precision = 1
        aggregation_rule.active = True
        session.commit()

        invalid_hour = datetime(2026, 8, 19, 18, tzinfo=timezone.utc)
        flag_hour = invalid_hour + timedelta(hours=1)
        for parameter_code, (device, sensor, rule) in streams.items():
            for position in range(30):
                _ingest(
                    session,
                    device,
                    sensor,
                    100.0 if position < 8 else 10.0,
                    invalid_hour + timedelta(seconds=(position + 1) * 120),
                )
            rule.failure_action_override = "flag_for_review"
            session.flush()
            for position in range(30):
                _ingest(
                    session,
                    device,
                    sensor,
                    100.0 if position < 8 else 10.0,
                    flag_hour + timedelta(seconds=(position + 1) * 120),
                )
        session.commit()

        completeness = {}
        for parameter_code, (_, sensor, _) in streams.items():
            raw = retrieve_raw_measurement_inputs(
                session,
                parameter_codes=(parameter_code,),
                start_utc=invalid_hour,
                end_utc=flag_hour + timedelta(hours=1),
                include_end=True,
                sensor_ids=(sensor.sensor_id,),
            )
            completeness[parameter_code] = {}
            for hour in (invalid_hour, flag_hour):
                observations = select_raw_observations_for_hour(
                    raw,
                    interval_started_at=hour,
                    timestamp_semantics="provider_received_at",
                )
                result = construct_subhourly_pm_hour(
                    observations,
                    interval_started_at=hour,
                    parameter_code=parameter_code,
                    input_unit="ug_m3",
                    expected_frequency_seconds=120,
                    measurement_duration_seconds=120,
                    source_aggregation_duration_seconds=120,
                    timestamp_semantics="provider_received_at",
                )
                completeness[parameter_code][hour] = result
                if hour == invalid_hour:
                    assert result.is_eligible is False
                    assert result.valid_observation_count == 22
                    assert len(result.rejected_measurement_ids) == 8
                else:
                    assert result.is_eligible is True
                    assert result.valid_observation_count == 30
                    assert result.rejected_measurement_ids == ()

        european = calculate_eea_european_index_history(
            session,
            start_utc=invalid_hour,
            end_utc=flag_hour + timedelta(hours=1),
            current_time_utc=flag_hour + timedelta(days=1),
        )
        first_result = next(
            result
            for result in european
            if result.observed_at == invalid_hour
            and any(
                provenance.parameter_code == "pm25"
                for provenance in result.sensor_provenance
            )
        )
        second_result = next(
            result
            for result in european
            if result.observed_at == flag_hour
            and any(
                provenance.parameter_code == "pm25"
                for provenance in result.sensor_provenance
            )
        )
        first_pm25 = next(
            provenance
            for provenance in first_result.sensor_provenance
            if provenance.parameter_code == "pm25"
        )
        second_pm25 = next(
            provenance
            for provenance in second_result.sensor_provenance
            if provenance.parameter_code == "pm25"
        )
        assert first_pm25.valid_observation_count == 22
        assert first_pm25.eligible_sensor_ids == ()
        assert second_pm25.valid_observation_count == 30
        assert second_pm25.eligible_sensor_ids
        acceptance_evidence.update(
            {
                "database": session.get_bind().dialect.name,
                "invalid_hour_valid_positions": 22,
                "flag_hour_valid_positions": 30,
                "parameters": ["pm25", "pm10"],
                "european_shared_path_verified": True,
            }
        )


@pytest.mark.qc_acceptance(
    id="downstream-ozone-validity",
    source="OpenAQ-shaped provider-hourly ozone stream",
    parameter="o3",
    qc_layer="sensor_override",
    expected="QC-invalid ozone is ineligible while an equivalent flag-only failure remains eligible",
)
def test_qc_invalid_ozone_cannot_contribute_to_hourly_aqi_input(
    acceptance_session_factory, acceptance_evidence
):
    Session = acceptance_session_factory
    with Session() as session:
        units, parameters, periods = ensure_catalog(session)
        source = ensure_source(session, "openaq", "OpenAQ")
        device, sensor = _sensor(
            session,
            source,
            parameters["o3"],
            units["ppm"],
            periods["1h"],
            "Ozone acceptance sensor",
        )
        rule = _max_rule(
            session, sensor, units["ppm"], maximum=0.05, action="mark_invalid"
        )
        session.commit()
        invalid_hour = datetime(2026, 8, 19, 20, tzinfo=timezone.utc)
        invalid = _ingest(session, device, sensor, 0.08, invalid_hour)
        rule.failure_action_override = "flag_for_review"
        session.flush()
        flag_only = _ingest(
            session, device, sensor, 0.08, invalid_hour + timedelta(hours=1)
        )
        session.commit()

        invalid_input = construct_provider_hourly_ozone_hour(
            (
                RawHourlyObservation(
                    measurement_id=invalid.measurement_id,
                    observed_at=invalid.observed_at,
                    concentration=invalid.value,
                    is_valid=invalid.is_valid,
                ),
            ),
            interval_started_at=invalid_hour,
            input_unit="ppm",
            timestamp_semantics="hour_start",
        )
        flag_input = construct_provider_hourly_ozone_hour(
            (
                RawHourlyObservation(
                    measurement_id=flag_only.measurement_id,
                    observed_at=flag_only.observed_at,
                    concentration=flag_only.value,
                    is_valid=flag_only.is_valid,
                ),
            ),
            interval_started_at=invalid_hour + timedelta(hours=1),
            input_unit="ppm",
            timestamp_semantics="hour_start",
        )
        assert invalid.is_valid is False
        assert invalid_input.is_eligible is False
        assert invalid_input.valid_observation_count == 0
        assert invalid_input.rejected_measurement_ids == (invalid.measurement_id,)
        assert flag_only.is_valid is True
        assert flag_input.is_eligible is True
        assert flag_input.valid_observation_count == 1
        assert flag_input.measurement_ids == (flag_only.measurement_id,)
        acceptance_evidence.update(
            {
                "database": session.get_bind().dialect.name,
                "rejected_invalid_measurement_id": invalid.measurement_id,
                "accepted_flag_only_measurement_id": flag_only.measurement_id,
            }
        )
