from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes import air_quality_index
from db import get_session
from models import Device, ExternalAPI


UTC = timezone.utc


class FakeSession:
    def __init__(self, device: Device):
        self.device = device

    def get(self, model, device_id: int):
        if model is Device and device_id > 0:
            if device_id == self.device.device_id:
                return self.device
            device = Device(
                device_id=device_id,
                name=f"Analytics test device {device_id}",
                external_api_id=1,
                timezone="UTC",
            )
            device.external_api = self.device.external_api
            return device
        return None


@pytest.fixture()
def analytics_client(monkeypatch):
    source = ExternalAPI(name="Analytics test source", params={})
    device = Device(
        device_id=71,
        name="Analytics test device",
        friendly_name="Test Device",
        external_api_id=1,
        timezone="UTC",
    )
    device.external_api = source
    fake_session = FakeSession(device)

    def override_session():
        yield fake_session

    def fake_series_out(
        _session,
        *,
        requested_series,
        standard,
        product,
        device,
        range_started_at,
        range_ended_at,
        hourly_result_outs=None,
    ):
        return air_quality_index.AirQualityIndexAnalyticsSeriesOut(
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
            source_name=device.external_api.name,
            points=[],
        )

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(
        air_quality_index,
        "_analytics_series_out",
        fake_series_out,
    )
    monkeypatch.setattr(
        air_quality_index,
        "_hourly_analytics_result_outs",
        lambda *args, **kwargs: [],
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


def _payload(*series: dict, days: int = 1) -> dict:
    range_started_at = datetime(2026, 1, 1, tzinfo=UTC)
    return {
        "range_started_at": range_started_at.isoformat(),
        "range_ended_at": (range_started_at + timedelta(days=days)).isoformat(),
        "series": list(series),
    }


def test_batch_history_deduplicates_identical_series(analytics_client) -> None:
    selected = {
        "standard_code": "us_epa",
        "product_code": "us_epa.pm25.nowcast",
        "device_id": 71,
    }
    response = analytics_client.post(
        "/air-quality-index/analytics-history",
        json=_payload(selected, selected),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requested_series_count"] == 2
    assert body["returned_series_count"] == 1
    assert body["series"][0]["history_interval"] == "utc_hour"


def test_batch_history_accepts_mixed_numeric_and_categorical_series(
    analytics_client,
) -> None:
    response = analytics_client.post(
        "/air-quality-index/analytics-history",
        json=_payload(
            {
                "standard_code": "us_epa",
                "product_code": "us_epa.pm25.nowcast",
                "device_id": 71,
            },
            {
                "standard_code": "eea_european",
                "product_code": "eea_european.overall.hourly",
                "device_id": 71,
            },
        ),
    )

    assert response.status_code == 200
    assert [
        series["result_kind"] for series in response.json()["series"]
    ] == ["numeric", "categorical"]


def test_batch_history_groups_devices_sharing_one_product(
    analytics_client,
    monkeypatch,
) -> None:
    grouped_calls = []

    def grouped_results(*args, **kwargs):
        grouped_calls.append(kwargs)
        return []

    monkeypatch.setattr(
        air_quality_index,
        "_hourly_analytics_result_outs",
        grouped_results,
    )
    response = analytics_client.post(
        "/air-quality-index/analytics-history",
        json=_payload(
            {
                "standard_code": "us_epa",
                "product_code": "us_epa.pm25.nowcast",
                "device_id": 71,
            },
            {
                "standard_code": "us_epa",
                "product_code": "us_epa.pm25.nowcast",
                "device_id": 72,
            },
        ),
    )

    assert response.status_code == 200
    assert len(grouped_calls) == 1
    assert grouped_calls[0]["device_ids"] == [71, 72]


def test_batch_history_rejects_empty_and_more_than_six_series(
    analytics_client,
) -> None:
    assert analytics_client.post(
        "/air-quality-index/analytics-history",
        json=_payload(),
    ).status_code == 422
    selected = {
        "standard_code": "us_epa",
        "product_code": "us_epa.pm25.nowcast",
        "device_id": 71,
    }
    assert analytics_client.post(
        "/air-quality-index/analytics-history",
        json=_payload(*([selected] * 7)),
    ).status_code == 422


def test_batch_history_rejects_unknown_product_and_reversed_range(
    analytics_client,
) -> None:
    unknown_response = analytics_client.post(
        "/air-quality-index/analytics-history",
        json=_payload(
            {
                "standard_code": "us_epa",
                "product_code": "us_epa.unknown",
                "device_id": 71,
            }
        ),
    )
    assert unknown_response.status_code == 400
    selected = {
        "standard_code": "us_epa",
        "product_code": "us_epa.pm25.nowcast",
        "device_id": 71,
    }
    reversed_payload = _payload(selected)
    reversed_payload["range_started_at"], reversed_payload["range_ended_at"] = (
        reversed_payload["range_ended_at"],
        reversed_payload["range_started_at"],
    )
    assert analytics_client.post(
        "/air-quality-index/analytics-history",
        json=reversed_payload,
    ).status_code == 400


def test_batch_history_rejects_more_than_one_year_for_mixed_series(
    analytics_client,
) -> None:
    response = analytics_client.post(
        "/air-quality-index/analytics-history",
        json=_payload(
            {
                "standard_code": "us_epa",
                "product_code": "us_epa.pm25.completed_day",
                "device_id": 71,
            },
            {
                "standard_code": "eea_european",
                "product_code": "eea_european.pm25.hourly",
                "device_id": 71,
            },
            days=367,
        ),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "aqi_history_range_exceeded"
    assert response.json()["detail"]["error_context"]["maximum_days"] == 366


@pytest.mark.parametrize("days", [278, 366])
@pytest.mark.parametrize("standard, product", [
    ("us_epa", "us_epa.pm25.nowcast"),
    ("eea_european", "eea_european.pm25.hourly"),
])
def test_analytics_accepts_long_hourly_ranges(analytics_client, days, standard, product):
    response = analytics_client.post(
        "/air-quality-index/analytics-history",
        json=_payload({"standard_code": standard, "product_code": product, "device_id": 71}, days=days),
    )
    assert response.status_code == 200, response.text
    assert response.json()["maximum_hourly_interval_count"] == 366 * 24


def test_long_hourly_retrieval_overlaps_batches_and_keeps_unavailable_results(monkeypatch):
    from types import SimpleNamespace

    start = datetime(2026, 1, 1, 0, 30, tzinfo=UTC)
    end = start + timedelta(days=278)
    calls = []
    shared_hour = start + timedelta(days=90) - timedelta(hours=1)
    valid = SimpleNamespace(device_id=71, observed_at=start, calculation_status="calculated")
    unavailable = SimpleNamespace(device_id=71, observed_at=shared_hour, calculation_status="unavailable")

    def retrieve(_session, **kwargs):
        calls.append((kwargs["range_started_at"], kwargs["range_ended_at"]))
        return [valid, unavailable]

    monkeypatch.setattr(air_quality_index, "_hourly_analytics_result_outs", retrieve)
    _standard, product = air_quality_index._analytics_product("us_epa", "us_epa.pm25.nowcast")
    results = air_quality_index._bounded_hourly_analytics_result_outs(
        None, standard_code="us_epa", product=product, device_ids=[71],
        range_started_at=start, range_ended_at=end,
    )
    assert len(calls) == 4
    assert calls[0][0] == start and calls[-1][1] == end
    assert all(batch_end - batch_start <= timedelta(days=90) for batch_start, batch_end in calls)
    assert all(calls[index][0] == calls[index - 1][1] - timedelta(hours=1) for index in range(1, len(calls)))
    assert results == [valid, unavailable]


def test_completed_day_series_uses_completed_day_history_adapter(monkeypatch) -> None:
    source = ExternalAPI(name="Analytics test source", params={})
    device = Device(
        device_id=71,
        name="Analytics test device",
        external_api_id=1,
        timezone="UTC",
    )
    device.external_api = source
    standard = air_quality_index.US_EPA_STANDARD
    product = next(
        product
        for product in standard.products
        if product.product_code == "us_epa.pm25.completed_day"
    )
    adapter_calls = []

    def completed_day_points(
        _session,
        *,
        product,
        device,
        range_started_at,
        range_ended_at,
    ):
        adapter_calls.append(
            (product.product_code, device.device_id, range_started_at, range_ended_at)
        )
        return []

    monkeypatch.setattr(
        air_quality_index,
        "_completed_day_analytics_points",
        completed_day_points,
    )
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    ended_at = started_at + timedelta(days=30)

    result = air_quality_index._analytics_series_out(
        FakeSession(device),
        requested_series=air_quality_index.AirQualityIndexAnalyticsSeriesRequest(
            standard_code="us_epa",
            product_code=product.product_code,
            device_id=device.device_id,
        ),
        standard=standard,
        product=product,
        device=device,
        range_started_at=started_at,
        range_ended_at=ended_at,
    )

    assert result.history_interval == "represented_device_local_date"
    assert adapter_calls == [
        (product.product_code, device.device_id, started_at, ended_at)
    ]


def test_hourly_series_reuses_grouped_results(monkeypatch) -> None:
    source = ExternalAPI(name="Analytics test source", params={})
    device = Device(
        device_id=71,
        name="Analytics test device",
        external_api_id=1,
        timezone="UTC",
    )
    device.external_api = source
    standard = air_quality_index.US_EPA_STANDARD
    product = next(
        product
        for product in standard.products
        if product.product_code == "us_epa.pm25.nowcast"
    )
    grouped_results = []
    adapter_calls = []

    def hourly_points(
        _session,
        *,
        standard_code,
        product,
        device_id,
        range_started_at,
        range_ended_at,
        result_outs,
    ):
        adapter_calls.append(
            (
                standard_code,
                product.product_code,
                device_id,
                range_started_at,
                range_ended_at,
                result_outs,
            )
        )
        return []

    monkeypatch.setattr(air_quality_index, "_hourly_analytics_points", hourly_points)
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    ended_at = started_at + timedelta(days=1)

    air_quality_index._analytics_series_out(
        FakeSession(device),
        requested_series=air_quality_index.AirQualityIndexAnalyticsSeriesRequest(
            standard_code="us_epa",
            product_code=product.product_code,
            device_id=device.device_id,
        ),
        standard=standard,
        product=product,
        device=device,
        range_started_at=started_at,
        range_ended_at=ended_at,
        hourly_result_outs=grouped_results,
    )

    assert adapter_calls == [
        (
            standard.code,
            product.product_code,
            device.device_id,
            started_at,
            ended_at,
            grouped_results,
        )
    ]
