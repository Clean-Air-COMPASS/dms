from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from api.main import app
from api.routes import health as health_routes


def _sqlite_engine(database_path: Path):
    return create_engine(f"sqlite+pysqlite:///{database_path}", future=True)


def _create_alembic_version(database_engine, revisions: set[str]) -> None:
    with database_engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        for revision in revisions:
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": revision},
            )


def test_readiness_succeeds_when_database_and_schema_are_ready(monkeypatch, tmp_path) -> None:
    database_engine = _sqlite_engine(tmp_path / "ready.sqlite3")
    expected_revisions = health_routes.get_expected_schema_revisions()
    _create_alembic_version(database_engine, expected_revisions)
    monkeypatch.setattr(health_routes, "engine", database_engine)

    response = TestClient(app).get("/health/readiness")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_is_not_ready_when_database_is_unavailable(monkeypatch) -> None:
    class UnavailableDatabaseEngine:
        def connect(self):
            raise RuntimeError("database password must never be exposed")

    monkeypatch.setattr(health_routes, "engine", UnavailableDatabaseEngine())

    response = TestClient(app, raise_server_exceptions=False).get("/health/readiness")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert "password" not in response.text


def test_readiness_is_not_ready_when_schema_revision_is_missing(monkeypatch, tmp_path) -> None:
    database_engine = _sqlite_engine(tmp_path / "old-schema.sqlite3")
    _create_alembic_version(database_engine, {"outdated_revision"})
    monkeypatch.setattr(health_routes, "engine", database_engine)

    response = TestClient(app).get("/health/readiness")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_optional_services_do_not_affect_readiness(monkeypatch, tmp_path) -> None:
    database_engine = _sqlite_engine(tmp_path / "optional-services.sqlite3")
    expected_revisions = health_routes.get_expected_schema_revisions()
    _create_alembic_version(database_engine, expected_revisions)
    monkeypatch.setattr(health_routes, "engine", database_engine)
    monkeypatch.setenv("OPENAQ_API_KEY", "")
    monkeypatch.setenv("PURPLEAIR_API_KEY", "")
    monkeypatch.setenv("AIRGRADIENT_API_TOKEN", "")
    monkeypatch.setenv("GEOAPIFY_API_KEY", "")
    monkeypatch.setenv("SMTP_HOST", "")

    response = TestClient(app).get("/health/readiness")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert set(response.json()) == {"status"}
