"""Controlled values for source-provided measurement metadata.

These values describe how a stored source measurement was produced. They do
not establish regulatory-monitor qualification or AQI input eligibility.
"""

from enum import Enum


class MeasurementTimestampSemantics(str, Enum):
    """Supported meanings for a source measurement timestamp."""

    OBSERVATION_INSTANT = "observation_instant"
    INTERVAL_START = "interval_start"
    INTERVAL_END = "interval_end"
    PROVIDER_RECEIVED_AT = "provider_received_at"


class MeasurementMetadataStatus(str, Enum):
    """Verification state for source measurement metadata."""

    PROVIDER_DOCUMENTED = "provider_documented"


class MeasurementMetadataManager(str, Enum):
    """Importer that owns and reconciles provider-assigned metadata."""

    PURPLEAIR_IMPORTER = "purpleair_importer"
