from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional
import os

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from models import Device, Sensor, Measurement, Parameter


PM25_CODE = "pm25"

                  
                                                                              
                                                                             
                                                                          
           

                                                                                  
                                                                                    
                                                                                   
DEFAULT_MIN_HOURS = int(os.getenv("PM25_MIN_HOURS", "18"))


def _normalize_end(end_time: Optional[datetime]) -> datetime:
    if end_time is None:
        return datetime.now(timezone.utc)
    if end_time.tzinfo is None:
        return end_time.replace(tzinfo=timezone.utc)
    return end_time.astimezone(timezone.utc)


def get_pm25_rolling_24h_avg(session: Session, device_id: int, end_time: Optional[datetime] = None, min_hours: Optional[int] = None) -> Optional[float]:
    end_utc = _normalize_end(end_time)
    start_utc = end_utc - timedelta(hours=24)
                                                                                                    
    effective_min_hours = 0

    sql = text(
        "WITH hourly AS ("
        " SELECT m.sensor_id, date_trunc('hour', m.observed_at) AS hr, avg(m.value) AS hr_avg"
        " FROM measurement m"
        " JOIN sensor s ON m.sensor_id = s.sensor_id"
        " JOIN parameter p ON s.parameter_id = p.parameter_id"
        " WHERE s.device_id = :device_id AND p.code = :pcode AND m.is_valid = true AND m.observed_at >= :start AND m.observed_at < :end"
        " GROUP BY m.sensor_id, hr"
        "), sensor_avg AS ("
        " SELECT sensor_id, avg(hr_avg) AS sensor_avg, count(*) AS n_hours FROM hourly GROUP BY sensor_id HAVING count(*) >= :min_hours"
        ") SELECT avg(sensor_avg) AS device_avg, sum(n_hours) AS total_hours, count(*) AS contributing_sensors FROM sensor_avg"
    )

    row = session.execute(sql, {"device_id": device_id, "pcode": PM25_CODE, "start": start_utc, "end": end_utc, "min_hours": effective_min_hours}).first()
    if not row or row[0] is None:
        return None
    return float(row[0])


def get_pm25_daily_24h_avg(session: Session, device_id: int, local_date: datetime, min_hours: Optional[int] = None) -> Optional[float]:
    tz_row = session.execute(select(Device.timezone).where(Device.device_id == device_id)).first()
    if not tz_row or not tz_row[0]:
        return None
    tz_name: str = tz_row[0]

    local_day = local_date.date()
                                                                                                    
    effective_min_hours = 0

                                                                                                
                                                                                          
                                           
    sql = text(
        "WITH hourly AS ("
        " SELECT m.sensor_id, date_trunc('hour', (m.observed_at AT TIME ZONE :tz)) AS hr_local, avg(m.value) AS hr_avg"
        " FROM measurement m"
        " JOIN sensor s ON m.sensor_id = s.sensor_id"
        " JOIN parameter p ON s.parameter_id = p.parameter_id"
        " WHERE s.device_id = :device_id AND p.code = :pcode AND m.is_valid = true AND date_trunc('day', (m.observed_at AT TIME ZONE :tz)) = :local_day"
        " GROUP BY m.sensor_id, hr_local"
        "), sensor_avg AS ("
        " SELECT sensor_id, avg(hr_avg) AS sensor_avg, count(*) AS n_hours FROM hourly GROUP BY sensor_id HAVING count(*) >= :min_hours"
        ") SELECT avg(sensor_avg) AS device_avg, sum(n_hours) AS total_hours, count(*) AS contributing_sensors FROM sensor_avg"
    )

    row = session.execute(sql, {"device_id": device_id, "pcode": PM25_CODE, "tz": tz_name, "local_day": local_day, "min_hours": effective_min_hours}).first()
    if not row or row[0] is None:
        return None
    return float(row[0])
