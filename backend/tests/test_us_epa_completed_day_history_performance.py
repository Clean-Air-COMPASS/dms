from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import select

from api.routes.air_quality_index import (
    _us_epa_completed_day_history_response,
)
from db import SessionLocal
from models import (
    AggregationPeriod,
    Device,
    ExternalAPI,
    Measurement,
    Parameter,
    Sensor,
    Unit,
)
import services.us_epa_completed_day_service as completed_day_service
from services.air_quality_index.us_epa import get_product
from services.us_epa_completed_day_service import (
    calculate_us_epa_completed_day_history,
)


def _seed_hourly_history(
    session,
    *,
    device_count: int,
    day_count: int,
) -> str:
    source_name = f"history-performance-{uuid4()}"
    external_api = ExternalAPI(
        name=source_name,
        base_url="https://example.com",
        params={},
    )
    session.add(external_api)
    session.flush()
    parameter = session.scalar(select(Parameter).where(Parameter.code == "pm25"))
    unit = session.scalar(select(Unit).where(Unit.code == "ug_m3"))
    hourly = session.scalar(
        select(AggregationPeriod).where(AggregationPeriod.code == "1h")
    )
    first_hour = datetime(2024, 1, 1, 8, tzinfo=timezone.utc)
    for device_index in range(device_count):
        device = Device(
            name=f"performance-device-{device_index}-{uuid4()}",
            external_api_id=external_api.external_api_id,
            timezone="America/Los_Angeles",
        )
        session.add(device)
        session.flush()
        sensor = Sensor(
            device_id=device.device_id,
            parameter_id=parameter.parameter_id,
            unit_id=unit.unit_id,
            aggregation_period_id=hourly.aggregation_period_id,
            hourly_concentration_provenance="provider_reported_hourly_average",
            hourly_timestamp_semantics="hour_start",
            measurement_metadata_status="provider_documented",
            measurement_metadata_managed_by="test_fixture",
        )
        session.add(sensor)
        session.flush()
        for hour_index in range(day_count * 24):
            session.add(
                Measurement(
                    sensor_id=sensor.sensor_id,
                    value=9.1,
                    observed_at=first_hour + timedelta(hours=hour_index),
                    is_valid=True,
                )
            )
    session.flush()
    return source_name


@pytest.mark.parametrize(
    ("device_count", "day_count", "target_seconds"),
    ((1, 30, 1.0), (1, 365, 3.0), (10, 30, 3.0)),
)
def test_summary_history_diagnostic_targets(
    device_count: int,
    day_count: int,
    target_seconds: float,
    monkeypatch,
    record_property,
) -> None:
    session = SessionLocal()
    try:
        source_name = _seed_hourly_history(
            session,
            device_count=device_count,
            day_count=day_count,
        )
        start_date = date(2024, 1, 1)
        end_date = start_date + timedelta(days=day_count - 1)
        retrieval_seconds = 0.0
        retrieval_count = 0
        real_retrieval = completed_day_service.retrieve_raw_measurement_inputs

        def timed_retrieval(*args, **kwargs):
            nonlocal retrieval_count, retrieval_seconds
            retrieval_count += 1
            retrieval_started_at = perf_counter()
            retrieved = real_retrieval(*args, **kwargs)
            retrieval_seconds += perf_counter() - retrieval_started_at
            return retrieved

        monkeypatch.setattr(
            completed_day_service,
            "retrieve_raw_measurement_inputs",
            timed_retrieval,
        )
        service_started_at = perf_counter()
        results = calculate_us_epa_completed_day_history(
            session,
            product_code="us_epa.pm25.completed_day",
            start_local_date=start_date,
            end_local_date=end_date,
            external_api_name=source_name,
            limit=device_count,
            current_time_utc=datetime(2025, 2, 1, tzinfo=timezone.utc),
        )
        service_seconds = perf_counter() - service_started_at
        product = get_product("us_epa.pm25.completed_day")
        assert product is not None
        summary_started_at = perf_counter()
        summary_response = _us_epa_completed_day_history_response(
            results,
            product=product,
            start_local_date=start_date,
            end_local_date=end_date,
            detail="summary",
        )
        summary_payload_size = len(
            summary_response.model_dump_json().encode("utf-8")
        )
        summary_serialization_seconds = perf_counter() - summary_started_at
        full_started_at = perf_counter()
        full_response = _us_epa_completed_day_history_response(
            results,
            product=product,
            start_local_date=start_date,
            end_local_date=end_date,
            detail="full",
        )
        full_payload_size = len(full_response.model_dump_json().encode("utf-8"))
        full_serialization_seconds = perf_counter() - full_started_at
        summary_total_seconds = service_seconds + summary_serialization_seconds

        record_property("measurement_retrieval_count", retrieval_count)
        record_property("measurement_retrieval_seconds", retrieval_seconds)
        record_property(
            "in_memory_calculation_seconds",
            service_seconds - retrieval_seconds,
        )
        record_property(
            "summary_serialization_seconds",
            summary_serialization_seconds,
        )
        record_property(
            "full_serialization_seconds",
            full_serialization_seconds,
        )
        record_property("summary_payload_bytes", summary_payload_size)
        record_property("full_payload_bytes", full_payload_size)

        assert len(results) == device_count * day_count
        assert retrieval_count == 1
        assert summary_payload_size > 0
        assert full_payload_size > summary_payload_size
        assert summary_total_seconds < target_seconds
    finally:
        session.rollback()
        session.close()
