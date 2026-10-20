from __future__ import annotations

import os
from collections.abc import Mapping

from cryptography.fernet import Fernet, InvalidToken

from services.runtime_secrets import get_or_create_encryption_key


ENCRYPTION_KEY_ENVIRONMENT_VARIABLE = "COMPASSAQ_ENCRYPTION_KEY"


class SecretEncryptionError(RuntimeError):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


def _load_fernet(environment: Mapping[str, str] | None = None) -> Fernet:
    if environment is None:
        encryption_key = (
            (os.getenv(ENCRYPTION_KEY_ENVIRONMENT_VARIABLE) or "").strip()
            or get_or_create_encryption_key()
        )
    else:
        encryption_key = environment.get(ENCRYPTION_KEY_ENVIRONMENT_VARIABLE)
        if not encryption_key:
            raise SecretEncryptionError(
                "encryption_key_missing",
                f"{ENCRYPTION_KEY_ENVIRONMENT_VARIABLE} is not configured",
            )
    try:
        return Fernet(encryption_key.encode("ascii"))
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise SecretEncryptionError(
            "encryption_key_invalid",
            f"{ENCRYPTION_KEY_ENVIRONMENT_VARIABLE} is invalid",
        ) from exc


def encrypt_secret(
    plaintext: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    if not isinstance(plaintext, str) or plaintext == "":
        raise ValueError("Secret plaintext must be a non-empty string")
    cipher = _load_fernet(environment)
    return cipher.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(
    ciphertext: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    if not isinstance(ciphertext, str) or not ciphertext:
        raise SecretEncryptionError(
            "encrypted_secret_invalid",
            "The encrypted secret is missing or invalid",
        )
    cipher = _load_fernet(environment)
    try:
        return cipher.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise SecretEncryptionError(
            "encrypted_secret_unreadable",
            "The encrypted secret cannot be decrypted with the configured key",
        ) from exc
