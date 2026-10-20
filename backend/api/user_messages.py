from __future__ import annotations

from typing import Any


def user_message_detail(
    error_code: str,
    diagnostic_message: str,
    *,
    error_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a stable presentation code while retaining diagnostic prose."""
    return {
        "error_code": error_code,
        "error_context": error_context or {},
        "message": diagnostic_message,
    }
