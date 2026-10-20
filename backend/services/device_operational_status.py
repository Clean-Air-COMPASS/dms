from __future__ import annotations

from datetime import datetime, timezone
from typing import Final, Literal


DeviceOperationalStatus = Literal["active", "inactive", "unknown"]

# A device should not become inactive because one importer run was delayed. Six
# hours also matches the scheduler's maximum default importer runtime while still
# identifying a stopped hourly or high-frequency stream within the same day.
MINIMUM_FRESHNESS_ALLOWANCE_SECONDS: Final = 6 * 60 * 60
EXPECTED_FREQUENCY_ALLOWANCE_MULTIPLIER: Final = 3

# Some provider metadata does not include a defensible expected cadence. A
# two-day threshold is deliberately conservative for those measured devices and
# is independent of the Devices page's separate recency controls.
MISSING_FREQUENCY_FALLBACK_SECONDS: Final = 48 * 60 * 60


def device_freshness_threshold_seconds(
    expected_frequency_seconds: int | None,
) -> int:
    """Return the provider-neutral overdue threshold for a measured device."""
    if expected_frequency_seconds is None or expected_frequency_seconds <= 0:
        return MISSING_FREQUENCY_FALLBACK_SECONDS

    cadence_allowance_seconds = (
        expected_frequency_seconds * EXPECTED_FREQUENCY_ALLOWANCE_MULTIPLIER
    )
    return max(cadence_allowance_seconds, MINIMUM_FRESHNESS_ALLOWANCE_SECONDS)


def derive_device_operational_status(
    last_seen_at: datetime | None,
    expected_frequency_seconds: int | None,
    *,
    evaluated_at: datetime | None = None,
) -> DeviceOperationalStatus:
    """Classify measurement freshness using the cadence of the latest sensor."""
    if last_seen_at is None:
        return "unknown"

    comparison_time = evaluated_at or datetime.now(timezone.utc)
    if comparison_time.tzinfo is None:
        comparison_time = comparison_time.replace(tzinfo=timezone.utc)
    if last_seen_at.tzinfo is None:
        last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)

    age_seconds = (comparison_time - last_seen_at).total_seconds()
    threshold_seconds = device_freshness_threshold_seconds(
        expected_frequency_seconds
    )
    return "active" if age_seconds <= threshold_seconds else "inactive"
