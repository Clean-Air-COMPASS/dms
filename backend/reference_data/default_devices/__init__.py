"""Permanent fresh-install reference-device bootstrap."""

from .bootstrap import (
    DEFAULT_REFERENCE_DEVICES_VERSION,
    initialize_default_reference_devices,
    restore_missing_default_reference_devices,
)

__all__ = [
    "DEFAULT_REFERENCE_DEVICES_VERSION",
    "initialize_default_reference_devices",
    "restore_missing_default_reference_devices",
]
