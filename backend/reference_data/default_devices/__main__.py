from __future__ import annotations

import argparse

from db import SessionLocal
from services.external_sources import ensure_builtin_external_apis

from .bootstrap import restore_missing_default_reference_devices


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore missing permanent default reference devices and sensors."
    )
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument(
        "--restore-missing",
        action="store_true",
        help="Create only missing manifest devices and sensors; preserve existing edits.",
    )
    actions.add_argument(
        "--restore-airgradient",
        action="store_true",
        help="Fetch and restore the approved AirGradient reference locations.",
    )
    args = parser.parse_args()

    with SessionLocal.begin() as session:
        ensure_builtin_external_apis(session)
        if args.restore_airgradient:
            from sources.airgradient.importer import (
                restore_airgradient_reference_locations,
            )

            result = restore_airgradient_reference_locations(session)
            print(
                "AirGradient reference restore complete: "
                f"devices_created={result['devices_created']}, "
                f"sensors_created={result['sensors_created']}, "
                f"locations_failed={result['locations_failed']}."
            )
        else:
            devices_created, sensors_created = restore_missing_default_reference_devices(
                session
            )
            print(
                "Default reference restore complete: "
                f"devices_created={devices_created}, sensors_created={sensors_created}."
            )


if __name__ == "__main__":
    main()
