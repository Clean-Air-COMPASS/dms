from __future__ import annotations

import pytest
from sqlalchemy import exc, text

from postgresql_test_support import temporary_postgres_database, upgrade


def test_airgradient_provenance_migration_backfills_and_separates_acquisition_paths() -> None:
    with temporary_postgres_database("airgradient_provenance") as (database_url, engine):
        upgrade(database_url, "20260903_0018")
        with engine.begin() as connection:
            source_id = connection.scalar(
                text(
                    "SELECT external_api_id FROM external_api "
                    "WHERE provider_code = 'airgradient'"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO device (name, external_id, external_api_id, timezone) VALUES "
                    "('Legacy public reference', '58376', :source_id, 'UTC'), "
                    "('Legacy authenticated location', 'owned-location', :source_id, 'UTC')"
                ),
                {"source_id": source_id},
            )

        upgrade(database_url, "head")

        with engine.begin() as connection:
            migrated = connection.execute(
                text(
                    "SELECT external_id, acquisition_path, hardware_provider_name, "
                    "license_code, license_share_alike FROM device "
                    "WHERE external_api_id = :source_id ORDER BY external_id"
                ),
                {"source_id": source_id},
            ).all()
            assert migrated == [
                (
                    "58376",
                    "airgradient_public_reference",
                    "AirGradient",
                    "CC-BY-SA-4.0",
                    True,
                ),
                (
                    "owned-location",
                    "airgradient_authenticated",
                    "AirGradient",
                    None,
                    None,
                ),
            ]

            # The same provider Location ID can legitimately be represented by
            # the authenticated and bounded public-reference acquisition paths.
            connection.execute(
                text(
                    "INSERT INTO device "
                    "(name, external_id, external_api_id, timezone, acquisition_path) "
                    "VALUES ('Owned view of reference', '58376', :source_id, 'UTC', "
                    "'airgradient_authenticated')"
                ),
                {"source_id": source_id},
            )

            with pytest.raises(exc.IntegrityError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO device "
                            "(name, external_id, external_api_id, timezone, acquisition_path) "
                            "VALUES ('Duplicate public view', '58376', :source_id, 'UTC', "
                            "'airgradient_public_reference')"
                        ),
                        {"source_id": source_id},
                    )
