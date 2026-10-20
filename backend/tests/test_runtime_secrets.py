from __future__ import annotations

from cryptography.fernet import Fernet

from services.runtime_secrets import (
    get_or_create_encryption_key,
    get_or_create_jwt_secret,
    runtime_data_dir,
)


def test_runtime_data_dir_accepts_explicit_override(tmp_path) -> None:
    environment = {"COMPASSAQ_DATA_DIR": str(tmp_path / "runtime")}
    assert runtime_data_dir(environment) == tmp_path / "runtime"


def test_jwt_secret_is_generated_once_and_reused(tmp_path) -> None:
    environment = {"COMPASSAQ_DATA_DIR": str(tmp_path)}

    first = get_or_create_jwt_secret(environment)
    second = get_or_create_jwt_secret(environment)

    assert first
    assert first == second
    assert (tmp_path / "jwt_secret").read_text(encoding="utf-8").strip() == first


def test_encryption_key_is_generated_once_and_is_valid_fernet_key(tmp_path) -> None:
    environment = {"COMPASSAQ_DATA_DIR": str(tmp_path)}

    first = get_or_create_encryption_key(environment)
    second = get_or_create_encryption_key(environment)

    assert first == second
    Fernet(first.encode("ascii"))
    assert (tmp_path / "encryption_key").read_text(encoding="utf-8").strip() == first
