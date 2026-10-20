"""Serialize compact data provenance and attribution for public API consumers."""

from __future__ import annotations

from typing import Any


def serialize_data_attribution(
    *,
    acquisition_path: str | None,
    data_provider_name: str | None,
    hardware_provider_name: str | None,
    provider_url: str | None,
    contributor_name: str | None,
    contributor_url: str | None,
    license_code: str | None,
    license_url: str | None,
    license_share_alike: bool | None,
) -> dict[str, Any] | None:
    """Return structured attribution when the device has provenance metadata."""

    if not any(
        (
            data_provider_name,
            acquisition_path and acquisition_path != "unspecified",
            hardware_provider_name,
            provider_url,
            contributor_name,
            contributor_url,
            license_code,
            license_url,
            license_share_alike is not None,
        )
    ):
        return None

    return {
        "acquisition_path": acquisition_path,
        "data_provider_name": data_provider_name,
        "hardware_provider_name": hardware_provider_name,
        "provider_url": provider_url,
        "contributor_name": contributor_name,
        "contributor_url": contributor_url,
        "license_code": license_code,
        "license_url": license_url,
        "license_share_alike": license_share_alike,
    }


def serialize_device_data_attribution(device: Any, data_provider_name: str | None) -> dict[str, Any] | None:
    """Read attribution fields from a Device-like ORM object or result row."""

    return serialize_data_attribution(
        acquisition_path=getattr(device, "acquisition_path", None),
        data_provider_name=data_provider_name,
        hardware_provider_name=getattr(device, "hardware_provider_name", None),
        provider_url=getattr(device, "provider_url", None),
        contributor_name=getattr(device, "contributor_name", None),
        contributor_url=getattr(device, "contributor_url", None),
        license_code=getattr(device, "license_code", None),
        license_url=getattr(device, "license_url", None),
        license_share_alike=getattr(device, "license_share_alike", None),
    )
