from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from api.main import app
from api.routes import air_quality_index as air_quality_index_routes


def test_current_condition_history_routes_the_selected_product_once(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_history(_session, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        air_quality_index_routes,
        "calculate_us_epa_gas_history",
        fake_history,
    )
    response = TestClient(app).get(
        "/air-quality-index/us_epa/current-history",
        params={
            "product_code": "us_epa.no2.latest",
            "start": "2026-07-13T11:00:00Z",
            "end": "2026-07-14T11:00:00Z",
            "device_id": 42,
            "external_api_name": "openaq",
        },
    )

    assert response.status_code == 200
    assert response.json()["product_code"] == "us_epa.no2.latest"
    assert captured["product_code"] == "us_epa.no2.latest"
    assert captured["device_id"] == 42
    assert captured["external_api_name"] == "openaq"
    assert captured["start_utc"] == datetime(
        2026, 7, 13, 11, tzinfo=timezone.utc
    )
    assert captured["end_utc"] == datetime(
        2026, 7, 14, 11, tzinfo=timezone.utc
    )


def test_current_condition_history_rejects_completed_day_and_ranges_over_90_days() -> None:
    client = TestClient(app)
    url = "/air-quality-index/us_epa/current-history"
    completed_day_response = client.get(
        url,
        params={
            "product_code": "us_epa.pm25.completed_day",
            "start": "2026-07-13T11:00:00Z",
            "end": "2026-07-14T11:00:00Z",
        },
    )
    long_range_response = client.get(
        url,
        params={
            "product_code": "us_epa.pm25.nowcast",
            "start": "2026-04-14T10:00:00Z",
            "end": "2026-07-14T11:00:00Z",
        },
    )

    assert completed_day_response.status_code == 400
    assert "represented local dates" in completed_day_response.json()["detail"]
    assert long_range_response.status_code == 400
    assert "at most 90 days" in long_range_response.json()["detail"]
