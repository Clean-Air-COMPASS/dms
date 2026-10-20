from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import os

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from api.main import app
from db import get_session
import models
from reference_data.default_devices import initialize_default_reference_devices
from services.air_quality_index.hourly_measurements import (
    retrieve_candidate_sensor_streams,
)
from services.device_locations import (
    InvalidBoundingBox,
    InvalidDeviceLocation,
    device_bbox_predicate,
    device_radius_predicate,
    parse_bounding_box,
    set_device_location,
)
from services.measurement_aggregation import execute_latest_measurements
from services.external_sources import ensure_builtin_external_apis
from postgresql_test_support import (
    POSTGRES_TEST_URL_ENV,
    downgrade,
    temporary_postgres_database,
    upgrade,
)


pytestmark = pytest.mark.skipif(
    not os.environ.get(POSTGRES_TEST_URL_ENV),
    reason=f"Set {POSTGRES_TEST_URL_ENV} to run PostgreSQL/PostGIS tests.",
)


def test_default_reference_devices_cover_approved_postgis_areas():
    with temporary_postgres_database("postgis_default_references") as (url, engine):
        upgrade(url)
        with Session(engine) as session:
            sources = session.scalars(
                select(models.ExternalAPI).order_by(models.ExternalAPI.provider_code)
            ).all()
            assert {source.provider_code for source in sources} == {
                "openaq",
                "purpleair",
                "airgradient",
                "demo",
            }
            assert all(source.enabled is False for source in sources if source.provider_code != "demo")
            assert next(source for source in sources if source.provider_code == "demo").enabled is True
            assert all(source.api_key is None for source in sources)
            assert initialize_default_reference_devices(session) == (7, 19)
            session.commit()

            new_york = set(
                session.scalars(
                    select(models.Device.external_id).where(
                        device_bbox_predicate(
                            models.Device.location, (-74.3, 40.5, -73.7, 40.95)
                        )
                    )
                ).all()
            )
            rio = set(
                session.scalars(
                    select(models.Device.external_id).where(
                        device_bbox_predicate(
                            models.Device.location, (-43.5, -23.1, -43.1, -22.7)
                        )
                    )
                ).all()
            )
            manila = set(
                session.scalars(
                    select(models.Device.external_id).where(
                        device_bbox_predicate(
                            models.Device.location, (120.9, 14.4, 121.2, 14.8)
                        )
                    )
                ).all()
            )

            assert new_york == {"971", "626", "159361"}
            assert rio == {"820326", "175407"}
            assert manila == {"4565934", "99177"}

            near_manila = set(
                session.scalars(
                    select(models.Device.external_id).where(
                        device_radius_predicate(
                            models.Device.location,
                            center_latitude=14.6354,
                            center_longitude=121.0779,
                            radius_meters=1000,
                        )
                    )
                ).all()
            )
            assert near_manila == {"4565934"}

            unrelated = session.scalars(
                select(models.Device.external_id).where(
                    device_bbox_predicate(
                        models.Device.location, (0.0, 0.0, 1.0, 1.0)
                    )
                )
            ).all()
            assert unrelated == []

            removed_schedule = session.scalar(
                select(models.JobSchedule).where(
                    models.JobSchedule.task == "openaq_import"
                )
            )
            session.delete(removed_schedule)
            session.commit()
            ensure_builtin_external_apis(session)
            assert initialize_default_reference_devices(session) == (0, 0)
            session.commit()
            assert session.scalar(
                select(models.JobSchedule).where(
                    models.JobSchedule.task == "openaq_import"
                )
            ) is None


