from __future__ import annotations
from typing import List, Optional, Union
from pydantic import BaseModel


class DateTimeObj(BaseModel):
    utc: Optional[str] = None


class LatestObj(BaseModel):
    value: Optional[float] = None
    datetime: Optional[DateTimeObj] = None
                                                     
    date: Optional[DateTimeObj] = None


class ParameterObj(BaseModel):
    id: Optional[Union[int, str]] = None
    name: Optional[str] = None
    units: Optional[str] = None
    displayName: Optional[str] = None


class SensorModel(BaseModel):
    id: Optional[Union[int, str]] = None
    sensorId: Optional[Union[int, str]] = None
    name: Optional[str] = None
    parameter: Optional[ParameterObj] = None
    latest: Optional[LatestObj] = None
    locationId: Optional[Union[int, str]] = None
    locationsId: Optional[List[Union[int, str]]] = None
    coverage: Optional["Coverage"] = None


class SensorResponse(BaseModel):
    results: List[SensorModel] = []


class ParameterMeasurement(BaseModel):
    parameter: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    lastUpdated: Optional[str] = None
    lastUpdatedUtc: Optional[str] = None
                        
    lastValue: Optional[float] = None
    id: Optional[Union[int, str]] = None


class LocationResult(BaseModel):
    id: Optional[Union[int, str]] = None
    name: Optional[str] = None
    location: Optional[str] = None
    coordinates: Optional[dict] = None
    parameters: List[ParameterMeasurement] = []
    measurements: List[ParameterMeasurement] = []


class LocationLatestResponse(BaseModel):
    results: List[LocationResult] = []


                                                                  
class DateTimePair(BaseModel):
    utc: Optional[str] = None
    local: Optional[str] = None


class ParameterInfo(BaseModel):
    id: Optional[Union[int, str]] = None
    name: Optional[str] = None
    units: Optional[str] = None
    displayName: Optional[str] = None


class PeriodInfo(BaseModel):
    label: Optional[str] = None
    interval: Optional[str] = None
    datetimeFrom: Optional[DateTimePair] = None
    datetimeTo: Optional[DateTimePair] = None


class Coordinates(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class Summary(BaseModel):
    min: Optional[float] = None
    q02: Optional[float] = None
    q25: Optional[float] = None
    median: Optional[float] = None
    q75: Optional[float] = None
    q98: Optional[float] = None
    max: Optional[float] = None
    avg: Optional[float] = None
    sd: Optional[float] = None


class CoverageRange(BaseModel):
    utc: Optional[str] = None
    local: Optional[str] = None


class Coverage(BaseModel):
    expectedCount: Optional[int] = None
    expectedInterval: Optional[str] = None
    observedCount: Optional[int] = None
    observedInterval: Optional[str] = None
    percentComplete: Optional[float] = None
    percentCoverage: Optional[float] = None
    datetimeFrom: Optional[CoverageRange] = None
    datetimeTo: Optional[CoverageRange] = None


class MeasurementResult(BaseModel):
    value: Optional[float] = None
    flagInfo: Optional[dict] = None
    parameter: Optional[ParameterInfo] = None
    period: Optional[PeriodInfo] = None
    coordinates: Optional[Coordinates] = None
    summary: Optional[Summary] = None
    coverage: Optional[Coverage] = None


class MetaInfo(BaseModel):
    name: Optional[str] = None
    website: Optional[str] = None
    page: Optional[int] = None
    limit: Optional[int] = None


class OpenAQMeasurementsResponse(BaseModel):
    meta: Optional[MetaInfo] = None
    results: List[MeasurementResult] = []
