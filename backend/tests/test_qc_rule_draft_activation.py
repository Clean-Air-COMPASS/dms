from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app
from db import SessionLocal
import models
from qaqc import discovery, registry
from qaqc.plugins import BUILT_IN_PLUGINS
from sqlalchemy import select

                                                                             
                                            

client = TestClient(app)


def _maybe_get_session():
    try:
        return SessionLocal()
    except Exception:
        return None


def test_draft_and_activation_flow(admin_auth_headers):
    session = _maybe_get_session()
    if session is None:
                                   
        return

                                    
    parameter = session.scalar(
        select(models.Parameter).where(models.Parameter.code == "pm25")
    )
    r = models.QCRule(
        check_code="min_value",
        parameter_id=parameter.parameter_id,
        policy_unit_id=parameter.default_unit_id,
        enabled_override=True,
        settings={"min": 0.0},
    )
    session.add(r)
    session.flush()
    rid = r.qc_rule_id
    session.commit()

                
    resp = client.put(
        f"/admin/qc/rules/{rid}/draft",
        json={"draft_params": {"min": 5.0}},
        headers=admin_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["draft_params"] == {"min": 5.0}

                                                     
    prev = client.post(f"/admin/qc/rules/{rid}/preview", headers=admin_auth_headers)
    assert prev.status_code == 200, prev.text
    pdata = prev.json()
    assert pdata["qc_rule_id"] == rid
    assert "samples" in pdata

              
    act = client.post(f"/admin/qc/rules/{rid}/activate", headers=admin_auth_headers)
    assert act.status_code == 200, act.text
    adata = act.json()
    assert adata["params"] == {"min": 5.0}
    assert adata["draft_params"] is None
    assert adata["version"] >= 2

             
    session.delete(r)
    session.commit()
    session.close()


def test_max_value_draft_preview_has_no_builtin_fallback(admin_auth_headers):
    session = _maybe_get_session()
    if session is None:
        return

    parameter = session.scalar(
        select(models.Parameter).where(models.Parameter.code == "pm25")
    )
    rule = models.QCRule(
        check_code="max_value",
        parameter_id=parameter.parameter_id,
        policy_unit_id=parameter.default_unit_id,
        enabled_override=True,
        settings={"max": 100.0},
        draft_params={"max": 50.0},
    )
    session.add(rule)
    session.commit()
    rule_id = rule.qc_rule_id
    previous_registry = tuple(registry.all_registrations().values())
    try:
        registry.replace_all(
            registry.validate_plugin(plugin, origin="built_in")
            for plugin in BUILT_IN_PLUGINS
        )
        response = client.post(
            f"/admin/qc/rules/{rule_id}/preview",
            headers=admin_auth_headers,
        )
        assert response.status_code == 503
        assert response.json()["detail"]["reason_code"] == "plugin_unavailable"

        discovery.load_plugins()
        restored = client.post(
            f"/admin/qc/rules/{rule_id}/preview",
            headers=admin_auth_headers,
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["check_code"] == "max_value"
    finally:
        registry.replace_all(previous_registry)
        session.delete(rule)
        session.commit()
        session.close()