def _schema_signature(connection) -> tuple:
    columns = tuple(
        connection.execute(
            text(
                """
                SELECT table_name, column_name, data_type, udt_name, is_nullable,
                       coalesce(column_default, '')
                FROM information_schema.columns
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position
                """
            )
        ).all()
    )
    constraints = tuple(
        connection.execute(
            text(
                """
                SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE connamespace = 'public'::regnamespace
                ORDER BY conrelid::regclass::text, conname
                """
            )
        ).all()
    )
    indexes = tuple(
        connection.execute(
            text(
                """
                SELECT tablename, indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                ORDER BY tablename, indexname
                """
            )
        ).all()
    )
    triggers = tuple(
        connection.execute(
            text(
                """
                SELECT event_object_table, trigger_name, event_manipulation,
                       action_timing, action_statement
                FROM information_schema.triggers
                WHERE trigger_schema = 'public'
                ORDER BY event_object_table, trigger_name, event_manipulation
                """
            )
        ).all()
    )
    return columns, constraints, indexes, triggers


def _insert_legacy_device(connection, *, latitude=40.7128, longitude=-74.006):
    external_api_id = connection.scalar(
        text("SELECT external_api_id FROM external_api ORDER BY external_api_id LIMIT 1")
    )
    device_id = connection.scalar(
        text(
            """
            INSERT INTO device (name, external_api_id, latitude, longitude)
            VALUES ('legacy-spatial-device', :external_api_id, :latitude, :longitude)
            RETURNING device_id
            """
        ),
        {
            "external_api_id": external_api_id,
            "latitude": latitude,
            "longitude": longitude,
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO device_location_history
                (device_id, latitude, longitude, effective_from)
            VALUES (:device_id, :latitude, :longitude, :effective_from)
            """
        ),
        {
            "device_id": device_id,
            "latitude": latitude,
            "longitude": longitude,
            "effective_from": datetime(2026, 1, 1, tzinfo=timezone.utc),
        },
    )
    return device_id


def test_fresh_and_upgraded_installs_converge_on_the_same_spatial_schema():
    with temporary_postgres_database("postgis_fresh") as (fresh_url, fresh_engine):
        upgrade(fresh_url)
        with fresh_engine.connect() as connection:
            fresh_signature = _schema_signature(connection)
            assert connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='postgis'"))

    with temporary_postgres_database("postgis_upgrade") as (
        upgraded_url,
        upgraded_engine,
    ):
        upgrade(upgraded_url, "20260812_0006")
        with upgraded_engine.begin() as connection:
            device_id = _insert_legacy_device(connection)
        upgrade(upgraded_url)
        with upgraded_engine.connect() as connection:
            upgraded_signature = _schema_signature(connection)
            row = connection.execute(
                text(
                    "SELECT ST_Y(location), ST_X(location), ST_SRID(location) "
                    "FROM device WHERE device_id=:device_id"
                ),
                {"device_id": device_id},
            ).one()
            assert row == (40.7128, -74.006, 4326)

    assert upgraded_signature == fresh_signature


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(10.0, None), (91.0, 10.0), (10.0, 181.0)],
)
def test_migration_aborts_without_partial_schema_for_invalid_legacy_coordinates(
    latitude, longitude
):
    with temporary_postgres_database("postgis_invalid") as (url, engine):
        upgrade(url, "20260812_0006")
        with engine.begin() as connection:
            device_id = _insert_legacy_device(
                connection, latitude=latitude, longitude=longitude
            )
        with pytest.raises(Exception, match="PostGIS location preflight failed"):
            upgrade(url)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260812_0006"
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name='device' AND column_name='location'"
                )
            ) == 0
            assert connection.scalar(
                text("SELECT latitude FROM device WHERE device_id=:device_id"),
                {"device_id": device_id},
            ) == latitude


def test_migration_rejects_non_finite_legacy_coordinates():
    with temporary_postgres_database("postgis_non_finite") as (url, engine):
        upgrade(url, "20260812_0006")
        with engine.begin() as connection:
            device_id = _insert_legacy_device(
                connection, latitude=float("nan"), longitude=10.0
            )
        with pytest.raises(Exception, match="PostGIS location preflight failed"):
            upgrade(url)
        with engine.connect() as connection:
            stored_latitude = connection.scalar(
                text("SELECT latitude FROM device WHERE device_id=:device_id"),
                {"device_id": device_id},
            )
            assert math.isnan(stored_latitude)


def test_migration_rejects_invalid_legacy_history_coordinates():
    with temporary_postgres_database("postgis_invalid_history") as (url, engine):
        upgrade(url, "20260812_0006")
        with engine.begin() as connection:
            device_id = _insert_legacy_device(connection)
            connection.execute(
                text(
                    "UPDATE device_location_history SET latitude=95.0 "
                    "WHERE device_id=:device_id"
                ),
                {"device_id": device_id},
            )
        with pytest.raises(Exception, match="history count=1"):
            upgrade(url)


def test_migration_creates_geometry_only_schema_and_one_partial_device_gist():
    with temporary_postgres_database("postgis_objects") as (url, engine):
        # Round-trip only the spatial revision, before later provider safety barriers.
        upgrade(url, "20260812_0007")
        with engine.begin() as connection:
            external_api_id = connection.scalar(
                text("SELECT external_api_id FROM external_api ORDER BY external_api_id LIMIT 1")
            )
            device_id = connection.scalar(
                text(
                    """
                    INSERT INTO device (name, external_api_id, location)
                    VALUES ('geometry-device', :external_api_id,
                            ST_SetSRID(ST_MakePoint(-122.4, 37.8), 4326))
                    RETURNING device_id
                    """
                ),
                {"external_api_id": external_api_id},
            )
        with engine.connect() as connection:
            stored_columns = set(
                connection.execute(
                    text(
                        "SELECT table_name, column_name "
                        "FROM information_schema.columns "
                        "WHERE table_name IN ('device', 'device_location_history')"
                    )
                ).all()
            )
            for table_name in ("device", "device_location_history"):
                assert (table_name, "location") in stored_columns
                assert (table_name, "latitude") not in stored_columns
                assert (table_name, "longitude") not in stored_columns
            geometry_metadata = connection.execute(
                text(
                    "SELECT f_table_name, f_geometry_column, type, srid, coord_dimension "
                    "FROM geometry_columns "
                    "WHERE f_table_name IN ('device', 'device_location_history') "
                    "ORDER BY f_table_name"
                )
            ).all()
            assert geometry_metadata == [
                ("device", "location", "POINT", 4326, 2),
                ("device_location_history", "location", "POINT", 4326, 2),
            ]
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM pg_proc "
                    "WHERE proname='sync_location_coordinate_mirrors'"
                )
            ) == 0
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.triggers "
                    "WHERE event_object_table IN ('device', 'device_location_history')"
                )
            ) == 0
            spatial_indexes = connection.execute(
                text(
                    "SELECT tablename, indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname='public' AND indexdef ILIKE '% USING gist %'"
                )
            ).all()
            assert spatial_indexes == [
                (
                    "device",
                    "ix_device_location_gist",
                    "CREATE INDEX ix_device_location_gist ON public.device USING gist (location) WHERE (location IS NOT NULL)",
                )
            ]

        with engine.begin() as connection:
            external_api_id = connection.scalar(
                text("SELECT external_api_id FROM external_api ORDER BY external_api_id LIMIT 1")
            )
            duplicate_id = connection.scalar(
                text(
                    "INSERT INTO device (name, external_api_id, location) "
                    "VALUES ('duplicate-point', :external_api_id, "
                    "ST_SetSRID(ST_MakePoint(-122.4, 37.8), 4326)) "
                    "RETURNING device_id"
                ),
                {"external_api_id": external_api_id},
            )
            assert duplicate_id != device_id

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE device SET location="
                        "ST_SetSRID(ST_MakePoint(0, 95), 4326) WHERE device_id=:id"
                    ),
                    {"id": device_id},
                )
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE device SET location="
                        "ST_SetSRID(ST_MakePoint(0, 0), 3857) WHERE device_id=:id"
                    ),
                    {"id": device_id},
                )
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE device SET location="
                        "ST_GeomFromText('LINESTRING(0 0, 1 1)', 4326) "
                        "WHERE device_id=:id"
                    ),
                    {"id": device_id},
                )

        downgrade(url, "20260812_0006")
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT latitude, longitude FROM device WHERE device_id=:id"),
                {"id": device_id},
            ).one() == (37.8, -122.4)
            assert connection.scalar(
                text("SELECT count(*) FROM pg_extension WHERE extname='postgis'")
            ) == 1
        upgrade(url)
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT ST_Y(location), ST_X(location) FROM device WHERE device_id=:id"
            ), {"id": device_id}).one() == (37.8, -122.4)


def test_admin_crud_keeps_the_public_coordinate_contract_on_postgis():
    from api.routes.admin.devices import (
        create_device_admin,
        delete_device_admin,
        update_device_admin,
    )

    with temporary_postgres_database("postgis_crud") as (url, engine):
        upgrade(url)
        with Session(engine) as session:
            created = create_device_admin(
                {
                    "name": "PostGIS CRUD device",
                    "network": "Other",
                    "latitude": 38.44,
                    "longitude": -122.71,
                },
                session,
            )
            assert created["latitude"] == 38.44
            assert created["longitude"] == -122.71
            assert "location" not in created
            device_id = created["device_id"]

            unavailable = create_device_admin(
                {"name": "PostGIS unavailable device", "network": "Other"},
                session,
            )
            assert unavailable["latitude"] is None
            assert unavailable["longitude"] is None
            assert "location" not in unavailable

            external_api_id = session.scalar(
                select(models.ExternalAPI.external_api_id).order_by(
                    models.ExternalAPI.external_api_id
                )
            )
            stored_point_id = session.scalar(
                text(
                    "INSERT INTO device (name, external_api_id, location) "
                    "VALUES ('Stored PostGIS point', :external_api_id, "
                    "ST_GeomFromText('POINT(-73.98 40.70)', 4326)) "
                    "RETURNING device_id"
                ),
                {"external_api_id": external_api_id},
            )
            session.commit()

            def override_session():
                yield session

            app.dependency_overrides[get_session] = override_session
            try:
                response = TestClient(app).get("/devices")
                assert response.status_code == 200, response.text
                public_devices = {
                    row["device_id"]: row for row in response.json()
                }
                assert public_devices[device_id]["latitude"] == 38.44
                assert public_devices[device_id]["longitude"] == -122.71
                assert public_devices[stored_point_id]["latitude"] == 40.70
                assert public_devices[stored_point_id]["longitude"] == -73.98
                assert public_devices[unavailable["device_id"]]["latitude"] is None
                assert public_devices[unavailable["device_id"]]["longitude"] is None
                assert all("location" not in row for row in public_devices.values())
            finally:
                app.dependency_overrides.pop(get_session, None)

            updated = update_device_admin(
                device_id,
                {"latitude": 38.45, "longitude": -122.72},
                session,
            )
            assert updated["latitude"] == 38.45
            assert updated["longitude"] == -122.72
            history_count = session.scalar(
                select(text("count(*)"))
                .select_from(models.DeviceLocationHistory)
                .where(models.DeviceLocationHistory.device_id == device_id)
            )
            assert history_count == 2

            deleted = delete_device_admin(device_id, session)
            assert deleted == {"status": "deleted"}
            assert session.get(models.Device, device_id) is None
            delete_device_admin(unavailable["device_id"], session)
            delete_device_admin(stored_point_id, session)


def _catalog(session: Session):
    source = session.scalar(select(models.ExternalAPI).order_by(models.ExternalAPI.external_api_id))
    parameter = session.scalar(select(models.Parameter).where(models.Parameter.code == "pm25"))
    unit = session.get(models.Unit, parameter.default_unit_id)
    aggregation = session.scalar(
        select(models.AggregationPeriod).where(models.AggregationPeriod.code == "1h")
    )
    return source, parameter, unit, aggregation


def _device(
    session: Session,
    source: models.ExternalAPI,
    name: str,
    latitude: float | None,
    longitude: float | None,
    effective_at: datetime,
) -> models.Device:
    device = models.Device(
        name=name,
        external_api_id=source.external_api_id,
        timezone="UTC",
    )
    session.add(device)
    set_device_location(
        session,
        device,
        latitude=latitude,
        longitude=longitude,
        effective_at=effective_at,
    )
    return device


def test_crud_history_bbox_radius_and_all_bbox_query_paths(monkeypatch):
    with temporary_postgres_database("postgis_queries") as (url, engine):
        upgrade(url)
        started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with Session(engine) as session:
            source, parameter, unit, aggregation = _catalog(session)
            nyc = _device(session, source, "NYC", 40.7128, -74.006, started_at)
            duplicate_nyc = _device(
                session, source, "NYC duplicate", 40.7128, -74.006, started_at
            )
            boundary = _device(session, source, "Boundary", 41.0, -73.0, started_at)
            rio = _device(session, source, "Rio", -22.979204, -43.23326, started_at)
            manila = _device(session, source, "Manila", 14.5995, 120.9842, started_at)
            unavailable = _device(session, source, "Unavailable", None, None, started_at)
            dateline = _device(session, source, "Dateline", 0.0, -179.9, started_at)

            for device in (nyc, duplicate_nyc, boundary, rio, manila):
                sensor = models.Sensor(
                    device_id=device.device_id,
                    parameter_id=parameter.parameter_id,
                    unit_id=unit.unit_id,
                    aggregation_period_id=aggregation.aggregation_period_id,
                )
                session.add(sensor)
                session.flush()
                session.add(
                    models.Measurement(
                        sensor_id=sensor.sensor_id,
                        value=10.0,
                        observed_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                        is_valid=True,
                    )
                )
            session.commit()

            assert set_device_location(
                session,
                nyc,
                latitude=40.713,
                longitude=-74.005,
                effective_at=started_at + timedelta(days=1),
            )
            assert not set_device_location(
                session,
                nyc,
                latitude=40.713,
                longitude=-74.005,
                effective_at=started_at + timedelta(days=2),
            )
            session.commit()
            with pytest.raises(
                InvalidDeviceLocation, match="newer than the latest history row"
            ):
                set_device_location(
                    session,
                    nyc,
                    latitude=40.714,
                    longitude=-74.004,
                    effective_at=started_at,
                )

            bbox = parse_bounding_box("-75,40,-73,41")
            assert bbox is not None
            bbox_ids = set(
                session.scalars(
                    select(models.Device.device_id).where(
                        device_bbox_predicate(models.Device.location, bbox)
                    )
                )
            )
            assert bbox_ids == {nyc.device_id, duplicate_nyc.device_id, boundary.device_id}

            world = parse_bounding_box("-180,-90,180,90")
            world_ids = set(
                session.scalars(
                    select(models.Device.device_id).where(
                        device_bbox_predicate(models.Device.location, world)
                    )
                )
            )
            assert unavailable.device_id not in world_ids
            assert {rio.device_id, manila.device_id, dateline.device_id}.issubset(world_ids)
            with pytest.raises(InvalidBoundingBox):
                parse_bounding_box("170,-10,-170,10")
            for invalid_bbox in ("nan,-10,10,10", "-10,-inf,10,10"):
                with pytest.raises(InvalidBoundingBox, match="finite"):
                    parse_bounding_box(invalid_bbox)

            nearby_ids = set(
                session.scalars(
                    select(models.Device.device_id).where(
                        device_radius_predicate(
                            models.Device.location,
                            center_latitude=40.7128,
                            center_longitude=-74.006,
                            radius_meters=1000,
                        )
                    )
                )
            )
            assert {nyc.device_id, duplicate_nyc.device_id}.issubset(nearby_ids)
            assert rio.device_id not in nearby_ids

            boundary_distance = session.scalar(
                text(
                    "SELECT ST_Distance(location::geography, "
                    "ST_SetSRID(ST_MakePoint(-74.006, 40.7128), 4326)::geography) "
                    "FROM device WHERE device_id=:device_id"
                ),
                {"device_id": boundary.device_id},
            )
            exact_boundary_ids = set(
                session.scalars(
                    select(models.Device.device_id).where(
                        device_radius_predicate(
                            models.Device.location,
                            center_latitude=40.7128,
                            center_longitude=-74.006,
                            radius_meters=boundary_distance,
                        )
                    )
                )
            )
            assert boundary.device_id in exact_boundary_ids
            with pytest.raises(InvalidDeviceLocation, match="non-negative"):
                device_radius_predicate(
                    models.Device.location,
                    center_latitude=40.7128,
                    center_longitude=-74.006,
                    radius_meters=-1,
                )
            with pytest.raises(InvalidDeviceLocation, match="non-negative"):
                device_radius_predicate(
                    models.Device.location,
                    center_latitude=40.7128,
                    center_longitude=-74.006,
                    radius_meters=float("nan"),
                )

            dateline_ids = set(
                session.scalars(
                    select(models.Device.device_id).where(
                        device_radius_predicate(
                            models.Device.location,
                            center_latitude=0.0,
                            center_longitude=179.9,
                            radius_meters=30_000,
                        )
                    )
                )
            )
            assert dateline.device_id in dateline_ids

            ordinary = execute_latest_measurements(
                session,
                parameter_code="pm25",
                bbox=(-75.0, 40.0, -73.0, 41.0),
            )
            assert {row["device"]["device_id"] for row in ordinary} == {
                nyc.device_id,
                duplicate_nyc.device_id,
                boundary.device_id,
            }
            aqi_streams = retrieve_candidate_sensor_streams(
                session,
                parameter_codes=("pm25",),
                bbox=(-75.0, 40.0, -73.0, 41.0),
            )
            assert {row.device_id for row in aqi_streams} == {
                nyc.device_id,
                duplicate_nyc.device_id,
                boundary.device_id,
            }

            def override_session():
                yield session

            app.dependency_overrides[get_session] = override_session
            monkeypatch.setattr(
                "api.routes.measurements.get_pm25_rolling_24h_avg",
                lambda _session, _device_id, _now: 10.0,
            )
            monkeypatch.setattr(
                "api.routes.measurements.get_pm25_daily_24h_avg",
                lambda _session, _device_id, _local_date: 10.0,
            )
            try:
                for aggregation_code in ("24h_rolling", "24h_daily"):
                    response = TestClient(app).get(
                        "/measurements/pm25/latest",
                        params={
                            "aggregation": aggregation_code,
                            "bbox": "-75,40,-73,41",
                        },
                    )
                    assert response.status_code == 200, response.text
                    assert {
                        row["device"]["device_id"] for row in response.json()
                    } == {
                        nyc.device_id,
                        duplicate_nyc.device_id,
                        boundary.device_id,
                    }
            finally:
                app.dependency_overrides.pop(get_session, None)

            assert set_device_location(
                session,
                nyc,
                latitude=None,
                longitude=None,
                effective_at=started_at + timedelta(days=2),
            )
            session.commit()
            history = session.scalars(
                select(models.DeviceLocationHistory)
                .where(models.DeviceLocationHistory.device_id == nyc.device_id)
                .order_by(models.DeviceLocationHistory.effective_from)
            ).all()
            assert len(history) == 2
            assert all(row.location is not None for row in history)
            assert history[-1].effective_to == started_at + timedelta(days=2)


def test_provider_coordinate_update_policies_use_canonical_history(monkeypatch):
    from sources.airgradient.importer import (
        _ensure_reference_device as ensure_airgradient,
    )
    from sources.openaq.openaq_upserts import _upsert_device_for_external_location
    from sources.purpleair import importer as purpleair_importer

    with temporary_postgres_database("postgis_providers") as (url, engine):
        upgrade(url)
        with Session(engine) as session:
            openaq_source = session.scalar(
                select(models.ExternalAPI).where(models.ExternalAPI.name == "OpenAQ")
            )
            assert openaq_source is not None
            purpleair_source = session.scalar(
                select(models.ExternalAPI).where(models.ExternalAPI.name == "PurpleAir")
            )
            airgradient_source = session.scalar(
                select(models.ExternalAPI).where(models.ExternalAPI.name == "AirGradient")
            )

            openaq_device = _upsert_device_for_external_location(
                session,
                "openaq-location-policy-test",
                latitude=10.0,
                longitude=20.0,
            )
            _upsert_device_for_external_location(
                session,
                "openaq-location-policy-test",
                latitude=11.0,
                longitude=21.0,
            )
            assert (openaq_device.latitude, openaq_device.longitude) == (10.0, 20.0)

            purpleair_payload = {
                "sensor": {
                    "name": "PurpleAir policy test",
                    "latitude": 0.0,
                    "longitude": 0.0,
                }
            }
            monkeypatch.setattr(
                purpleair_importer,
                "_api_get",
                lambda *_args, **_kwargs: purpleair_payload,
            )
            purpleair_device = purpleair_importer._ensure_device(
                session,
                "https://example.invalid",
                "purpleair-policy-test",
                purpleair_source.external_api_id,
                None,
            )
            assert (purpleair_device.latitude, purpleair_device.longitude) == (0.0, 0.0)
            purpleair_payload["sensor"]["latitude"] = 1.0
            purpleair_payload["sensor"]["longitude"] = 2.0
            purpleair_importer._ensure_device(
                session,
                "https://example.invalid",
                "purpleair-policy-test",
                purpleair_source.external_api_id,
                None,
            )
            assert (purpleair_device.latitude, purpleair_device.longitude) == (1.0, 2.0)

            airgradient_device = ensure_airgradient(
                session,
                {
                    "locationId": "58376",
                    "name": "AirGradient policy test",
                    "latitude": 40.940119,
                    "longitude": -73.7561704,
                },
                airgradient_source.external_api_id,
                "58376",
                "UTC",
            )
            ensure_airgradient(
                session,
                {
                    "locationId": "58376",
                    "name": "AirGradient policy test",
                    "latitude": 40.940219,
                    "longitude": -73.7560704,
                },
                airgradient_source.external_api_id,
                "58376",
                "UTC",
            )
            assert (airgradient_device.latitude, airgradient_device.longitude) == (
                40.940219,
                -73.7560704,
            )
            session.commit()

            purpleair_payload["sensor"]["longitude"] = None
            with pytest.raises(
                InvalidDeviceLocation, match="both be provided or both be absent"
            ):
                purpleair_importer._ensure_device(
                    session,
                    "https://example.invalid",
                    "purpleair-policy-test",
                    purpleair_source.external_api_id,
                    None,
                )

            openaq_history_count = session.scalar(
                select(text("count(*)")).select_from(models.DeviceLocationHistory).where(
                    models.DeviceLocationHistory.device_id == openaq_device.device_id
                )
            )
            purpleair_history_count = session.scalar(
                select(text("count(*)")).select_from(models.DeviceLocationHistory).where(
                    models.DeviceLocationHistory.device_id == purpleair_device.device_id
                )
            )
            airgradient_history_count = session.scalar(
                select(text("count(*)")).select_from(models.DeviceLocationHistory).where(
                    models.DeviceLocationHistory.device_id == airgradient_device.device_id
                )
            )
            assert openaq_history_count == 1
            assert purpleair_history_count == 2
            assert airgradient_history_count == 2


def test_map_device_parameter_filter_uses_sensors_without_requiring_observations():
    from api.routes.general import list_devices

    with temporary_postgres_database("map_device_filters") as (url, engine):
        upgrade(url)
        with Session(engine) as session:
            initialize_default_reference_devices(session)
            session.commit()
            assert session.scalar(select(models.Measurement.measurement_id).limit(1)) is None
            all_devices = list_devices(parameter=None, aggregation=None, external_api_name=None, session=session)
            assert len(all_devices) == 7
            pm25_devices = list_devices(parameter="pm25", aggregation=None, external_api_name=None, session=session)
            assert {device["external_id"] for device in pm25_devices} == {
                "971", "820326", "4565934", "159361", "175407", "99177",
            }
            purpleair_devices = list_devices(parameter="pm25", aggregation=None, external_api_name="purpleair", session=session)
            assert {device["external_id"] for device in purpleair_devices} == {"159361", "175407", "99177"}
            assert list_devices(parameter="not-a-parameter", aggregation=None, external_api_name=None, session=session) == []
