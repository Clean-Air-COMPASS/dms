"""Small helpers for validating persisted IANA timezone names."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class IanaTimezoneError(ValueError):
    """Raised when a configured value is not a usable IANA timezone."""


def resolve_iana_timezone(value: str, *, field_label: str = "Timezone") -> ZoneInfo:
    """Validate and return one persisted IANA timezone as a ``ZoneInfo``."""
    normalized_name = str(value or "").strip()
    if not normalized_name:
        raise IanaTimezoneError(f"{field_label} is required")
    try:
        return ZoneInfo(normalized_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise IanaTimezoneError(
            f"{field_label} '{normalized_name}' is not a valid IANA timezone"
        ) from exc
