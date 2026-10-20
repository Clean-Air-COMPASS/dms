"""Map list requests change result limits, never scientific time semantics."""
from unittest.mock import Mock

import pytest

from api.routes import air_quality_index, measurements


@pytest.mark.parametrize("all_results,expected_count", [(False, 100), (True, 1001)])
def test_latest_measurements_include_all_streams_without_a_recency_window(monkeypatch, all_results, expected_count):
    rows = [{"measurement_id": index, "observed_at": "2020-01-01T00:00:00Z"} for index in range(1001)]
    retrieve = Mock(return_value=rows)
    monkeypatch.setattr(measurements, "execute_latest_measurements", retrieve)
    result = measurements.latest_by_parameter(
        "pm25", limit=100, since=None, until=None, aggregation="1h", bbox=None,
        device_id=None, external_api_name=None, all_results=all_results, session=None,
    )
    assert len(result) == expected_count
    assert result[-1]["observed_at"] == "2020-01-01T00:00:00Z"
    assert retrieve.call_args.kwargs["since"] is None
    assert retrieve.call_args.kwargs["until"] is None
    assert retrieve.call_args.kwargs["result_aggregation_code"] == "1h"


@pytest.mark.parametrize("standard", [air_quality_index.US_EPA_STANDARD, air_quality_index.PHILIPPINES_DENR_STANDARD, air_quality_index.EEA_EUROPEAN_STANDARD])
def test_all_map_aqi_products_can_request_all_locations_without_a_time_override(monkeypatch, standard):
    retrieve = Mock(return_value=[])
    for name in (
        "calculate_latest_us_epa_aqi", "calculate_latest_us_epa_completed_day_aqi",
        "calculate_latest_us_epa_ozone_aqi", "calculate_latest_us_epa_carbon_monoxide_aqi",
        "calculate_latest_us_epa_nitrogen_dioxide_aqi", "calculate_latest_us_epa_sulfur_dioxide_aqi",
        "calculate_latest_philippine_aqi", "calculate_latest_eea_european_index",
    ):
        monkeypatch.setattr(air_quality_index, name, retrieve)
    for product in standard.products:
        for all_results, expected_limit in ((False, 100), (True, None)):
            retrieve.reset_mock()
            air_quality_index.latest_air_quality_index(
                standard.code, product_code=product.product_code, until=None,
                limit=100, all_results=all_results, session=None,
            )
            retrieve.assert_called_once()
            assert retrieve.call_args.kwargs["limit"] == expected_limit
            assert retrieve.call_args.kwargs["reference_time_utc"] is None
            assert retrieve.call_args.kwargs["bbox"] is None
