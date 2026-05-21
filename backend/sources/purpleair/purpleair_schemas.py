from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class Sensor(BaseModel):
    sensor_index: int
    name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    last_seen: Optional[int] = Field(default=None, description="Epoch seconds")
    pm2_5_atm: Optional[float] = None
    pm2_5_cf_1: Optional[float] = None
    humidity: Optional[float] = None
    temperature: Optional[float] = None
    channel_state: Optional[int] = None


class SensorsResponse(BaseModel):
    api_version: Optional[str] = None
    time_stamp: Optional[int] = None
    data_time_stamp: Optional[int] = None
    sensors: List[Sensor] = []


class SingleSensorResponse(BaseModel):
    api_version: Optional[str] = None
    time_stamp: Optional[int] = None
    data_time_stamp: Optional[int] = None
    sensor: Optional[Sensor] = None
