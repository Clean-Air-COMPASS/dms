from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from postgresql_test_support import (
    POSTGRES_TEST_URL_ENV,
    temporary_postgres_database,
    upgrade,
)


pytestmark = pytest.mark.skipif(
    not os.environ.get(POSTGRES_TEST_URL_ENV),
    reason=f"Set {POSTGRES_TEST_URL_ENV} to run PostgreSQL/PostGIS tests.",
)


DERIVED_COORDINATE_BBOX_SQL = """
SELECT count(*)
FROM device
WHERE ST_X(location) >= :min_lon AND ST_X(location) <= :max_lon
  AND ST_Y(location) >= :min_lat AND ST_Y(location) <= :max_lat
"""

POSTGIS_BBOX_SQL = """
SELECT count(*)
FROM device
WHERE ST_Covers(
    ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326),
    location
)
"""


def _explain(connection, sql: str, bounds: dict[str, float]) -> str:
    rows = connection.execute(
        text("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + sql), bounds
    ).scalars()
    return "\n".join(rows)


@pytest.mark.parametrize("row_count", [451, 10_000])
def test_bbox_plan_and_result_regression_at_current_and_representative_scale(
    row_count: int,
):
    """Capture both plans without asserting that every bbox must be faster.

    PostgreSQL may correctly choose a sequential scan for a small table or a
    world-sized box. At the representative 10k scale, this selective box must
    make the one partial GiST index available to the planner.
    """
    with temporary_postgres_database(f"postgis_plan_{row_count}") as (url, engine):
        upgrade(url)
        bounds = {
            "min_lon": -74.01,
            "min_lat": 40.70,
            "max_lon": -74.00,
            "max_lat": 40.72,
        }
        with engine.begin() as connection:
            external_api_id = connection.scalar(
                text(
                    "SELECT external_api_id FROM external_api "
                    "ORDER BY external_api_id LIMIT 1"
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO device (name, external_api_id, location)
                    SELECT
                        'bbox-plan-' || value::text,
                        :external_api_id,
                        ST_SetSRID(
                            ST_MakePoint(
                                -179.0 + ((value * 137) % 35800) / 100.0,
                                -89.0 + ((value * 251) % 17800) / 100.0
                            ),
                            4326
                        )
                    FROM generate_series(1, :generated_count) AS value
                    """
                ),
                {
                    "external_api_id": external_api_id,
                    "generated_count": row_count - 1,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO device (name, external_api_id, location)
                    VALUES (
                        'bbox-plan-target', :external_api_id,
                        ST_SetSRID(ST_MakePoint(-74.006, 40.7128), 4326)
                    )
                    """
                ),
                {"external_api_id": external_api_id},
            )
            connection.execute(text("ANALYZE device"))

        with engine.connect() as connection:
            coordinate_count = connection.scalar(
                text(DERIVED_COORDINATE_BBOX_SQL), bounds
            )
            postgis_count = connection.scalar(text(POSTGIS_BBOX_SQL), bounds)
            coordinate_plan = _explain(
                connection, DERIVED_COORDINATE_BBOX_SQL, bounds
            )
            postgis_plan = _explain(connection, POSTGIS_BBOX_SQL, bounds)

        print(
            f"\n{row_count}-row derived-coordinate bbox plan:\n{coordinate_plan}"
        )
        print(f"\n{row_count}-row PostGIS bbox plan:\n{postgis_plan}")

        assert coordinate_count == postgis_count
        assert "Execution Time" in coordinate_plan
        assert "Execution Time" in postgis_plan
        if row_count == 10_000:
            assert "ix_device_location_gist" in postgis_plan
