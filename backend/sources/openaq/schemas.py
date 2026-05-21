from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime


class DateTimePair(BaseModel):
    utc: datetime
    local: datetime


class ParameterInfo(BaseModel):
    id: int
    name: str
    units: str
    displayName: str


class PeriodInfo(BaseModel):
    label: str
    interval: str
    datetimeFrom: DateTimePair
    datetimeTo: DateTimePair


class Coordinates(BaseModel):
    latitude: float
    longitude: float


class Summary(BaseModel):
    min: float
    q02: float
    q25: float
    median: float
    q75: float
    q98: float
    max: float
    avg: float
    sd: float


class CoverageDateRange(BaseModel):
    utc: datetime
    local: datetime


class Coverage(BaseModel):
    expectedCount: int
    expectedInterval: str
    observedCount: int
    observedInterval: str
    percentComplete: float
    percentCoverage: float
    datetimeFrom: CoverageDateRange
    datetimeTo: CoverageDateRange


class ResultItem(BaseModel):
    value: float
    flagInfo: dict
    parameter: ParameterInfo
    period: PeriodInfo
    coordinates: Coordinates
    summary: Summary
    coverage: Coverage


class MetaInfo(BaseModel):
    name: str
    website: str
    page: int
    limit: int


class OpenAQMeasurementsResponse(BaseModel):
    meta: MetaInfo
    results: List[ResultItem]


__all__ = [
    "DateTimePair",
    "ParameterInfo",
    "PeriodInfo",
    "Coordinates",
    "Summary",
    "Coverage",
    "ResultItem",
    "MetaInfo",
    "OpenAQMeasurementsResponse",
]
