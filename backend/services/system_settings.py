from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session
from tzlocal import get_localzone_name

from models import SystemSettings
from services.timezone import IanaTimezoneError, resolve_iana_timezone


DEFAULT_LANGUAGE_CODE = "en"
SUPPORTED_LANGUAGE_CODES = frozenset({"en", "es"})
DEFAULT_SYSTEM_TIMEZONE = "UTC"
SYSTEM_TIMEZONE_ENV_VAR = "SYSTEM_TIMEZONE"


def resolve_default_language_code(value: str | None) -> str:
    """Return the saved language when supported, otherwise safe English.

    Language is an independent display preference. Missing or malformed legacy
    values must never change whether first-run setup is complete.
    """
    if value in SUPPORTED_LANGUAGE_CODES:
        return str(value)
    return DEFAULT_LANGUAGE_CODE


def _valid_iana_timezone_name(value: str | None) -> str | None:
    """Return a normalized IANA timezone name, or None when unusable."""
    if not value or not str(value).strip():
        return None
    try:
        return resolve_iana_timezone(
            str(value), field_label="System timezone"
        ).key
    except IanaTimezoneError:
        return None


def detect_initial_system_timezone() -> str:
    """Resolve the timezone used only when system settings are first created.

    An explicit SYSTEM_TIMEZONE environment value wins. Otherwise tzlocal
    performs cross-platform host/container detection (including Windows ID to
    IANA mapping). Invalid or unavailable values fall back safely to UTC.
    """
    configured_timezone = _valid_iana_timezone_name(
        os.environ.get(SYSTEM_TIMEZONE_ENV_VAR)
    )
    if configured_timezone is not None:
        return configured_timezone

    try:
        detected_timezone = _valid_iana_timezone_name(get_localzone_name())
    except Exception:
        detected_timezone = None

    return detected_timezone or DEFAULT_SYSTEM_TIMEZONE


def get_or_create_system_settings(session: Session) -> SystemSettings:
    """
    Load the singleton system settings row.

    The table is intended to hold one platform-wide configuration row.
    If the row does not exist yet, create it so callers can safely read
    and update settings without duplicating initialization logic. The initial
    timezone is detected once; saved administrator settings remain authoritative
    after creation and do not track later OS timezone changes.
    """
    settings = session.scalar(
        select(SystemSettings).order_by(SystemSettings.system_settings_id).limit(1)
    )
    if settings is None:
        settings = SystemSettings(
            default_language_code=DEFAULT_LANGUAGE_CODE,
            system_timezone=detect_initial_system_timezone(),
        )
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings


def is_system_setup_complete(session: Session) -> bool:
    """Read the persisted installation-level setup marker.

    No language, user, browser, environment, or container state participates
    in this decision. A missing settings row is a genuine fresh installation.
    """
    setup_complete = session.scalar(
        select(SystemSettings.is_system_setup_complete)
        .order_by(SystemSettings.system_settings_id)
        .limit(1)
    )
    return setup_complete is True


def get_system_timezone(session: Session) -> str:
    """Return the saved system timezone, or UTC for schema-light test stores."""
    system_timezone = session.scalar(select(SystemSettings.system_timezone))
    return str(system_timezone or DEFAULT_SYSTEM_TIMEZONE)
