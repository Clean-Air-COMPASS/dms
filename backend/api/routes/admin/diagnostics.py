from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from db import get_session
from models import Device, Sensor, Measurement, Parameter, MeasurementQCResult, JobRun, JobSchedule

router = APIRouter(prefix="/admin", tags=["admin"]) 


@router.get("/diagnostics/location_migration")
def location_migration_diagnostics(session: Session = Depends(get_session)):
    """Report Phase 2 migration diagnostics.

    - Count devices with/without external_id
    - Count devices with/without coordinates
    - Count legacy Location-linkage usage (devices with non-null location_id)
    - Totals for sensors and measurements
    """
    try:
        devices_total = session.scalar(select(func.count()).select_from(Device)) or 0
        devices_with_ext = session.scalar(select(func.count()).select_from(Device).where(Device.external_id != None)) or 0
        devices_with_lat = session.scalar(select(func.count()).select_from(Device).where(Device.latitude != None)) or 0
        devices_with_lon = session.scalar(select(func.count()).select_from(Device).where(Device.longitude != None)) or 0
        devices_with_coords = session.scalar(
            select(func.count()).select_from(Device).where((Device.latitude != None) & (Device.longitude != None))
        ) or 0
        devices_missing_coords = devices_total - devices_with_coords
                                                                      
        devices_with_location_id = 0
        location_link_removed = True
        try:
                                                                         
            _ = getattr(Device, 'location_id')
            location_link_removed = False
            devices_with_location_id = session.scalar(
                select(func.count()).select_from(Device).where(getattr(Device, 'location_id') != None)
            ) or 0
        except AttributeError:
            devices_with_location_id = 0
            location_link_removed = True
        sensors_total = session.scalar(select(func.count()).select_from(Sensor)) or 0
        measurements_total = session.scalar(select(func.count()).select_from(Measurement)) or 0

        return {
            "devices": {
                "total": int(devices_total),
                "with_external_id": int(devices_with_ext),
                "with_latitude": int(devices_with_lat),
                "with_longitude": int(devices_with_lon),
                "with_coords": int(devices_with_coords),
                "missing_coords": int(devices_missing_coords),
                "with_location_id": int(devices_with_location_id),
                "location_link_removed": bool(location_link_removed),
            },
            "sensors": {"total": int(sensors_total)},
            "measurements": {"total": int(measurements_total)},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/diagnostics/summary")
def diagnostics_summary(session: Session = Depends(get_session)):
    """Summarize data flow and QC metrics for quick admin checks.

    Returns counts, ingest lag (overall and per-parameter), QC rates over the last 24h,
    and the most recent job runs.
    """
    try:
        now = datetime.now(timezone.utc)
        last_24h = now - timedelta(hours=24)

        devices_total = session.scalar(select(func.count()).select_from(Device)) or 0
        sensors_total = session.scalar(select(func.count()).select_from(Sensor)) or 0
        measurements_total = session.scalar(select(func.count()).select_from(Measurement)) or 0

                                            
        latest_obs = session.scalar(select(func.max(Measurement.observed_at)))
        latest_obs_iso = latest_obs.isoformat() if latest_obs else None
        lag_minutes = None
        if latest_obs:
            try:
                latest_dt = latest_obs
                if latest_dt.tzinfo is None:
                    latest_dt = latest_dt.replace(tzinfo=timezone.utc)
                lag_minutes = int(max(0, (now - latest_dt).total_seconds() // 60))
            except Exception:
                lag_minutes = None

                                                  
        rows = session.execute(
            select(Parameter.code, func.max(Measurement.observed_at))
            .join(Sensor, Sensor.parameter_id == Parameter.parameter_id)
            .join(Measurement, Measurement.sensor_id == Sensor.sensor_id)
            .group_by(Parameter.code)
        ).all()
        per_param = []
        for code, dt in rows:
            iso = dt.isoformat() if dt else None
            lag = None
            if dt:
                try:
                    dtt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                    lag = int(max(0, (now - dtt).total_seconds() // 60))
                except Exception:
                    lag = None
            per_param.append({"code": code, "latest_observed_at": iso, "lag_minutes": lag})

                                
        valid_24h = session.scalar(
            select(func.count()).select_from(Measurement).where(
                Measurement.observed_at >= last_24h, Measurement.is_valid == True              
            )
        ) or 0
        invalid_24h = session.scalar(
            select(func.count()).select_from(Measurement).where(
                Measurement.observed_at >= last_24h, Measurement.is_valid == False              
            )
        ) or 0
        total_24h = valid_24h + invalid_24h
        pct_valid_24h = (float(valid_24h) / float(total_24h) * 100.0) if total_24h > 0 else None

        fail_rows = session.execute(
            select(MeasurementQCResult.check_code, func.count())
            .where(
                MeasurementQCResult.passed == False,              
                MeasurementQCResult.created_at >= last_24h,
            )
            .group_by(MeasurementQCResult.check_code)
        ).all()
        failures_by_check = {str(code): int(cnt) for code, cnt in fail_rows}

                                                
        last_runs = []
        jr_rows = session.execute(
            select(JobSchedule.task, JobRun.status, JobRun.started_at, JobRun.finished_at)
            .join(JobRun, JobRun.job_schedule_id == JobSchedule.job_schedule_id)
            .order_by(JobRun.started_at.desc())
            .limit(5)
        ).all()
        for task, status, started, finished in jr_rows:
            last_runs.append(
                {
                    "task": task,
                    "status": status,
                    "started_at": started.isoformat() if started else None,
                    "finished_at": finished.isoformat() if finished else None,
                }
            )

        return {
            "counts": {
                "devices": int(devices_total),
                "sensors": int(sensors_total),
                "measurements": int(measurements_total),
            },
            "ingest": {
                "latest_observed_at": latest_obs_iso,
                "lag_minutes": lag_minutes,
                "per_parameter": per_param,
            },
            "qc": {
                "last_24h": {
                    "valid": int(valid_24h),
                    "invalid": int(invalid_24h),
                    "total": int(total_24h),
                    "pct_valid": pct_valid_24h,
                    "failures_by_check": failures_by_check,
                }
            },
            "jobs": {"last_runs": last_runs},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
