from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from db import SessionLocal
from models import (
    AggregationPeriod,
    Device,
    ExternalAPI,
    Measurement,
    Parameter,
    ParameterAggregationRollup,
    ParameterAggregationRule,
    Sensor,
    Unit,
)
from services.measurement_aggregation import (
    MeasurementAggregationError,
    execute_measurement_aggregation,
    execute_latest_measurements,
    load_measurement_aggregation_capabilities,
    resolve_measurement_aggregation,
)


def _period(session, code: str, minutes: int) -> AggregationPeriod:
    period = session.scalar(select(AggregationPeriod).where(AggregationPeriod.code == code))
    if period is None:
        period = AggregationPeriod(
            code=code,
            display_name=code,
            duration_minutes=minutes,
            is_rolling=False,
        )
        session.add(period)
        session.flush()
    else:
        period.duration_minutes = minutes
        period.is_rolling = False
    return period


def _add_edge(session, parameter: Parameter, source: AggregationPeriod, target: AggregationPeriod) -> None:
    session.add(
        ParameterAggregationRollup(
            parameter_id=parameter.parameter_id,
            from_aggregation_period_id=source.aggregation_period_id,
            to_aggregation_period_id=target.aggregation_period_id,
        )
    )


def _scenario():
    session = SessionLocal()
    suffix = uuid4().hex[:12]
    unit = Unit(code=f"unit_{suffix}", symbol="µg/m³", name="Test concentration")
    source_api = ExternalAPI(name=f"source-{suffix}", base_url="https://example.com", params={})
    session.add_all([unit, source_api])
    session.flush()
    parameter = Parameter(
        code=f"phase2h_{suffix}",
        display_name="Phase 2H parameter",
        default_unit_id=unit.unit_id,
    )
    device = Device(name=f"device-{suffix}", external_api_id=source_api.external_api_id)
    session.add_all([parameter, device])
    session.flush()
    period_2m = _period(session, f"2m_{suffix}", 2)
    period_1h = _period(session, f"1h_{suffix}", 60)
    period_24h = _period(session, f"24h_{suffix}", 1440)
    _add_edge(session, parameter, period_2m, period_1h)
    _add_edge(session, parameter, period_1h, period_24h)
    sensor = Sensor(
        device_id=device.device_id,
        parameter_id=parameter.parameter_id,
        unit_id=unit.unit_id,
        aggregation_period_id=period_2m.aggregation_period_id,
    )
    session.add(sensor)
    session.flush()
    return session, parameter, sensor, period_2m, period_1h, period_24h


def test_chained_daily_rollup_averages_hourly_results_before_final_formatting():
    session, parameter, sensor, period_2m, _, period_24h = _scenario()
    try:
        session.add(
            ParameterAggregationRule(
                parameter_id=parameter.parameter_id,
                aggregation_period_id=period_24h.aggregation_period_id,
                rounding_method="round",
                rounding_precision=1,
                truncation_method="none",
                active=True,
            )
        )
        start = datetime(2026, 8, 1, tzinfo=timezone.utc)
        session.add_all(
            [
                Measurement(sensor_id=sensor.sensor_id, value=0, observed_at=start, is_valid=True),
                Measurement(sensor_id=sensor.sensor_id, value=10, observed_at=start + timedelta(minutes=2), is_valid=True),
                Measurement(sensor_id=sensor.sensor_id, value=100, observed_at=start + timedelta(hours=1), is_valid=True),
            ]
        )
        session.flush()

        result = execute_measurement_aggregation(
            session,
            sensor_ids=[sensor.sensor_id],
            parameter_code=parameter.code,
            native_aggregation_code=period_2m.code,
            result_aggregation_code=period_24h.code,
            since=start,
            until=start + timedelta(days=1),
        )

        assert len(result) == 1
        assert result[0].value == 52.5
        assert result[0].sample_count == 3
        assert result[0].formatting_status == "configured"
        assert resolve_measurement_aggregation(
            session, parameter.code, period_2m.code, period_24h.code
        ).capability_kind == "chained_rollup"
    finally:
        session.rollback()
        session.close()


def test_rolling_averages_are_latest_only_and_empty_input_is_not_a_transport_error():
    session, parameter, sensor, native, _, rolling = _scenario()
    try:
        rolling.is_rolling = True
        session.flush()
        options = dict(sensor_ids=[sensor.sensor_id], parameter_code=parameter.code,
                       native_aggregation_code=native.code, result_aggregation_code=rolling.code)
        with pytest.raises(MeasurementAggregationError) as error:
            execute_measurement_aggregation(session, **options, latest_only=False)
        assert error.value.reason == "rolling_history_not_supported"
        assert execute_measurement_aggregation(session, **options, latest_only=True) == []
        capability = load_measurement_aggregation_capabilities(session, parameter_code=parameter.code)[0]
        rolling_option = next(option for option in capability["supported_aggregations"]
                              if option["result_aggregation_code"] == rolling.code)
        assert rolling_option["supports_latest"] is True
        assert rolling_option["supports_history"] is False
    finally:
        session.rollback()
        session.close()


def test_direct_edge_takes_precedence_and_uses_direct_sample_average():
    session, parameter, sensor, period_2m, _, period_24h = _scenario()
    try:
        _add_edge(session, parameter, period_2m, period_24h)
        start = datetime(2026, 8, 2, tzinfo=timezone.utc)
        session.add_all(
            [
                Measurement(sensor_id=sensor.sensor_id, value=0, observed_at=start, is_valid=True),
                Measurement(sensor_id=sensor.sensor_id, value=10, observed_at=start + timedelta(minutes=2), is_valid=True),
                Measurement(sensor_id=sensor.sensor_id, value=100, observed_at=start + timedelta(hours=1), is_valid=True),
            ]
        )
        session.flush()

        resolved = resolve_measurement_aggregation(
            session, parameter.code, period_2m.code, period_24h.code
        )
        result = execute_measurement_aggregation(
            session,
            sensor_ids=[sensor.sensor_id],
            parameter_code=parameter.code,
            native_aggregation_code=period_2m.code,
            result_aggregation_code=period_24h.code,
            since=start,
            until=start + timedelta(days=1),
        )

        assert resolved.capability_kind == "direct_rollup"
        assert result[0].value == pytest.approx(110 / 3)
        assert result[0].formatting_status == "not_configured"
    finally:
        session.rollback()
        session.close()


def test_unknown_native_is_raw_only_and_capability_output_is_backend_resolved():
    session, parameter, sensor, period_2m, period_1h, period_24h = _scenario()
    try:
        sensor.aggregation_period_id = None
        session.flush()
        raw = resolve_measurement_aggregation(session, parameter.code, None, "raw")
        assert raw.result_aggregation_code == "raw"
        with pytest.raises(MeasurementAggregationError) as exc_info:
            resolve_measurement_aggregation(session, parameter.code, None, period_1h.code)
        assert exc_info.value.reason == "unknown_native_aggregation"

        capabilities = load_measurement_aggregation_capabilities(
            session, parameter_code=parameter.code
        )
        assert capabilities == [
            {
                "parameter_code": parameter.code,
                "native_aggregation_code": None,
                "native_status": "unknown",
                "supported_aggregations": [
                    {
                        "result_aggregation_code": "raw",
                        "display_name": "Raw/latest (native period unknown)",
                        "duration_minutes": None,
                        "is_rolling": False,
                        "capability_kind": "native",
                        "rollup_path": ["raw"],
                        "supports_latest": True,
                        "supports_history": True,
                        "formatting_status": "not_configured",
                        "display_precision": None,
                    }
                ],
                "diagnostics": [],
            }
        ]
    finally:
        session.rollback()
        session.close()


def test_ambiguous_and_invalid_rollup_configuration_is_explicit():
    session, parameter, sensor, period_2m, period_1h, period_24h = _scenario()
    try:
        suffix = uuid4().hex[:12]
        alternate_hour = _period(session, f"45m_{suffix}", 45)
        _add_edge(session, parameter, period_2m, alternate_hour)
        _add_edge(session, parameter, alternate_hour, period_24h)
        session.flush()

        with pytest.raises(MeasurementAggregationError) as ambiguous:
            resolve_measurement_aggregation(
                session, parameter.code, period_2m.code, period_24h.code
            )
        assert ambiguous.value.reason == "ambiguous_rollup_path"

        _add_edge(session, parameter, period_24h, period_1h)
        session.flush()
        with pytest.raises(MeasurementAggregationError) as invalid_duration:
            resolve_measurement_aggregation(
                session, parameter.code, period_24h.code, period_1h.code
            )
        assert invalid_duration.value.reason == "invalid_rollup_duration"
    finally:
        session.rollback()
        session.close()


