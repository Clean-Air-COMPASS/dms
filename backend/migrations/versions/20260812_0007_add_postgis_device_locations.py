"""add canonical PostGIS device locations

Revision ID: 20260812_0007
Revises: 20260812_0006
Create Date: 2026-08-12
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260812_0007"
down_revision: Union[str, None] = "20260812_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_location_constraint(table_name: str) -> None:
    op.execute(
        f"""
        ALTER TABLE {table_name}
        ADD CONSTRAINT ck_{table_name}_location_range
        CHECK (
            location IS NULL
            OR
            (GeometryType(location) = 'POINT'
             AND ST_SRID(location) = 4326
             AND ST_NDims(location) = 2
             AND ST_Y(location) BETWEEN -90.0 AND 90.0
             AND ST_X(location) BETWEEN -180.0 AND 180.0)
        )
        """
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute(
        """
        DO $$
        DECLARE
            invalid_device_count integer;
            invalid_history_count integer;
            invalid_device_ids text;
            invalid_history_ids text;
        BEGIN
            SELECT count(*), string_agg(device_id::text, ', ' ORDER BY device_id)
            INTO invalid_device_count, invalid_device_ids
            FROM device
            WHERE (latitude IS NULL) <> (longitude IS NULL)
               OR (latitude IS NOT NULL AND NOT (latitude BETWEEN -90.0 AND 90.0))
               OR (longitude IS NOT NULL AND NOT (longitude BETWEEN -180.0 AND 180.0));

            SELECT count(*), string_agg(device_location_id::text, ', ' ORDER BY device_location_id)
            INTO invalid_history_count, invalid_history_ids
            FROM device_location_history
            WHERE (latitude IS NULL) <> (longitude IS NULL)
               OR (latitude IS NOT NULL AND NOT (latitude BETWEEN -90.0 AND 90.0))
               OR (longitude IS NOT NULL AND NOT (longitude BETWEEN -180.0 AND 180.0));

            IF invalid_device_count > 0 OR invalid_history_count > 0 THEN
                RAISE EXCEPTION
                    'PostGIS location preflight failed: device count=% ids=[%]; history count=% ids=[%]',
                    invalid_device_count, coalesce(invalid_device_ids, ''),
                    invalid_history_count, coalesce(invalid_history_ids, '');
            END IF;
        END;
        $$
        """
    )

    op.execute("ALTER TABLE device ADD COLUMN location geometry(Point,4326)")
    op.execute(
        "ALTER TABLE device_location_history ADD COLUMN location geometry(Point,4326)"
    )
    op.execute(
        """
        UPDATE device
        SET location = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE device_location_history
        SET location = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM device
                WHERE location IS NOT NULL
                  AND (ST_SRID(location) <> 4326
                       OR ST_Y(location) IS DISTINCT FROM latitude
                       OR ST_X(location) IS DISTINCT FROM longitude)
            ) OR EXISTS (
                SELECT 1 FROM device_location_history
                WHERE location IS NOT NULL
                  AND (ST_SRID(location) <> 4326
                       OR ST_Y(location) IS DISTINCT FROM latitude
                       OR ST_X(location) IS DISTINCT FROM longitude)
            ) THEN
                RAISE EXCEPTION 'PostGIS location backfill verification failed';
            END IF;
        END;
        $$
        """
    )

    op.execute("ALTER TABLE device DROP COLUMN latitude, DROP COLUMN longitude")
    op.execute(
        "ALTER TABLE device_location_history "
        "DROP COLUMN latitude, DROP COLUMN longitude"
    )
    _add_location_constraint("device")
    _add_location_constraint("device_location_history")
    op.execute(
        """
        CREATE INDEX ix_device_location_gist
        ON device USING gist (location)
        WHERE location IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_device_location_gist")
    for table_name in ("device_location_history", "device"):
        op.execute(
            f"ALTER TABLE {table_name} DROP CONSTRAINT IF EXISTS ck_{table_name}_location_range"
        )
        op.execute(
            f"ALTER TABLE {table_name} "
            "ADD COLUMN latitude double precision, "
            "ADD COLUMN longitude double precision"
        )
        op.execute(
            f"UPDATE {table_name} "
            "SET latitude = ST_Y(location), longitude = ST_X(location) "
            "WHERE location IS NOT NULL"
        )
        op.execute(f"ALTER TABLE {table_name} DROP COLUMN location")
