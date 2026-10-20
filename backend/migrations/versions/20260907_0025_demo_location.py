"""Correct the canonical Demo location while retaining identity and history."""
from alembic import op

revision = "20260907_0025"
down_revision = "20260906_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Freeze this data correction in the migration rather than importing models
    # that may change. Match provenance and the original coordinate, never names.
    op.execute("""
        DO $$
        DECLARE
            demo_device RECORD;
            changed_at timestamptz;
        BEGIN
            FOR demo_device IN
                SELECT d.device_id FROM device d
                JOIN external_api e USING (external_api_id)
                WHERE e.provider_code = 'demo'
                  AND d.external_id = 'compassaq-sample-station'
                  AND d.acquisition_path = 'demo_fixture'
                  AND ST_Y(d.location) = 0 AND ST_X(d.location) = -140
                FOR UPDATE OF d
            LOOP
                SELECT GREATEST(CURRENT_TIMESTAMP,
                    MAX(effective_from) + interval '1 microsecond')
                INTO changed_at FROM device_location_history
                WHERE device_id = demo_device.device_id;

                UPDATE device_location_history SET effective_to = changed_at
                WHERE device_id = demo_device.device_id AND effective_to IS NULL;
                UPDATE device SET location = ST_SetSRID(ST_MakePoint(5.1214, 52.0907), 4326)
                WHERE device_id = demo_device.device_id;
                INSERT INTO device_location_history (device_id, location, effective_from)
                VALUES (demo_device.device_id, ST_SetSRID(ST_MakePoint(5.1214, 52.0907), 4326), changed_at);
            END LOOP;
        END;
        $$
    """)


def downgrade() -> None:
    # Keep the corrected location and its audit history when rolling code back.
    pass
