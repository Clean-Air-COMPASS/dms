from __future__ import annotations

"""Canonical device-location writes and PostGIS search predicates.

Public API responses continue to expose latitude and longitude as coordinates
derived from ``location``. Application code must write locations through this
module so history and current state stay aligned.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Optional

from geoalchemy2 import Geography
from geoalchemy2.elements import WKTElement
from sqlalchemy import Boolean, and_, cast, func, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.orm import Session

import models


class InvalidDeviceLocation(ValueError):
    """A coordinate pair cannot represent a canonical WGS84 point."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


class InvalidBoundingBox(ValueError):
    """A bbox cannot be represented by the existing public bbox contract."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class BoundingBox:
    min_longitude: float
    min_latitude: float
    max_longitude: float
    max_latitude: float

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (
            self.min_longitude,
            self.min_latitude,
            self.max_longitude,
            self.max_latitude,
        )


def validate_coordinate_pair(
    latitude: Optional[float], longitude: Optional[float]
) -> Optional[tuple[float, float]]:
    """Return a finite WGS84 pair, or ``None`` when both values are absent."""
    if latitude is None and longitude is None:
        return None
    if latitude is None or longitude is None:
        raise InvalidDeviceLocation(
            "incomplete_coordinate_pair",
            "latitude and longitude must both be provided or both be absent",
        )
    try:
        normalized_latitude = float(latitude)
        normalized_longitude = float(longitude)
    except (TypeError, ValueError) as exc:
        raise InvalidDeviceLocation(
            "non_numeric_coordinate", "latitude and longitude must be numeric"
        ) from exc
    if not math.isfinite(normalized_latitude) or not math.isfinite(
        normalized_longitude
    ):
        raise InvalidDeviceLocation(
            "non_finite_coordinate", "latitude and longitude must be finite"
        )
    if not -90.0 <= normalized_latitude <= 90.0:
        raise InvalidDeviceLocation(
            "latitude_out_of_range", "latitude must be between -90 and 90"
        )
    if not -180.0 <= normalized_longitude <= 180.0:
        raise InvalidDeviceLocation(
            "longitude_out_of_range", "longitude must be between -180 and 180"
        )
    return normalized_latitude, normalized_longitude


def parse_bounding_box(value: Optional[str]) -> Optional[BoundingBox]:
    """Parse the established ``min_lon,min_lat,max_lon,max_lat`` contract."""
    if value is None:
        return None
    parts = value.split(",")
    if len(parts) != 4:
        raise InvalidBoundingBox(
            "invalid_bbox_format", "bbox must be min_lon,min_lat,max_lon,max_lat"
        )
    try:
        coordinates = tuple(float(part.strip()) for part in parts)
    except (TypeError, ValueError) as exc:
        raise InvalidBoundingBox(
            "non_numeric_bbox", "bbox values must be numeric"
        ) from exc
    if not all(math.isfinite(coordinate) for coordinate in coordinates):
        raise InvalidBoundingBox(
            "non_finite_bbox", "bbox values must be finite"
        )
    min_longitude, min_latitude, max_longitude, max_latitude = coordinates
    if min_longitude >= max_longitude or min_latitude >= max_latitude:
        raise InvalidBoundingBox(
            "invalid_bbox_bounds", "bbox bounds are invalid (min must be < max)"
        )
    return BoundingBox(
        min_longitude=min_longitude,
        min_latitude=min_latitude,
        max_longitude=max_longitude,
        max_latitude=max_latitude,
    )


def _coerce_bounding_box(
    bbox: BoundingBox | tuple[float, float, float, float]
) -> BoundingBox:
    if isinstance(bbox, BoundingBox):
        return bbox
    return BoundingBox(*bbox)


class _DeviceBoundingBoxPredicate(ColumnElement):
    """Dialect-aware expression with PostGIS as the production behavior."""

    type = Boolean()
    inherit_cache = False

    def __init__(self, location_column, latitude_column, longitude_column, bbox):
        self.location_column = location_column
        self.latitude_column = latitude_column
        self.longitude_column = longitude_column
        self.bbox = bbox


@compiles(_DeviceBoundingBoxPredicate, "postgresql")
def _compile_postgis_bbox(element, compiler, **kwargs):
    envelope = func.ST_MakeEnvelope(*element.bbox.as_tuple(), 4326)
    predicate = func.ST_Covers(envelope, element.location_column)
    return compiler.process(predicate, **kwargs)


@compiles(_DeviceBoundingBoxPredicate, "sqlite")
def _compile_sqlite_bbox(element, compiler, **kwargs):
    # SQLite is retained only for existing non-spatial unit tests. Production
    # PostgreSQL always compiles the PostGIS implementation above.
    bbox = element.bbox
    predicate = and_(
        element.longitude_column >= bbox.min_longitude,
        element.longitude_column <= bbox.max_longitude,
        element.latitude_column >= bbox.min_latitude,
        element.latitude_column <= bbox.max_latitude,
    )
    return compiler.process(predicate, **kwargs)


def device_bbox_predicate(
    location_column,
    bbox: BoundingBox | tuple[float, float, float, float],
):
    """Return the shared inclusive bbox predicate.

    PostgreSQL compiles this as ``ST_Covers(ST_MakeEnvelope(...), location)``.
    """
    normalized_bbox = _coerce_bounding_box(bbox)
    model = location_column.class_
    return _DeviceBoundingBoxPredicate(
        location_column,
        model.latitude,
        model.longitude,
        normalized_bbox,
    )


def device_radius_predicate(
    location_column,
    *,
    center_latitude: float,
    center_longitude: float,
    radius_meters: float,
):
    """Return a meter-based WGS84 radius predicate for internal DB queries."""
    center = validate_coordinate_pair(center_latitude, center_longitude)
    assert center is not None
    try:
        normalized_radius = float(radius_meters)
    except (TypeError, ValueError) as exc:
        raise InvalidDeviceLocation(
            "non_numeric_radius", "radius_meters must be numeric"
        ) from exc
    if not math.isfinite(normalized_radius) or normalized_radius < 0:
        raise InvalidDeviceLocation(
            "invalid_radius", "radius_meters must be finite and non-negative"
        )
    latitude, longitude = center
    query_point = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326)
    geography_type = Geography(geometry_type="POINT", srid=4326)
    return func.ST_DWithin(
        cast(location_column, geography_type),
        cast(query_point, geography_type),
        normalized_radius,
        True,
    )


def _normalize_effective_at(value: Optional[datetime]) -> datetime:
    effective_at = value or datetime.now(timezone.utc)
    if effective_at.tzinfo is None:
        return effective_at.replace(tzinfo=timezone.utc)
    return effective_at.astimezone(timezone.utc)


def _point_storage_value(
    session: Session, latitude: float, longitude: float
) -> WKTElement | str:
    wkt = f"POINT ({longitude} {latitude})"
    if session.get_bind().dialect.name == "postgresql":
        return WKTElement(wkt, srid=4326)
    return wkt


def _normalized_history_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def set_device_location(
    session: Session,
    device: models.Device,
    *,
    latitude: Optional[float],
    longitude: Optional[float],
    effective_at: Optional[datetime] = None,
) -> bool:
    """Set canonical current location and maintain non-overlapping history.

    The first point opens history, a changed point closes the open row and opens
    another, and clearing current location closes history without inventing a
    null-location row. An older changed observation is rejected explicitly.
    """
    new_pair = validate_coordinate_pair(latitude, longitude)
    current_pair = validate_coordinate_pair(device.latitude, device.longitude)
    if new_pair == current_pair:
        if device.device_id is None:
            session.add(device)
            session.flush()
            session.refresh(device)
        return False

    changed_at = _normalize_effective_at(effective_at)
    latest_history = None
    if device.device_id is not None:
        # Serialize changes for one device so concurrent provider jobs cannot
        # create two open-ended history rows from the same prior point.
        session.scalar(
            select(models.Device.device_id)
            .where(models.Device.device_id == device.device_id)
            .with_for_update()
        )
        latest_history = session.scalar(
            select(models.DeviceLocationHistory)
            .where(models.DeviceLocationHistory.device_id == device.device_id)
            .order_by(models.DeviceLocationHistory.effective_from.desc())
            .limit(1)
        )
        if latest_history is not None:
            latest_started_at = _normalized_history_time(
                latest_history.effective_from
            )
            if changed_at <= latest_started_at:
                raise InvalidDeviceLocation(
                    "out_of_order_location_change",
                    "a changed location must be newer than the latest history row",
                )

    if new_pair is None:
        device.location = None
    else:
        new_latitude, new_longitude = new_pair
        device.location = _point_storage_value(
            session, new_latitude, new_longitude
        )

    session.add(device)
    session.flush()
    # Reload query-derived ST_Y/ST_X attributes for immediate API serialization.
    session.refresh(device)

    if latest_history is not None and latest_history.effective_to is None:
        latest_history.effective_to = changed_at
        session.add(latest_history)

    if new_pair is not None:
        new_latitude, new_longitude = new_pair
        session.add(
            models.DeviceLocationHistory(
                device_id=device.device_id,
                location=_point_storage_value(
                    session, new_latitude, new_longitude
                ),
                effective_from=changed_at,
                effective_to=None,
            )
        )
        session.flush()
    return True
