from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from services.runtime_secrets import runtime_data_dir


STORAGE_PATH_ENVIRONMENT_VARIABLE: Final = "COMPASSAQ_STORAGE_PATH"
STORAGE_ATTENTION_PERCENT_FREE: Final = 15.0
STORAGE_CRITICAL_PERCENT_FREE: Final = 5.0


@dataclass(frozen=True)
class StorageStatus:
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent_free: float
    status: str

    @property
    def needs_attention(self) -> bool:
        return self.status in {"needs_attention", "critical"}


def storage_path(environment: Mapping[str, str] | None = None) -> Path:
    """Return the filesystem path used to evaluate CompassAQ storage capacity.

    The default is the platform-neutral CompassAQ runtime-data directory. Docker
    places that directory on a persistent named volume, which is backed by the
    same host storage used by the default database volume. Advanced deployments
    may point COMPASSAQ_STORAGE_PATH at another persistent filesystem.
    """
    source = environment if environment is not None else os.environ
    configured = (source.get(STORAGE_PATH_ENVIRONMENT_VARIABLE) or "").strip()
    if configured:
        return Path(configured).expanduser()
    return runtime_data_dir(source)


def _status_for_percent_free(percent_free: float) -> str:
    if percent_free < STORAGE_CRITICAL_PERCENT_FREE:
        return "critical"
    if percent_free < STORAGE_ATTENTION_PERCENT_FREE:
        return "needs_attention"
    return "healthy"


def get_storage_status(
    environment: Mapping[str, str] | None = None,
) -> StorageStatus:
    """Measure free space using Python's OS-neutral filesystem API."""
    path = storage_path(environment)
    path.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(path)
    percent_free = (usage.free / usage.total * 100.0) if usage.total else 0.0
    return StorageStatus(
        total_bytes=int(usage.total),
        used_bytes=int(usage.used),
        free_bytes=int(usage.free),
        percent_free=round(percent_free, 1),
        status=_status_for_percent_free(percent_free),
    )
