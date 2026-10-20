"""Small PostgreSQL advisory-lock helpers shared by scheduled work."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine


def try_advisory_lock(connection: Connection, key: int) -> bool:
    acquired = connection.execute(
        text("SELECT pg_try_advisory_lock(:key)"),
        {"key": key},
    ).scalar()
    connection.commit()
    return bool(acquired)


def advisory_unlock(connection: Connection, key: int) -> None:
    try:
        connection.execute(
            text("SELECT pg_advisory_unlock(:key)"),
            {"key": key},
        )
        connection.commit()
    except Exception:
        # Closing the connection also releases session-level advisory locks.
        # Unlock errors must not hide the outcome of the scheduled work.
        pass


@contextmanager
def postgres_advisory_lock(engine: Engine, key: int) -> Iterator[bool]:
    """Hold one session-level advisory lock on a dedicated connection."""
    connection = engine.connect()
    try:
        acquired = try_advisory_lock(connection, key)
        yield acquired
    finally:
        if "acquired" in locals() and acquired:
            advisory_unlock(connection, key)
        connection.close()