def test_cycle_is_reported_when_no_valid_path_reaches_the_requested_period():
    session, parameter, sensor, period_2m, period_1h, _ = _scenario()
    try:
        suffix = uuid4().hex[:12]
        unreachable_target = _period(session, f"8h_{suffix}", 480)
        _add_edge(session, parameter, period_1h, period_2m)
        session.flush()

        with pytest.raises(MeasurementAggregationError) as cycle:
            resolve_measurement_aggregation(
                session, parameter.code, period_2m.code, unreachable_target.code
            )
        assert cycle.value.reason == "cyclic_rollup_path"

        capabilities = load_measurement_aggregation_capabilities(
            session, parameter_code=parameter.code
        )
        diagnostics = capabilities[0]["diagnostics"]
        assert any(item["reason"] == "cyclic_rollup_path" for item in diagnostics)
    finally:
        session.rollback()
        session.close()


def test_invalid_measurements_are_filtered_before_aggregation_and_counted_when_included():
    session, parameter, sensor, period_2m, period_1h, _ = _scenario()
    try:
        start = datetime(2026, 8, 3, tzinfo=timezone.utc)
        session.add_all(
            [
                Measurement(sensor_id=sensor.sensor_id, value=10, observed_at=start, is_valid=True),
                Measurement(
                    sensor_id=sensor.sensor_id,
                    value=100,
                    observed_at=start + timedelta(minutes=2),
                    is_valid=False,
                ),
            ]
        )
        session.flush()

        valid_only = execute_measurement_aggregation(
            session,
            sensor_ids=[sensor.sensor_id],
            parameter_code=parameter.code,
            native_aggregation_code=period_2m.code,
            result_aggregation_code=period_1h.code,
            since=start,
            until=start + timedelta(hours=1),
        )[0]
        with_invalid = execute_measurement_aggregation(
            session,
            sensor_ids=[sensor.sensor_id],
            parameter_code=parameter.code,
            native_aggregation_code=period_2m.code,
            result_aggregation_code=period_1h.code,
            since=start,
            until=start + timedelta(hours=1),
            include_invalid=True,
        )[0]

        assert valid_only.value == 10
        assert valid_only.sample_count == 1
        assert with_invalid.value == 55
        assert with_invalid.sample_count == 2
        assert with_invalid.valid_sample_count == 1
        assert with_invalid.invalid_sample_count == 1
    finally:
        session.rollback()
        session.close()


def test_native_interval_end_metadata_places_interval_before_observed_timestamp():
    session, parameter, sensor, period_2m, _, _ = _scenario()
    try:
        sensor.measurement_duration_seconds = 120
        sensor.measurement_timestamp_semantics = "interval_end"
        observed_at = datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc)
        session.add(
            Measurement(
                sensor_id=sensor.sensor_id,
                value=12.5,
                observed_at=observed_at,
                is_valid=True,
            )
        )
        session.flush()

        point = execute_measurement_aggregation(
            session,
            sensor_ids=[sensor.sensor_id],
            parameter_code=parameter.code,
            native_aggregation_code=period_2m.code,
            result_aggregation_code=period_2m.code,
        )[0]

        assert point.observed_at == observed_at
        assert point.interval_started_at == observed_at - timedelta(minutes=2)
        assert point.interval_ended_at == observed_at
    finally:
        session.rollback()
        session.close()


def test_native_non_interval_timestamps_do_not_fabricate_intervals():
    for timestamp_semantics in (
        "observation_instant",
        "provider_received_at",
        "unknown",
        None,
    ):
        session, parameter, sensor, period_2m, _, _ = _scenario()
        try:
            sensor.measurement_duration_seconds = 120
            sensor.measurement_timestamp_semantics = timestamp_semantics
            observed_at = datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc)
            session.add(
                Measurement(
                    sensor_id=sensor.sensor_id,
                    value=12.5,
                    observed_at=observed_at,
                    is_valid=True,
                )
            )
            session.flush()

            point = execute_measurement_aggregation(
                session,
                sensor_ids=[sensor.sensor_id],
                parameter_code=parameter.code,
                native_aggregation_code=period_2m.code,
                result_aggregation_code=period_2m.code,
            )[0]

            assert point.observed_at == observed_at
            assert point.interval_started_at is None
            assert point.interval_ended_at is None
        finally:
            session.rollback()
            session.close()


