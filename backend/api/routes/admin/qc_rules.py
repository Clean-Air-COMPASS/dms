from __future__ import annotations

from typing import Optional, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db import get_session
import models
from qaqc.pipeline import _validate_plugin_decisions
from qaqc.policy import EffectiveQCPolicy, resolve_effective_qc_policy
from qaqc.policy_defaults import FLAG_FOR_REVIEW
from qaqc.registry import get_registration
from qaqc.types import QCRecord


router = APIRouter(prefix="/admin", tags=["admin"]) 


def _rule_to_dict(r: models.QCRule) -> Dict[str, Any]:
    return {
        "qc_rule_id": r.qc_rule_id,
        "check_code": r.check_code,
        "sensor_id": getattr(r, "sensor_id", None),
        "parameter_id": getattr(r, "parameter_id", None),
        "external_api_id": getattr(r, "external_api_id", None),
        "aggregate_code": getattr(r, "aggregate_code", None),
        "enabled": r.enabled_override,
        "enabled_override": r.enabled_override,
        "failure_action_override": r.failure_action_override,
        "params": r.settings or None,
        "settings": r.settings or None,
        "policy_unit_id": r.policy_unit_id,
        "version": getattr(r, "version", None),
        "state": getattr(r, "state", None),
        "draft_params": getattr(r, "draft_params", None),
        "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
        "updated_at": r.updated_at.isoformat() if getattr(r, "updated_at", None) else None,
    }


