import json
import runpy
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app
from api.routes import version as version_routes


def test_native_version_loads_without_docker_metadata(tmp_path):
    repository = Path(__file__).resolve().parents[2]
    backend = tmp_path / "backend"
    frontend = tmp_path / "frontend"
    backend.mkdir()
    frontend.mkdir()
    (frontend / "package.json").write_bytes((repository / "frontend" / "package.json").read_bytes())
    source = backend / "build_identity.py"
    source.write_bytes((repository / "backend" / "build_identity.py").read_bytes())

    identity = runpy.run_path(str(source))

    assert identity["APPLICATION_VERSION"] == json.loads((frontend / "package.json").read_text())["version"]
    assert identity["BACKEND_BUILD"] == {"commit_sha": None, "build_time_utc": None}
    assert not (backend / "application-package.json").exists()
    assert not (backend / "build-metadata.json").exists()


def test_version_is_public_uncached_and_uses_shared_release_version(monkeypatch):
    monkeypatch.setattr(version_routes, "BACKEND_BUILD", {"commit_sha": "a" * 40, "build_time_utc": "2026-10-18T20:00:00Z"})
    monkeypatch.setenv("COMPASSAQ_ENV", "production")
    response = TestClient(app).get("/version")
    package = Path(__file__).resolve().parents[2] / "frontend" / "package.json"
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "application_version": json.loads(package.read_text())["version"],
        "backend": {"commit_sha": "a" * 40, "build_time_utc": "2026-10-18T20:00:00Z"},
        "environment": "production",
    }
    assert app.version == response.json()["application_version"]


def test_unknown_metadata_and_environment_are_explicit_and_not_generated(monkeypatch):
    monkeypatch.setattr(version_routes, "BACKEND_BUILD", {"commit_sha": None, "build_time_utc": None})
    monkeypatch.setenv("COMPASSAQ_ENV", "private-host-configuration")
    monkeypatch.setenv("COMPASSAQ_BUILD_SHA", "b" * 40)
    client = TestClient(app)
    first = client.get("/version")
    assert first.json()["backend"] == {"commit_sha": None, "build_time_utc": None}
    assert first.json()["environment"] is None
    assert client.get("/version").json() == first.json()
    assert "private-host" not in first.text


def test_version_does_not_weaken_admin_authentication():
    client = TestClient(app)
    assert client.get("/version").status_code == 200
    assert client.get("/admin/system-preferences").status_code == 401
