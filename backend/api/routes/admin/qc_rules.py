from __future__ import annotations

from typing import Optional, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from db import get_session
import models
from qaqc.rules import min_value as qc_min


router = APIRouter(prefix="/admin", tags=["admin"]) 


def _rule_to_dict(r: models.QCRule) -> Dict[str, Any]:
    return {
        "qc_rule_id": r.qc_rule_id,
        "check_code": r.check_code,
        "sensor_id": getattr(r, "sensor_id", None),
        "parameter_id": getattr(r, "parameter_id", None),
        "aggregate_code": getattr(r, "aggregate_code", None),
        "enabled": bool(r.enabled),
        "params": r.params or None,
        "version": getattr(r, "version", None),
        "state": getattr(r, "state", None),
        "draft_params": getattr(r, "draft_params", None),
        "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
        "updated_at": r.updated_at.isoformat() if getattr(r, "updated_at", None) else None,
    }


@router.get("/qc/rules")
def list_qc_rules(
    session: Session = Depends(get_session),
    check_code: Optional[str] = Query(default=None),
    sensor_id: Optional[int] = Query(default=None),
    parameter_id: Optional[int] = Query(default=None),
    enabled: Optional[bool] = Query(default=None),
):
    try:
        stmt = select(models.QCRule)
        conds = []
        if check_code:
            conds.append(models.QCRule.check_code == check_code)
        if sensor_id is not None:
            conds.append(models.QCRule.sensor_id == sensor_id)
        if parameter_id is not None:
            conds.append(models.QCRule.parameter_id == parameter_id)
        if enabled is not None:
            conds.append(models.QCRule.enabled == enabled)
        if conds:
            stmt = stmt.where(*conds)
        stmt = stmt.order_by(models.QCRule.qc_rule_id.desc())
        rows = session.scalars(stmt).all()
        return [_rule_to_dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/qc/rules")
def create_qc_rule(
    payload: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
):
    try:
        check_code = str(payload.get("check_code") or "").strip()
        if not check_code:
            raise HTTPException(status_code=400, detail="check_code is required")
        r = models.QCRule(
            check_code=check_code,
            sensor_id=payload.get("sensor_id"),
            parameter_id=payload.get("parameter_id"),
            aggregate_code=payload.get("aggregate_code"),
            enabled=bool(payload.get("enabled", True)),
            params=payload.get("params"),
        )
        session.add(r)
        session.flush()
        session.commit()
        return _rule_to_dict(r)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/qc/rules/{qc_rule_id}")
def update_qc_rule(
    qc_rule_id: int,
    payload: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
):
    try:
        r = session.get(models.QCRule, qc_rule_id)
        if not r:
            raise HTTPException(status_code=404, detail="Rule not found")
                                                      
        if "check_code" in payload:
            r.check_code = str(payload["check_code"]) or r.check_code
        if "sensor_id" in payload:
            r.sensor_id = payload["sensor_id"]
        if "parameter_id" in payload:
            r.parameter_id = payload["parameter_id"]
        if "aggregate_code" in payload:
            r.aggregate_code = payload["aggregate_code"]
        if "enabled" in payload:
            r.enabled = bool(payload["enabled"])
        if "params" in payload:
            r.params = payload["params"]
        session.add(r)
        session.flush()
        session.commit()
        return _rule_to_dict(r)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/qc/rules/{qc_rule_id}/draft")
def update_qc_rule_draft(
    qc_rule_id: int,
    payload: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
):
    """Update only draft_params for a rule (save draft without activating)."""
    try:
        r = session.get(models.QCRule, qc_rule_id)
        if not r:
            raise HTTPException(status_code=404, detail="Rule not found")
                                                                      
        dp = payload.get("draft_params")
        if dp is None or not isinstance(dp, dict):
            raise HTTPException(status_code=400, detail="draft_params must be an object")
        r.draft_params = dp
        r.state = "draft" if r.enabled else r.state
        session.add(r)
        session.flush()
        session.commit()
        return _rule_to_dict(r)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/qc/rules/{qc_rule_id}/activate")
def activate_qc_rule(
    qc_rule_id: int,
    session: Session = Depends(get_session),
):
    """Activate the current draft by copying draft_params into params, incrementing version, and clearing draft."""
    try:
        r = session.get(models.QCRule, qc_rule_id)
        if not r:
            raise HTTPException(status_code=404, detail="Rule not found")
        if not r.draft_params:
            raise HTTPException(status_code=400, detail="No draft_params to activate")
        r.params = r.draft_params
        r.draft_params = None
        r.version = int(getattr(r, "version", 1) or 1) + 1
        r.state = "active"
        r.enabled = True
        session.add(r)
        session.flush()
        session.commit()
        return _rule_to_dict(r)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/qc/rules/{qc_rule_id}/preview")
def preview_qc_rule(
    qc_rule_id: int,
    hours: int = Query(default=24, ge=1, le=168),
    session: Session = Depends(get_session),
):
    """Preview impact of draft parameters for min_value or max_value against recent measurements.

    Returns counts of would-pass/would-fail for the rule scope.
    """
    try:
        from datetime import datetime, timezone, timedelta
        r = session.get(models.QCRule, qc_rule_id)
        if not r:
            raise HTTPException(status_code=404, detail="Rule not found")
        if not r.draft_params:
            raise HTTPException(status_code=400, detail="No draft_params to preview")
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=hours)
                                           
        from sqlalchemy import select, and_
        m = models.Measurement
        s = models.Sensor
        stmt = select(m.value).join(s, s.sensor_id == m.sensor_id).where(m.observed_at >= since)
        if r.sensor_id is not None:
            stmt = stmt.where(m.sensor_id == r.sensor_id)
        if r.parameter_id is not None:
            stmt = stmt.where(s.parameter_id == r.parameter_id)
        values = [v for (v,) in session.execute(stmt).all()]
        threshold = None
        would_fail = 0
        would_pass = 0
        chk = r.check_code
        if chk == "min_value":
            try:
                threshold = float(r.draft_params.get("min"))
            except Exception:
                raise HTTPException(status_code=400, detail="draft_params.min must be numeric")
            for v in values:
                try:
                    vv = float(v)
                except Exception:
                    vv = None
                if vv is None or vv < threshold:
                    would_fail += 1
                else:
                    would_pass += 1
        elif chk == "max_value":
            try:
                threshold = float(r.draft_params.get("max"))
            except Exception:
                raise HTTPException(status_code=400, detail="draft_params.max must be numeric")
            for v in values:
                try:
                    vv = float(v)
                except Exception:
                    vv = None
                if vv is None or vv > threshold:
                    would_fail += 1
                else:
                    would_pass += 1
        else:
            raise HTTPException(status_code=400, detail=f"Preview not supported for check_code '{chk}'")
        return {
            "qc_rule_id": qc_rule_id,
            "check_code": chk,
            "threshold": threshold,
            "since": since.isoformat(),
            "samples": len(values),
            "would_fail": would_fail,
            "would_pass": would_pass,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/qc/rules/{qc_rule_id}")
def delete_qc_rule(qc_rule_id: int, session: Session = Depends(get_session)):
    try:
        r = session.get(models.QCRule, qc_rule_id)
        if not r:
            raise HTTPException(status_code=404, detail="Rule not found")
        session.delete(r)
        session.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/qc/rules/{qc_rule_id}/disable")
def disable_qc_rule(qc_rule_id: int, session: Session = Depends(get_session)):
    try:
        r = session.get(models.QCRule, qc_rule_id)
        if not r:
            raise HTTPException(status_code=404, detail="Rule not found")
        r.enabled = False
        session.add(r)
        session.flush()
        session.commit()
        return {"ok": True, "qc_rule_id": qc_rule_id, "enabled": False}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/qc/rules/{qc_rule_id}/enable")
def enable_qc_rule(qc_rule_id: int, session: Session = Depends(get_session)):
    try:
        r = session.get(models.QCRule, qc_rule_id)
        if not r:
            raise HTTPException(status_code=404, detail="Rule not found")
        r.enabled = True
        session.add(r)
        session.flush()
        session.commit()
        return {"ok": True, "qc_rule_id": qc_rule_id, "enabled": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/qc/effective")
def effective_qc_rule(
    session: Session = Depends(get_session),
    check_code: str = Query(default="min_value"),
    sensor_id: Optional[int] = Query(default=None),
    parameter_id: Optional[int] = Query(default=None),
    aggregate_code: str = Query(default="1h"),
):
    try:
                                                                                 
        import qaqc.plugins              

        if check_code != qc_min.CHECK_CODE:
            raise HTTPException(status_code=400, detail=f"check_code '{check_code}' not supported")

                                                                                                          
        if parameter_id is None and sensor_id is not None:
            try:
                s = session.get(models.Sensor, sensor_id)
                if s and getattr(s, "parameter_id", None) is not None:
                    parameter_id = s.parameter_id
            except Exception:
                pass

                                                      
        rules = session.scalars(
            select(models.QCRule).where(
                models.QCRule.enabled == True,              
                models.QCRule.check_code == check_code,
            )
        ).all()

        best = None
        best_score = -1
        for r in rules:
            score = 0
                                      
            if getattr(r, "sensor_id", None) is not None and sensor_id is not None and r.sensor_id == sensor_id:
                score += 4
            elif getattr(r, "sensor_id", None) is None:
                score += 1
            else:
                continue

            if r.parameter_id is not None and parameter_id is not None and r.parameter_id == parameter_id:
                score += 2
            elif r.parameter_id is None:
                score += 1
            else:
                continue

            if r.aggregate_code is not None and r.aggregate_code == aggregate_code:
                score += 2
            elif r.aggregate_code is None:
                score += 1
            else:
                continue

            if score > best_score:
                best_score = score
                best = r

                                        
        threshold = qc_min.DEFAULT_MIN_VALUE
        if best and best.params and isinstance(best.params, dict):
            try:
                threshold = float(best.params.get("min", qc_min.DEFAULT_MIN_VALUE))
            except Exception:
                threshold = qc_min.DEFAULT_MIN_VALUE

                                
        source = "default"
        if best is not None:
            if getattr(best, "sensor_id", None) is not None and sensor_id is not None and best.sensor_id == sensor_id:
                source = "sensor"
            elif best.parameter_id is not None and parameter_id is not None and best.parameter_id == parameter_id:
                source = "parameter"
            else:
                source = "global"

                             
        from qaqc.registry import get as get_plugin
        plugin = get_plugin(check_code)
        display_name = getattr(plugin, "display_name", check_code) if plugin else check_code
        long_description = getattr(plugin, "long_description", "") if plugin else ""
        return {
            "check_code": check_code,
            "display_name": display_name,
            "long_description": long_description,
            "context": {
                "sensor_id": sensor_id,
                "parameter_id": parameter_id,
                "aggregate_code": aggregate_code,
            },
            "source": source,
            "threshold": threshold,
            "rule": _rule_to_dict(best) if best else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/qc/plugins")
def list_qc_plugins():
    try:
                                                
        import qaqc.plugins              
        from qaqc.registry import all_plugins
        items = []
        for name, plugin in all_plugins().items():
            items.append({
                "name": getattr(plugin, "name", name),
                "display_name": getattr(plugin, "display_name", name),
                "long_description": getattr(plugin, "long_description", ""),
                "version": getattr(plugin, "version", None),
                "qc_api": getattr(plugin, "qc_api", None),
                "param_schema": getattr(plugin, "param_schema", None),
            })
                                            
        items.sort(key=lambda x: x.get("display_name") or x.get("name"))
        return items
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
