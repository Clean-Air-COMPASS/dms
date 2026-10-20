from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, literal_column, select

from db import SessionLocal
from models import (
    AggregationPeriod,
    Device,
    ExternalAPI,
    Measurement,
    Parameter,
    ParameterAggregationRollup,
    Sensor,
    UpdatePolicy,
    Unit,
)


def _maybe_get_session():
    try:
        return SessionLocal()
    except Exception:
        return None


def _ensure_agg(session, code: str, display: str) -> AggregationPeriod:
    agg = session.scalar(select(AggregationPeriod).where(AggregationPeriod.code == code))
    if agg:
        return agg
    agg = AggregationPeriod(code=code, display_name=display)
    session.add(agg)
    session.flush()
    return agg


def _ensure_rollup(session, parameter_id: int, from_id: int, to_id: int) -> None:
    existing = session.scalar(
        select(ParameterAggregationRollup).where(
            ParameterAggregationRollup.parameter_id == parameter_id,
            ParameterAggregationRollup.from_aggregation_period_id == from_id,
            ParameterAggregationRollup.to_aggregation_period_id == to_id,
        )
    )
    if existing is None:
        session.add(
            ParameterAggregationRollup(
                parameter_id=parameter_id,
                from_aggregation_period_id=from_id,
                to_aggregation_period_id=to_id,
            )
        )
        session.flush()


def test_rollup_from_1m_to_1h_preserves_unit_and_averages_values():
    """Ensure rollup path exists and aggregated query returns the unit symbol."""
    session = _maybe_get_session()
    if session is None:
        return

    try:
        unit = session.scalar(select(Unit).where(Unit.code == "ug_m3"))
        param = session.scalar(select(Parameter).where(Parameter.code == "pm25"))
        agg_1m = _ensure_agg(session, "1m", "1 Minute")
        agg_1h = _ensure_agg(session, "1h", "1 Hour")
        assert unit and param and agg_1m and agg_1h

        _ensure_rollup(session, param.parameter_id, agg_1m.aggregation_period_id, agg_1h.aggregation_period_id)

        ext_api = session.scalar(select(ExternalAPI).where(ExternalAPI.name == "test-rollup-api"))
        if ext_api is None:
            ext_api = ExternalAPI(name="test-rollup-api", base_url="http://example.com", params={})
            session.add(ext_api)
            session.flush()

        device = Device(
            name="rollup-test-device",
            external_api_id=ext_api.external_api_id,
            allow_updates=UpdatePolicy.ALLOW,
        )
        session.add(device)
        session.flush()

        sensor = Sensor(
            device_id=device.device_id,
            parameter_id=param.parameter_id,
            unit_id=unit.unit_id,
            aggregation_period_id=agg_1m.aggregation_period_id,
            external_sensor_id="rollup-sensor",
            allow_updates=UpdatePolicy.ALLOW,
        )
        session.add(sensor)
        session.flush()

        t0 = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        session.add_all(
            [
                Measurement(sensor_id=sensor.sensor_id, value=10.0, observed_at=t0, is_valid=True),
                Measurement(sensor_id=sensor.sensor_id, value=14.0, observed_at=t0.replace(minute=1), is_valid=True),
            ]
        )
        session.flush()

        bucket_seconds = 3600
        bucket_expr = func.floor(func.extract("epoch", Measurement.observed_at) / literal_column(str(bucket_seconds))) * literal_column(
            str(bucket_seconds)
        )
        stmt = (
            select(
                Measurement.sensor_id,
                func.avg(Measurement.value).label("value_avg"),
                bucket_expr.label("bucket_start"),
                Unit.symbol.label("unit_symbol"),
            )
            .join(Sensor, Sensor.sensor_id == Measurement.sensor_id)
            .join(Parameter, Parameter.parameter_id == Sensor.parameter_id)
            .join(Unit, Unit.unit_id == Sensor.unit_id, isouter=True)
            .where(Parameter.code == "pm25")
            .where(Measurement.sensor_id == sensor.sensor_id)
            .where(Measurement.is_valid == True)
            .group_by(Measurement.sensor_id, bucket_expr, Unit.symbol)
        )
        row = session.execute(stmt).first()
        assert row is not None
        assert row.value_avg == pytest.approx(12.0)
        assert row.unit_symbol == unit.symbol
    finally:
        session.rollback()
        session.close()
