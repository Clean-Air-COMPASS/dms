"""Add sensor acquisition provenance and transactional interval checkpoints."""
from alembic import op
import sqlalchemy as sa

revision = "20261013_0026"
down_revision = "20260907_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sensor", sa.Column("acquisition_metadata", sa.JSON(), nullable=True))
    op.add_column("sensor", sa.Column(
        "acquisition_examined_until", sa.DateTime(timezone=True), nullable=True,
    ))


def downgrade() -> None:
    # An older backend would lose this stream's provenance and could mix its
    # values into device-level snapshot averages. Never erase that distinction.
    sensors = sa.table(
        "sensor",
        sa.column("measurement_metadata_managed_by", sa.String()),
        sa.column("external_sensor_id", sa.String()),
    )
    has_history = op.get_bind().scalar(sa.select(sa.literal(1)).select_from(sensors).where(
        sa.or_(
            sensors.c.measurement_metadata_managed_by == "airgradient_map_history_importer",
            sensors.c.external_sensor_id.like("map:%:15m"),
        ),
    ).limit(1))
    if has_history:
        raise RuntimeError(
            "AirGradient history migration cannot be downgraded while processed history streams exist; "
            "preserve their provenance before rolling back."
        )
    op.drop_column("sensor", "acquisition_examined_until")
    op.drop_column("sensor", "acquisition_metadata")
