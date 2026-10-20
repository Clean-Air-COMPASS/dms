"""Reviewed geographic limits for built-in references, never user locations."""
from services.device_locations import BoundingBox, validate_coordinate_pair


# WGS84 degrees; deliberately allow the surrounding metropolitan area.
REFERENCE_REGION_BOUNDS = {
    "new_york": BoundingBox(-74.5, 40.4, -73.4, 41.2),
    "rio_de_janeiro": BoundingBox(-43.9, -23.2, -42.8, -22.6),
    "metro_manila": BoundingBox(120.8, 14.3, 121.3, 14.9),
}

# Reviewed site windows wholly on South American land. This intentionally
# validates approved sites, not every point in a continent-sized rectangle
# (which would also admit ocean and Caribbean/Central American locations).
# AirGradient 175911: São Paulo, Brazil; see docs/airgradient-south-america-reference.md.
SOUTH_AMERICA_REFERENCE_SITE_BOUNDS = {
    "175911": BoundingBox(-46.72, -23.70, -46.61, -23.59),
}


def validate_south_america_reference_coordinates(
    location_id: str, latitude: object, longitude: object
) -> tuple[float, float]:
    """Require the configured provider site to remain at its verified South America location."""
    bounds = SOUTH_AMERICA_REFERENCE_SITE_BOUNDS.get(location_id)
    if bounds is None:
        raise ValueError(f"Unreviewed South America reference location {location_id}")
    return _validate_coordinates_in_bounds(
        f"south_america_rio_reference location {location_id}", latitude, longitude, bounds
    )


def validate_reference_coordinates(
    region_code: str, latitude: object, longitude: object
) -> tuple[float, float]:
    """Require known, finite coordinates inside the expected reference region."""
    return _validate_coordinates_in_bounds(
        region_code, latitude, longitude, REFERENCE_REGION_BOUNDS[region_code]
    )


def _validate_coordinates_in_bounds(
    region_code: str, latitude: object, longitude: object, bounds: BoundingBox
) -> tuple[float, float]:
    pair = validate_coordinate_pair(latitude, longitude)
    if pair is None:
        raise ValueError(f"Reference {region_code} requires latitude and longitude")
    lat, lon = pair
    if not (
        bounds.min_latitude <= lat <= bounds.max_latitude
        and bounds.min_longitude <= lon <= bounds.max_longitude
    ):
        raise ValueError(
            f"Reference {region_code} returned out-of-region coordinates "
            f"({lat}, {lon}); expected latitude "
            f"[{bounds.min_latitude}, {bounds.max_latitude}] and longitude "
            f"[{bounds.min_longitude}, {bounds.max_longitude}]"
        )
    return pair
