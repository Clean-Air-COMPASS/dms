"""Parameter-centered QC policy administration API.

These endpoints expose effective policies and sparse generic overrides. The
row-oriented ``/admin/qc/rules`` routes remain only as a temporary compatibility
adapter for the existing administration screen.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db import get_session
from qaqc.admin_policy import (
    InvalidPolicyOverride,
    OverrideValue,
    PolicyScope,
    build_policy_response,
    get_check_metadata,
    list_parameter_policy_summaries,
    preview_policy_overrides,
    replace_generic_scope_overrides,
    reset_scope_overrides,
    search_sensors,
)


router = APIRouter(prefix="/admin/qc", tags=["admin-qc-policies"])


class PolicyOverrideInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_code: str = Field(min_length=1, max_length=64)
    enabled_override: bool | None = None
    failure_action_override: Literal["flag_for_review", "mark_invalid"] | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    policy_unit_code: str | None = Field(default=None, min_length=1, max_length=32)


class PolicyReplacementInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overrides: list[PolicyOverrideInput] = Field(default_factory=list, max_length=100)


class PolicyPreviewInput(PolicyReplacementInput):
    scope_type: Literal["parameter", "source_parameter", "sensor"]
    parameter_id: int | None = Field(default=None, ge=1)
    external_api_id: int | None = Field(default=None, ge=1)
    sensor_id: int | None = Field(default=None, ge=1)
    hours: int = Field(default=24, ge=1, le=168)
    check_codes: list[str] | None = Field(default=None, max_length=100)


def _override_values(
    overrides: list[PolicyOverrideInput],
) -> list[OverrideValue]:
    return [
        OverrideValue(
            check_code=override.check_code.strip(),
            enabled_override=override.enabled_override,
            failure_action_override=override.failure_action_override,
            settings=dict(override.settings),
            policy_unit_code=(
                override.policy_unit_code.strip()
                if override.policy_unit_code is not None
                else None
            ),
        )
        for override in overrides
    ]


def _preview_scope(payload: PolicyPreviewInput) -> PolicyScope:
    if payload.scope_type == "parameter":
        valid = (
            payload.parameter_id is not None
            and payload.external_api_id is None
            and payload.sensor_id is None
        )
    elif payload.scope_type == "source_parameter":
        valid = (
            payload.parameter_id is not None
            and payload.external_api_id is not None
            and payload.sensor_id is None
        )
    else:
        valid = (
            payload.sensor_id is not None
            and payload.parameter_id is None
            and payload.external_api_id is None
        )
    if not valid:
        raise InvalidPolicyOverride(
            "invalid_scope",
            "Scope identifiers do not match scope_type",
        )
    return PolicyScope(
        scope_type=payload.scope_type,
        parameter_id=payload.parameter_id,
        external_api_id=payload.external_api_id,
        sensor_id=payload.sensor_id,
    )


def _raise_policy_error(error: InvalidPolicyOverride) -> None:
    status_code = 404 if error.reason_code.endswith("_not_found") else 422
    raise HTTPException(
        status_code=status_code,
        detail={"reason_code": error.reason_code, "message": str(error)},
    ) from error


def _replace(
    session: Session,
    scope: PolicyScope,
    payload: PolicyReplacementInput,
) -> dict[str, Any]:
    try:
        response = replace_generic_scope_overrides(
            session,
            scope,
            _override_values(payload.overrides),
        )
        session.commit()
        return response
    except InvalidPolicyOverride as error:
        session.rollback()
        _raise_policy_error(error)
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "reason_code": "conflicting_override",
                "message": "A conflicting QC override already exists",
            },
        ) from error


def _reset(
    session: Session,
    scope: PolicyScope,
    check_code: str | None = None,
    policy_unit_code: str | None = None,
) -> dict[str, Any]:
    try:
        response = reset_scope_overrides(
            session,
            scope,
            check_code,
            policy_unit_code,
        )
        session.commit()
        return response
    except InvalidPolicyOverride as error:
        session.rollback()
        _raise_policy_error(error)


def _get(session: Session, scope: PolicyScope) -> dict[str, Any]:
    try:
        return build_policy_response(session, scope)
    except InvalidPolicyOverride as error:
        _raise_policy_error(error)


@router.get("/checks")
def list_qc_checks() -> dict[str, Any]:
    return {"items": get_check_metadata()}


@router.get("/parameters")
def list_qc_parameters(
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return list_parameter_policy_summaries(session)


@router.get("/sensors/search")
def find_qc_sensors(
    query: str | None = Query(default=None, max_length=120),
    parameter_id: int | None = Query(default=None, ge=1),
    external_api_id: int | None = Query(default=None, ge=1),
    has_overrides: bool | None = Query(default=None),
    has_sensor_specific_qc: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return search_sensors(
        session,
        query=query,
        parameter_id=parameter_id,
        external_api_id=external_api_id,
        has_overrides=has_overrides,
        has_sensor_specific_qc=has_sensor_specific_qc,
        limit=limit,
        offset=offset,
    )


@router.get("/parameters/{parameter_id}/policy")
def get_parameter_policy(
    parameter_id: int,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _get(session, PolicyScope("parameter", parameter_id=parameter_id))


@router.put("/parameters/{parameter_id}/policy")
def replace_parameter_policy(
    parameter_id: int,
    payload: PolicyReplacementInput,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _replace(
        session,
        PolicyScope("parameter", parameter_id=parameter_id),
        payload,
    )


@router.delete("/parameters/{parameter_id}/policy")
def reset_parameter_policy(
    parameter_id: int,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _reset(session, PolicyScope("parameter", parameter_id=parameter_id))


@router.delete("/parameters/{parameter_id}/policy/checks/{check_code}")
def reset_parameter_check(
    parameter_id: int,
    check_code: str,
    unit_code: str | None = Query(default=None, min_length=1, max_length=32),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _reset(
        session,
        PolicyScope("parameter", parameter_id=parameter_id),
        check_code,
        unit_code,
    )


@router.get("/sources/{external_api_id}/parameters/{parameter_id}/policy")
def get_source_parameter_policy(
    external_api_id: int,
    parameter_id: int,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _get(
        session,
        PolicyScope(
            "source_parameter",
            parameter_id=parameter_id,
            external_api_id=external_api_id,
        ),
    )


@router.put("/sources/{external_api_id}/parameters/{parameter_id}/policy")
def replace_source_parameter_policy(
    external_api_id: int,
    parameter_id: int,
    payload: PolicyReplacementInput,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _replace(
        session,
        PolicyScope(
            "source_parameter",
            parameter_id=parameter_id,
            external_api_id=external_api_id,
        ),
        payload,
    )


@router.delete("/sources/{external_api_id}/parameters/{parameter_id}/policy")
def reset_source_parameter_policy(
    external_api_id: int,
    parameter_id: int,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _reset(
        session,
        PolicyScope(
            "source_parameter",
            parameter_id=parameter_id,
            external_api_id=external_api_id,
        ),
    )


@router.delete(
    "/sources/{external_api_id}/parameters/{parameter_id}/policy/checks/{check_code}"
)
def reset_source_parameter_check(
    external_api_id: int,
    parameter_id: int,
    check_code: str,
    unit_code: str | None = Query(default=None, min_length=1, max_length=32),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _reset(
        session,
        PolicyScope(
            "source_parameter",
            parameter_id=parameter_id,
            external_api_id=external_api_id,
        ),
        check_code,
        unit_code,
    )


@router.get("/sensors/{sensor_id}/policy")
def get_sensor_policy(
    sensor_id: int,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _get(session, PolicyScope("sensor", sensor_id=sensor_id))


@router.put("/sensors/{sensor_id}/policy")
def replace_sensor_policy(
    sensor_id: int,
    payload: PolicyReplacementInput,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _replace(
        session,
        PolicyScope("sensor", sensor_id=sensor_id),
        payload,
    )


@router.delete("/sensors/{sensor_id}/policy")
def reset_sensor_policy(
    sensor_id: int,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _reset(session, PolicyScope("sensor", sensor_id=sensor_id))


@router.delete("/sensors/{sensor_id}/policy/checks/{check_code}")
def reset_sensor_check(
    sensor_id: int,
    check_code: str,
    unit_code: str | None = Query(default=None, min_length=1, max_length=32),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _reset(
        session,
        PolicyScope("sensor", sensor_id=sensor_id),
        check_code,
        unit_code,
    )


@router.post("/preview")
def preview_qc_policy(
    payload: PolicyPreviewInput,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        scope = _preview_scope(payload)
        preview = preview_policy_overrides(
            session,
            scope,
            _override_values(payload.overrides),
            hours=payload.hours,
            check_codes=payload.check_codes,
        )
        response.headers["Cache-Control"] = "no-store"
        return preview
    except InvalidPolicyOverride as error:
        _raise_policy_error(error)
