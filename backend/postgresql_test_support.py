from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
from typing import Iterator
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL, make_url


BACKEND_ROOT = Path(__file__).resolve().parent
POSTGRES_TEST_URL_ENV = "COMPASSAQ_POSTGRES_TEST_URL"


def postgres_test_url() -> URL:
    raw_url = os.environ.get(POSTGRES_TEST_URL_ENV)
    if not raw_url:
        raise RuntimeError(
            f"Set {POSTGRES_TEST_URL_ENV} to run PostgreSQL/PostGIS tests."
        )
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError(f"{POSTGRES_TEST_URL_ENV} must be a PostgreSQL URL")
    return url


@contextmanager
def temporary_postgres_database(prefix: str) -> Iterator[tuple[URL, Engine]]:
    base_url = postgres_test_url()
    database_name = f"compassaq_{prefix}_{uuid4().hex}"
    admin_url = base_url.set(database="postgres")
    test_url = base_url.set(database=database_name)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    test_engine: Engine | None = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        test_engine = create_engine(test_url)
        yield test_url, test_engine
    finally:
        if test_engine is not None:
            test_engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()


def _run_alembic(database_url: URL, action: str, revision: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url.render_as_string(
        hide_password=False
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", action, revision],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)


def upgrade(database_url: URL, revision: str = "head") -> None:
    _run_alembic(database_url, "upgrade", revision)


def downgrade(database_url: URL, revision: str) -> None:
    _run_alembic(database_url, "downgrade", revision)
