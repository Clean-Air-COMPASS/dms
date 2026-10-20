from __future__ import annotations

from types import SimpleNamespace

from services import system_storage


def test_storage_path_defaults_to_runtime_data_dir(tmp_path):
    path = system_storage.storage_path({"COMPASSAQ_DATA_DIR": str(tmp_path)})
    assert path == tmp_path


def test_storage_path_allows_explicit_override(tmp_path):
    override = tmp_path / "storage"
    path = system_storage.storage_path(
        {
            "COMPASSAQ_DATA_DIR": str(tmp_path / "runtime"),
            "COMPASSAQ_STORAGE_PATH": str(override),
        }
    )
    assert path == override


def test_storage_status_healthy(monkeypatch, tmp_path):
    monkeypatch.setattr(
        system_storage.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=1000, used=700, free=300),
    )

    status = system_storage.get_storage_status({"COMPASSAQ_DATA_DIR": str(tmp_path)})

    assert status.total_bytes == 1000
    assert status.used_bytes == 700
    assert status.free_bytes == 300
    assert status.percent_free == 30.0
    assert status.status == "healthy"
    assert status.needs_attention is False


def test_storage_status_needs_attention(monkeypatch, tmp_path):
    monkeypatch.setattr(
        system_storage.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=1000, used=900, free=100),
    )

    status = system_storage.get_storage_status({"COMPASSAQ_DATA_DIR": str(tmp_path)})

    assert status.percent_free == 10.0
    assert status.status == "needs_attention"
    assert status.needs_attention is True


def test_storage_status_critical(monkeypatch, tmp_path):
    monkeypatch.setattr(
        system_storage.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=1000, used=960, free=40),
    )

    status = system_storage.get_storage_status({"COMPASSAQ_DATA_DIR": str(tmp_path)})

    assert status.percent_free == 4.0
    assert status.status == "critical"
    assert status.needs_attention is True
