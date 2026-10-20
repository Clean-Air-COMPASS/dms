"""Selective administrator imports using the scheduled importer's provider contract."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
from services.device_locations import validate_coordinate_pair
from sources.airgradient import importer


class LocationWorkflowError(Exception):
    def __init__(self, code: str, status: int = 400):
        self.code = code
        self.status = status


def _configuration(session: Session) -> tuple[models.ExternalAPI, str, str]:
    source = session.scalar(select(models.ExternalAPI).where(
        models.ExternalAPI.provider_code == "airgradient"
    ))
    if source is None or not source.api_key or not source.api_key.strip():
        raise LocationWorkflowError("configuration_required")
    # Require the saved Data Source credential; do not fall back to environment keys.
    source, base_url, api_key = importer._load_airgradient_config(session)
    return source, base_url, api_key


def _existing_device(session: Session, source_id: int, location_id: str) -> models.Device | None:
    # Public references are a separate acquisition path, even when IDs overlap.
    return session.scalar(select(models.Device).where(
        models.Device.external_api_id == source_id,
        models.Device.external_id == location_id,
        models.Device.acquisition_path.in_([
            importer.AIRGRADIENT_AUTHENTICATED_PATH, "unspecified",
        ]),
    ).order_by(models.Device.device_id))


def list_locations(session: Session) -> dict:
    source, base_url, api_key = _configuration(session)
    place, locations = importer.fetch_authenticated_locations(api_key, base_url)
    choices = []
    for location in locations:
        location_id = str(location["locationId"])
        try:
            coordinates = validate_coordinate_pair(
                location.get("latitude", location.get("lat")),
                location.get("longitude", location.get("lng")),
            )
        except ValueError as exc:
            raise importer.AirGradientMalformedResponse("Invalid location coordinates") from exc
        existing = _existing_device(session, source.external_api_id, location_id)
        # Explicit allowlist: never return raw provider payloads or source configuration.
        choices.append({
            "location_id": location_id,
            "name": location["locationName"].strip(),
            "latitude": coordinates[0] if coordinates else None,
            "longitude": coordinates[1] if coordinates else None,
            "timezone": location.get("timezone") or place.get("timezoneId"),
            "existing_device_id": existing.device_id if existing else None,
        })
    return {
        "locations": choices,
        "automatic_imports_enabled": source.enabled and importer._authenticated_import_enabled(source),
    }


def add_location(session: Session, location_id: str) -> dict:
    source, base_url, api_key = _configuration(session)
    existing = _existing_device(session, source.external_api_id, location_id)
    if existing:
        return {"device_id": existing.device_id, "already_exists": True, "measurements_imported": 0}

    # Re-read membership at creation. The browser supplies only the selected ID,
    # never trusted metadata, current readings, or an arbitrary provider URL.
    place, locations = importer.fetch_authenticated_locations(api_key, base_url)
    location = next((row for row in locations if str(row["locationId"]) == location_id), None)
    if location is None:
        raise LocationWorkflowError("location_unavailable", 404)

    try:
        with session.begin_nested():
            device, created = importer._ensure_authenticated_device(
                session, location, place, source.external_api_id
            )
            if not created:
                return {"device_id": device.device_id, "already_exists": True, "measurements_imported": 0}
            importer._ensure_airgradient_sensors(session, device, location)
            # Discovery already returned this location's current reading. Apply
            # the same sensor resolution, QC and upsert policy as scheduled runs.
            lookup = importer._sensor_lookup_for_measurements(session, device, [location])
            _, counts, _, _ = importer._store_measurements(
                session, device, [location], None, sensor_lookup=lookup
            )
            session.flush()
            result = {"device_id": device.device_id, "already_exists": False,
                      "measurements_imported": counts["insert"] + counts["update"]}
        return result
    except IntegrityError:
        # The canonical database uniqueness constraint also protects a race
        # with another administrator or a scheduled account-wide discovery.
        existing = _existing_device(session, source.external_api_id, location_id)
        if existing is None:
            raise
        return {"device_id": existing.device_id, "already_exists": True, "measurements_imported": 0}