def test_fixed_eight_hour_and_daily_buckets_align_to_utc_epoch_boundaries():
    session, parameter, sensor, period_2m, _, period_24h = _scenario()
    try:
        suffix = uuid4().hex[:12]
        period_8h = _period(session, f"8h_{suffix}", 480)
        _add_edge(session, parameter, period_2m, period_8h)
        start = datetime(2026, 8, 4, tzinfo=timezone.utc)
        session.add_all(
            [
                Measurement(sensor_id=sensor.sensor_id, value=1, observed_at=start + timedelta(hours=7, minutes=59), is_valid=True),
                Measurement(sensor_id=sensor.sensor_id, value=3, observed_at=start + timedelta(hours=8), is_valid=True),
                Measurement(sensor_id=sensor.sensor_id, value=5, observed_at=start + timedelta(hours=23, minutes=59), is_valid=True),
                Measurement(sensor_id=sensor.sensor_id, value=7, observed_at=start + timedelta(days=1), is_valid=True),
            ]
        )
        session.flush()

        eight_hour = execute_measurement_aggregation(
            session,
            sensor_ids=[sensor.sensor_id],
            parameter_code=parameter.code,
            native_aggregation_code=period_2m.code,
            result_aggregation_code=period_8h.code,
            since=start,
            until=start + timedelta(days=1),
        )
        daily = execute_measurement_aggregation(
            session,
            sensor_ids=[sensor.sensor_id],
            parameter_code=parameter.code,
            native_aggregation_code=period_2m.code,
            result_aggregation_code=period_24h.code,
            since=start,
            until=start + timedelta(days=1),
        )

        assert [point.observed_at for point in eight_hour] == [
            start,
            start + timedelta(hours=8),
            start + timedelta(hours=16),
            start + timedelta(days=1),
        ]
        assert [point.observed_at for point in daily] == [
            start,
            start + timedelta(days=1),
        ]
        assert all(point.interval_ended_at > point.interval_started_at for point in eight_hour)
    finally:
        session.rollback()
        session.close()


def test_latest_query_count_is_independent_of_sensor_count_within_one_path_group():
    session, parameter, sensor, period_2m, period_1h, _ = _scenario()
    statement_count = 0

    def count_statement(*_args) -> None:
        nonlocal statement_count
        statement_count += 1

    try:
        observed_at = datetime(2026, 8, 5, tzinfo=timezone.utc)
        session.add(
            Measurement(sensor_id=sensor.sensor_id, value=10, observed_at=observed_at, is_valid=True)
        )
        session.flush()
        assert session.bind is not None
        event.listen(session.bind, "before_cursor_execute", count_statement)
        execute_latest_measurements(
            session,
            parameter_code=parameter.code,
            result_aggregation_code=period_1h.code,
        )
        one_sensor_statement_count = statement_count

        event.remove(session.bind, "before_cursor_execute", count_statement)
        second_sensor = Sensor(
            device_id=sensor.device_id,
            parameter_id=parameter.parameter_id,
            unit_id=sensor.unit_id,
            aggregation_period_id=period_2m.aggregation_period_id,
        )
        session.add(second_sensor)
        session.flush()
        session.add(
            Measurement(
                sensor_id=second_sensor.sensor_id,
                value=20,
                observed_at=observed_at,
                is_valid=True,
            )
        )
        session.flush()

        statement_count = 0
        event.listen(session.bind, "before_cursor_execute", count_statement)
        execute_latest_measurements(
            session,
            parameter_code=parameter.code,
            result_aggregation_code=period_1h.code,
        )
        assert statement_count == one_sensor_statement_count
    finally:
        if session.bind is not None:
            try:
                event.remove(session.bind, "before_cursor_execute", count_statement)
            except Exception:
                pass
        session.rollback()
        session.close()


def test_history_query_count_is_independent_of_requested_interval_count():
    session, parameter, sensor, period_2m, period_1h, _ = _scenario()
    statement_count = 0

    def count_statement(*_args) -> None:
        nonlocal statement_count
        statement_count += 1

    try:
        start = datetime(2026, 5, 1, tzinfo=timezone.utc)
        session.add_all(
            [
                Measurement(
                    sensor_id=sensor.sensor_id,
                    value=hour,
                    observed_at=start + timedelta(hours=hour),
                    is_valid=True,
                )
                for hour in range(24 * 30)
            ]
        )
        session.flush()
        assert session.bind is not None

        event.listen(session.bind, "before_cursor_execute", count_statement)
        execute_measurement_aggregation(
            session,
            sensor_ids=[sensor.sensor_id],
            parameter_code=parameter.code,
            native_aggregation_code=period_2m.code,
            result_aggregation_code=period_1h.code,
            since=start,
            until=start + timedelta(days=1),
        )
        one_day_statement_count = statement_count

        statement_count = 0
        execute_measurement_aggregation(
            session,
            sensor_ids=[sensor.sensor_id],
            parameter_code=parameter.code,
            native_aggregation_code=period_2m.code,
            result_aggregation_code=period_1h.code,
            since=start,
            until=start + timedelta(days=30),
        )

        assert statement_count == one_day_statement_count
    finally:
        if session.bind is not None:
            try:
                event.remove(session.bind, "before_cursor_execute", count_statement)
            except Exception:
                pass
        session.rollback()
        session.close()
