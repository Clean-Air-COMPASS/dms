"""Transport helpers for the two administrator operational history lists."""

from datetime import datetime, timezone
from typing import Generic, TypeVar

from fastapi import HTTPException
from pydantic import BaseModel

T = TypeVar("T")


class HistoryPage(BaseModel, Generic[T]):
    items: list[T]
    total: int
    options: dict[str, list[str]]


def history_bounds(after: datetime | None, before: datetime | None):
    for value in (after, before):
        if value is not None and value.utcoffset() is None:
            raise HTTPException(422, detail={"error_code": "history_timezone_required"})
    if after is not None and before is not None and after >= before:
        raise HTTPException(422, detail={"error_code": "history_invalid_range"})
    return tuple(value.astimezone(timezone.utc) if value else None for value in (after, before))