def _validate_rule_scope(
    sensor_id: Optional[int],
    parameter_id: Optional[int],
    external_api_id: Optional[int],
) -> None:
    is_sensor_scope = (
        sensor_id is not None
        and parameter_id is None
        and external_api_id is None
    )
    is_parameter_scope = (
        sensor_id is None
        and parameter_id is not None
        and external_api_id is None
    )
    is_source_scope = (
        sensor_id is None
        and parameter_id is not None
        and external_api_id is not None
    )
    if not (is_sensor_scope or is_parameter_scope or is_source_scope):
        raise HTTPException(
            status_code=400,
            detail=(
                "QC rule scope must be parameter, data source + parameter, "
                "or sensor"
            ),
        )


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
            conds.append(models.QCRule.enabled_override == enabled)
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
        sensor_id = payload.get("sensor_id")
        parameter_id = payload.get("parameter_id")
        external_api_id = payload.get("external_api_id")
        _validate_rule_scope(sensor_id, parameter_id, external_api_id)
        enabled_override = payload.get(
            "enabled_override", payload.get("enabled")
        )
        r = models.QCRule(
            check_code=check_code,
            sensor_id=sensor_id,
            parameter_id=parameter_id,
            external_api_id=external_api_id,
            aggregate_code=payload.get("aggregate_code"),
            enabled_override=enabled_override,
            failure_action_override=payload.get("failure_action_override"),
            settings=payload.get("settings", payload.get("params")),
            policy_unit_id=payload.get("policy_unit_id"),
        )
        session.add(r)
        session.flush()
        session.commit()
        return _rule_to_dict(r)
    except HTTPException:
        raise
    except IntegrityError as e:
        session.rollback()
        raise HTTPException(status_code=409, detail="A QC override already exists for this scope") from e
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
        if "external_api_id" in payload:
            r.external_api_id = payload["external_api_id"]
        if "aggregate_code" in payload:
            r.aggregate_code = payload["aggregate_code"]
        if "enabled_override" in payload:
            r.enabled_override = payload["enabled_override"]
        elif "enabled" in payload:
            r.enabled_override = payload["enabled"]
        if "failure_action_override" in payload:
            r.failure_action_override = payload["failure_action_override"]
        if "settings" in payload:
            r.settings = payload["settings"]
        elif "params" in payload:
            r.settings = payload["params"]
        if "policy_unit_id" in payload:
            r.policy_unit_id = payload["policy_unit_id"]
        _validate_rule_scope(r.sensor_id, r.parameter_id, r.external_api_id)
        session.add(r)
        session.flush()
        session.commit()
        return _rule_to_dict(r)
    except HTTPException:
        raise
    except IntegrityError as e:
        session.rollback()
        raise HTTPException(status_code=409, detail="A QC override already exists for this scope") from e
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
        r.state = "draft"
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
    """Preview draft settings through the registered plugin implementation.

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
        if r.external_api_id is not None:
            stmt = stmt.join(models.Device, models.Device.device_id == s.device_id).where(
                models.Device.external_api_id == r.external_api_id
            )
        values = [v for (v,) in session.execute(stmt).all()]
        chk = r.check_code
        registration = get_registration(chk)
        if registration is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "reason_code": "plugin_unavailable",
                    "message": f"QC plugin '{chk}' is unavailable",
                },
            )
        draft_settings = dict(r.draft_params)
        preview_policy = EffectiveQCPolicy(
            check_code=chk,
            status="ready",
            enabled=True,
            failure_action=r.failure_action_override or FLAG_FOR_REVIEW,
            configured_settings=draft_settings,
            evaluation_settings=draft_settings,
        )
        records = [
            QCRecord(
                sensor_id=None,
                parameter_id=r.parameter_id,
                value=value,
                unit_id=None,
                observed_at=None,
            )
            for value in values
        ]
        raw_decisions = registration.plugin.apply(
            records,
            {"effective_policies": [preview_policy] * len(records)},
        )
        decisions = _validate_plugin_decisions(chk, raw_decisions, len(records))
        would_fail = sum(decision.is_valid is False for decision in decisions)
        would_pass = sum(decision.is_valid is True for decision in decisions)
        indeterminate = sum(decision.is_valid is None for decision in decisions)
        summary_setting = registration.metadata.overview.summary_setting
        threshold = (
            draft_settings.get(summary_setting)
            if summary_setting is not None
            else None
        )
        return {
            "qc_rule_id": qc_rule_id,
            "check_code": chk,
            "threshold": threshold,
            "since": since.isoformat(),
            "samples": len(values),
            "would_fail": would_fail,
            "would_pass": would_pass,
            "indeterminate": indeterminate,
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
        r.enabled_override = False
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
        r.enabled_override = True
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
        if sensor_id is None:
            raise HTTPException(
                status_code=400,
                detail="sensor_id is required for unit-aware effective QC policy resolution",
            )
        sensor = session.get(models.Sensor, sensor_id)
        if sensor is None:
            raise HTTPException(status_code=404, detail="Sensor not found")
        if parameter_id is not None and sensor.parameter_id != parameter_id:
            raise HTTPException(
                status_code=400,
                detail="parameter_id does not match the selected sensor",
            )
        policy = resolve_effective_qc_policy(
            session,
            sensor_id,
            check_code,
            aggregate_code,
        )

        import qaqc.plugins
        from qaqc.registry import get as get_plugin
        plugin = get_plugin(check_code)
        display_name = getattr(plugin, "display_name", check_code) if plugin else check_code
        long_description = getattr(plugin, "long_description", "") if plugin else ""
        threshold_name = "min" if check_code == "min_value" else "max"
        return {
            "check_code": check_code,
            "display_name": display_name,
            "long_description": long_description,
            "context": {
                "sensor_id": sensor_id,
                "parameter_id": sensor.parameter_id,
                "aggregate_code": aggregate_code,
            },
            "source": (
                policy.most_specific_source.layer
                if policy.most_specific_source is not None
                else None
            ),
            "threshold": policy.evaluation_settings.get(threshold_name),
            "rule": None,
            "effective_policy": policy.to_dict(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/qc/plugins")
def list_qc_plugins():
    try:
        from dataclasses import asdict
        from qaqc.registry import all_registrations

        items = []
        for registration in all_registrations().values():
            items.append(asdict(registration.metadata))
        items.sort(key=lambda x: x.get("display_name") or x.get("name"))
        return items
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
