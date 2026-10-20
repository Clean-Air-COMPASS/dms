"""Quick Download pagination preserves the latest-per-sensor query contract."""
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from api.routes import measurements
from api.main import app


@pytest.mark.parametrize('endpoint', ['/measurements/pm25/latest', '/measurements/latest'])
def test_export_pages_include_every_sensor_without_duplicates(monkeypatch, endpoint):
    # Deliberately reverse sensor order and tie timestamps. Export order must be
    # independent of latest-first order and timestamps changing between pages.
    rows = [dict(measurement_id=i, sensor_id=i, parameter='pm25',
                 parameter_name='PM2.5', value=12.5, unit='µg/m³',
                 observed_at='2020-01-01T00:00:00Z', device=None)
            for i in range(235, 0, -1)]
    retrieve = Mock(return_value=rows)
    monkeypatch.setattr(measurements, 'execute_latest_measurements', retrieve)
    client = TestClient(app)
    exported = []
    for offset, expected_count in [(0, 100), (100, 100), (200, 35), (300, 0)]:
        response = client.get(endpoint, params={'offset': offset, 'limit': 100,
                              'aggregation': '1h', 'external_api_name': 'Other'})
        assert response.status_code == 200, response.text
        page = response.json()
        assert len(page) == expected_count
        exported.extend(page)
        filters = retrieve.call_args.kwargs
        assert filters['source'] == 'other'
        assert filters['result_aggregation_code'] == '1h'
        assert filters['since'] is None
        assert filters['until'] is None
        if 'pm25' in endpoint:
            assert filters['parameter_code'] == 'pm25'
    assert [row['sensor_id'] for row in exported] == list(range(1, 236))
    assert len({row['sensor_id'] for row in exported}) == 235


@pytest.mark.parametrize('endpoint', ['/measurements/pm25/latest', '/measurements/latest'])
def test_export_offset_is_validated_and_remains_bounded_with_since(monkeypatch, endpoint):
    rows = [dict(measurement_id=i, sensor_id=i, parameter='pm25',
                 parameter_name='PM2.5', value=1, unit='µg/m³',
                 observed_at='2020-01-01T00:00:00Z', device=None) for i in range(1, 236)]
    monkeypatch.setattr(measurements, 'execute_latest_measurements', Mock(return_value=rows))
    client = TestClient(app)
    assert client.get(endpoint, params={'offset': -1}).status_code == 422
    assert client.get(endpoint, params={'limit': 1001, 'offset': 0}).status_code == 422
    response = client.get(endpoint, params={'offset': 100, 'limit': 100, 'since': '2019-01-01T00:00:00Z'})
    assert response.status_code == 200
    assert len(response.json()) == 100
    assert response.json()[0]['sensor_id'] == 101


def test_device_inventory_filters_do_not_require_measurements_or_coordinates():
    from sqlalchemy import select
    from db import SessionLocal
    from models import Device, ExternalAPI, Parameter, Sensor, Unit
    from api.routes.general import list_devices

    with SessionLocal() as session:
        provider = ExternalAPI(name='Synthetic inventory provider', base_url='https://example.invalid', params={})
        session.add(provider)
        session.flush()
        unit = session.scalar(select(Unit).where(Unit.code == 'ug_m3'))
        pm25 = session.scalar(select(Parameter).where(Parameter.code == 'pm25'))
        pm10 = session.scalar(select(Parameter).where(Parameter.code == 'pm10'))
        first = Device(name='Synthetic Estación Niño', external_api_id=provider.external_api_id)
        second = Device(name='Synthetic different parameter', external_api_id=provider.external_api_id)
        manual = Device(name='Synthetic manual source', external_api_id=provider.external_api_id,
                        manual_data_source_name='Neighborhood lab')
        session.add_all([first, second, manual])
        session.flush()
        session.add_all([Sensor(device_id=first.device_id, parameter_id=pm25.parameter_id, unit_id=unit.unit_id),
                         Sensor(device_id=second.device_id, parameter_id=pm10.parameter_id, unit_id=unit.unit_id),
                         Sensor(device_id=manual.device_id, parameter_id=pm25.parameter_id, unit_id=unit.unit_id)])
        session.flush()
        devices = list_devices(parameter='pm25', aggregation=None,
                               external_api_name=provider.name.lower(), session=session)
        # The retained provider association is storage metadata for manual
        # devices; their authoritative public source remains Other.
        assert {row['device_id'] for row in devices} == {first.device_id}
        first_row = next(row for row in devices if row['device_id'] == first.device_id)
        assert first_row['name'] == 'Synthetic Estación Niño'
        assert first_row['latitude'] is None
        assert first_row['longitude'] is None
        assert first_row['sensor_count'] == 1
        manual_devices = list_devices(parameter='pm25', aggregation=None, external_api_name='other', session=session)
        assert manual.device_id in {row['device_id'] for row in manual_devices}
        assert first.device_id not in {row['device_id'] for row in manual_devices}
        manual_row = next(row for row in manual_devices if row['device_id'] == manual.device_id)
        assert manual_row['network'] == 'Other'
        assert manual_row['data_attribution']['data_provider_name'] == 'Other'
        all_devices = list_devices(parameter='pm25', aggregation=None, external_api_name=None, session=session)
        fixture_ids = {first.device_id, second.device_id, manual.device_id}
        assert {row['device_id'] for row in all_devices} & fixture_ids == {first.device_id, manual.device_id}
        assert manual.external_api_id == provider.external_api_id
        session.rollback()
