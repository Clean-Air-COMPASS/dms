from __future__ import annotations

import subprocess

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
from jobs import import_runner, scheduler


def test_scheduled_import_runtime_default_has_large_operational_margin(
    monkeypatch,
) -> None:
    monkeypatch.delenv("SCHEDULER_IMPORT_MAX_RUNTIME_SECONDS", raising=False)
    assert scheduler._scheduled_import_max_runtime_seconds() == 21_600


def test_scheduled_import_runtime_must_be_positive(monkeypatch) -> None:
    monkeypatch.setenv("SCHEDULER_IMPORT_MAX_RUNTIME_SECONDS", "0")
    with pytest.raises(ValueError, match="must be positive"):
        scheduler._scheduled_import_max_runtime_seconds()


def test_importer_timeout_is_returned_as_explicit_scheduler_outcome(
    tmp_path,
    monkeypatch,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'timeout.sqlite'}")
    models.Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        session.add(
            models.ExternalAPI(
                provider_code="openaq",
                name="OpenAQ",
                api_key="configured-key",
                params={},
                enabled=True,
            )
        )
        session.commit()

    monkeypatch.setattr(import_runner, "SessionLocal", SessionLocal)
    monkeypatch.setenv("COMPASSAQ_ENV", "development")
    monkeypatch.setenv("COMPASSAQ_TMP_DIR", str(tmp_path))
    monkeypatch.setattr(
        import_runner.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd=kwargs.get("args", args[0]), timeout=21_600)
        ),
    )

    with pytest.raises(import_runner.ImporterTimedOut) as error:
        import_runner.run_importer(
            42,
            {},
            "openaq_import",
            timeout_seconds=21_600,
        )

    assert error.value.timeout_seconds == 21_600
    assert "21600-second maximum runtime" in str(error.value)
