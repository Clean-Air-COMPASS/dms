from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from pathlib import Path
from typing import Callable

from cryptography.fernet import Fernet


DATA_DIR_ENVIRONMENT_VARIABLE = "COMPASSAQ_DATA_DIR"


def runtime_data_dir(environment: Mapping[str, str] | None = None) -> Path:
    """Return CompassAQ's platform-neutral runtime-data directory."""
    source = environment if environment is not None else os.environ
    configured = (source.get(DATA_DIR_ENVIRONMENT_VARIABLE) or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".compassaq"


def _read_or_create_secret(
    filename: str,
    generator: Callable[[], str],
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    directory = runtime_data_dir(environment)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename

    try:
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    except FileNotFoundError:
        pass

    value = generator()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        existing = path.read_text(encoding="utf-8").strip()
        if not existing:
            raise RuntimeError(f"CompassAQ runtime secret file is empty: {path}")
        return existing

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.write("\n")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except Exception:
        try:
            path.unlink(missing_ok=True)
        finally:
            raise
    return value


def get_or_create_jwt_secret(environment: Mapping[str, str] | None = None) -> str:
    return _read_or_create_secret(
        "jwt_secret",
        lambda: secrets.token_urlsafe(64),
        environment=environment,
    )


def get_or_create_encryption_key(environment: Mapping[str, str] | None = None) -> str:
    return _read_or_create_secret(
        "encryption_key",
        lambda: Fernet.generate_key().decode("ascii"),
        environment=environment,
    )
