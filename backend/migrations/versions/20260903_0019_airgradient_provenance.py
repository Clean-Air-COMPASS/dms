"""add explicit device acquisition and attribution metadata

Revision ID: 20260903_0019
Revises: 20260903_0018
Create Date: 2026-09-03

AirGradient location IDs can be reached through distinct authenticated and
public-reference API paths. The acquisition path is therefore part of local
device identity. The remaining columns preserve the compact provider,
contributor, place, and license facts required for UI and CSV attribution.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260903_0019"
down_revision: Union[str, None] = "20260903_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PUBLIC_REFERENCE_LOCATION_IDS = ("58376", "175911", "160791")


def upgrade() -> None:
    op.add_column(
        "device",
        sa.Column(
            "acquisition_path",
            sa.String(length=64),
            nullable=False,
            server_default="unspecified",
        ),
    )
    op.add_column("device", sa.Column("hardware_provider_name", sa.String(length=120), nullable=True))
    op.add_column("device", sa.Column("provider_url", sa.String(length=512), nullable=True))
    op.add_column("device", sa.Column("contributor_name", sa.String(length=240), nullable=True))
    op.add_column("device", sa.Column("contributor_url", sa.String(length=512), nullable=True))
    op.add_column("device", sa.Column("license_code", sa.String(length=64), nullable=True))
    op.add_column("device", sa.Column("license_url", sa.String(length=512), nullable=True))
    op.add_column("device", sa.Column("license_share_alike", sa.Boolean(), nullable=True))

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE device SET acquisition_path = 'airgradient_authenticated', "
            "hardware_provider_name = 'AirGradient', "
            "provider_url = 'https://www.airgradient.com' "
            "WHERE external_api_id IN ("
            "SELECT external_api_id FROM external_api WHERE provider_code = 'airgradient')"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE device SET acquisition_path = 'airgradient_public_reference', "
            "hardware_provider_name = 'AirGradient', "
            "provider_url = 'https://www.airgradient.com', "
            "license_code = 'CC-BY-SA-4.0', "
            "license_url = 'https://creativecommons.org/licenses/by-sa/4.0/', "
            "license_share_alike = true "
            "WHERE external_id IN :location_ids AND external_api_id IN ("
            "SELECT external_api_id FROM external_api WHERE provider_code = 'airgradient')"
        ).bindparams(sa.bindparam("location_ids", expanding=True)),
        {"location_ids": PUBLIC_REFERENCE_LOCATION_IDS},
    )

    op.drop_constraint("uq_device_external_api_external_id", "device", type_="unique")
    op.create_unique_constraint(
        "uq_device_external_api_external_id_acquisition_path",
        "device",
        ["external_api_id", "external_id", "acquisition_path"],
    )


def downgrade() -> None:
    # This succeeds when no provider Location ID is represented through two
    # acquisition paths. PostgreSQL will reject the restored constraint rather
    # than silently discard either legitimate row when such data exists.
    op.drop_constraint(
        "uq_device_external_api_external_id_acquisition_path",
        "device",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_device_external_api_external_id",
        "device",
        ["external_api_id", "external_id"],
    )
    op.drop_column("device", "license_share_alike")
    op.drop_column("device", "license_url")
    op.drop_column("device", "license_code")
    op.drop_column("device", "contributor_url")
    op.drop_column("device", "contributor_name")
    op.drop_column("device", "provider_url")
    op.drop_column("device", "hardware_provider_name")
    op.drop_column("device", "acquisition_path")
