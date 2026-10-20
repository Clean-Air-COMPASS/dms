"""Resolution rules for private restricted reference datasets."""
from __future__ import annotations

import os
from pathlib import Path

from reference_data.fixture_io import ReferenceFixtureError


def restricted_data_root() -> Path | None:
    configured = os.getenv("COMPASSAQ_RESTRICTED_REFERENCE_DATA_ROOT", "").strip()
    return Path(configured).expanduser().resolve() if configured else None


def resolve_restricted_data_root(*, checked_in_fallback: Path | None = None) -> Path | None:
    """Resolve private data before an optional checked-in development fallback.

    Production and private CI callers should configure the private root.  The
    fallback exists only so repositories that intentionally include a
    restricted fixture can run the same offline tests without changing the
    resolution order.
    """
    configured_root = restricted_data_root()
    required = os.getenv("REQUIRE_RESTRICTED_REFERENCE_DATA", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }
    if configured_root is not None and configured_root.exists():
        return configured_root
    if checked_in_fallback is not None:
        fallback_root = checked_in_fallback.expanduser().resolve()
        if fallback_root.exists():
            return fallback_root
    if required:
        raise ReferenceFixtureError(
            "Restricted reference data is required but neither the configured "
            "COMPASSAQ_RESTRICTED_REFERENCE_DATA_ROOT nor the checked-in fallback "
            "is available"
        )
    return None


def require_restricted_data_if_configured() -> Path | None:
    """Retain the existing configured-root-only behavior for current callers."""
    return resolve_restricted_data_root()
