from __future__ import annotations

from sqlalchemy.orm import Session

from models import SystemSettings


def get_or_create_system_settings(session: Session) -> SystemSettings:
    """
    Load the singleton system settings row.

    The table is intended to hold one platform-wide configuration row.
    If the row does not exist yet, create it so callers can safely read
    and update settings without duplicating initialization logic.
    """
    settings = session.query(SystemSettings).first()
    if settings is None:
        settings = SystemSettings()
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings
