import httpx
import pytest

BASE = "http://localhost:8000"


def _get(path, **kwargs):
    return httpx.get(f"{BASE}{path}", timeout=10.0, **kwargs)


def test_devices_sensors_with_aggregation():
                             
    try:
        r = _get("/aggregation_periods")
        r.raise_for_status()
    except Exception:
        pytest.skip("API not reachable at http://localhost:8000")

    aggs = r.json()
    assert isinstance(aggs, list) and len(aggs) > 0
                                                 
    agg_code = next((a["code"] for a in aggs if a.get("code") == "1h"), aggs[0].get("code"))

                   
    r = _get("/devices")
    r.raise_for_status()
    devices = r.json()
    assert isinstance(devices, list)
    if len(devices) == 0:
        pytest.skip("No devices available in the test DB")

                                                  
    device = next((d for d in devices if d.get("sensor_count") and d.get("sensor_count") > 0), devices[0])
    device_id = device.get("device_id")
    assert device_id is not None

                                                       
    r = _get(f"/devices/{device_id}/sensors?aggregation={agg_code}")
                           
    assert r.status_code != 500
    r.raise_for_status()

    sensors = r.json()
    assert isinstance(sensors, list)
                                               
    for s in sensors:
        assert "sensor_id" in s
        assert "parameter" in s

