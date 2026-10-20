"""Read-only administration diagnostics for installed QC plugins."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import get_session
from models import QCRule
from qaqc import discovery, registry
from qaqc.admin_policy import get_check_metadata


router = APIRouter(prefix="/admin", tags=["admin"])


def _rule_counts(session: Session) -> dict[str, int]:
    rule_rows = session.execute(
        select(QCRule.check_code, func.count(QCRule.qc_rule_id)).group_by(
            QCRule.check_code
        )
    ).all()
    return {check_code: int(count) for check_code, count in rule_rows}


def _plugin_list(rule_counts: dict[str, int]) -> list[dict]:
    items: list[dict] = []
    for name, registration in registry.all_registrations().items():
        item = asdict(registration.metadata)
        item.update(
            {
                "available": True,
                "rules_count": rule_counts.get(name, 0),
                # Installed code is managed by deployment, never by an HTTP
                # request or a file path exposed to the browser.
                "deletable": False,
            }
        )
        items.append(item)
    return items


def _unavailable_checks(rule_counts: dict[str, int]) -> list[dict]:
    """Describe expected or configured checks that cannot currently execute."""
    metadata_by_code = {
        item["check_code"]: item for item in get_check_metadata()
    }
    known_check_codes = set(metadata_by_code)
    known_check_codes.update(rule_counts)

    unavailable: list[dict] = []
    for check_code in sorted(known_check_codes):
        metadata = metadata_by_code.get(check_code)
        if registry.get_registration(check_code) is not None:
            continue
        unavailable.append(
            {
                "check_code": check_code,
                "display_name": (
                    metadata["display_name"] if metadata is not None else check_code
                ),
                "reason_code": "plugin_unavailable",
                "configured_rule_count": rule_counts.get(check_code, 0),
            }
        )
    return unavailable


@router.get("/plugins")
def list_plugins(session: Session = Depends(get_session)) -> dict:
    """List validated installed plugins and the last discovery diagnostics."""
    rule_counts = _rule_counts(session)
    return {
        "plugins": _plugin_list(rule_counts),
        "unavailable_checks": _unavailable_checks(rule_counts),
        "rules_summary": rule_counts,
        "discovery": discovery.get_last_report(),
        "management_mode": "deployment_owned",
    }


@router.post("/plugins/reload")
def reload_plugins(session: Session = Depends(get_session)) -> dict:
    """Re-read deployment-installed entry points and atomically publish them."""
    report = discovery.load_plugins()
    rule_counts = _rule_counts(session)
    return {
        "plugins": _plugin_list(rule_counts),
        "unavailable_checks": _unavailable_checks(rule_counts),
        "rules_summary": rule_counts,
        "discovery": report,
        "management_mode": "deployment_owned",
    }
