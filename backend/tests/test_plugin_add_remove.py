from fastapi.testclient import TestClient

from api.main import app


client = TestClient(app)


def test_plugin_admin_is_read_only_and_built_ins_are_not_deletable(
    admin_auth_headers,
):
    response = client.get("/admin/plugins", headers=admin_auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["management_mode"] == "deployment_owned"

    plugins = {plugin["name"]: plugin for plugin in body["plugins"]}
    assert {"min_value", "max_value", "baseline_drift"} <= set(plugins)
    for check_code in ("min_value", "baseline_drift"):
        plugin = plugins[check_code]
        assert plugin["origin"] == "built_in"
        assert plugin["deletable"] is False
        assert plugin["available"] is True
        assert "file_path" not in plugin

    maximum = plugins["max_value"]
    assert maximum["origin"] == "entry_point"
    assert maximum["distribution"] == "compassaq-max-value"
    assert maximum["deletable"] is False
    assert maximum["available"] is True
    assert "file_path" not in maximum


def test_plugin_source_mutation_endpoints_are_removed(admin_auth_headers):
    create_response = client.post(
        "/admin/plugins/local",
        json={"name": "unsafe_plugin", "description": "must not be written"},
        headers=admin_auth_headers,
    )
    upload_response = client.post(
        "/admin/plugins/upload",
        files={"file": ("unsafe_plugin.py", b"raise RuntimeError()", "text/x-python")},
        headers=admin_auth_headers,
    )
    delete_response = client.delete(
        "/admin/plugins/max_value", headers=admin_auth_headers
    )

    assert create_response.status_code == 404
    assert upload_response.status_code == 404
    assert delete_response.status_code == 404


def test_reload_is_post_only_and_keeps_installed_checks_available(admin_auth_headers):
    get_response = client.get(
        "/admin/plugins/reload", headers=admin_auth_headers
    )
    assert get_response.status_code == 405

    post_response = client.post(
        "/admin/plugins/reload", headers=admin_auth_headers
    )
    assert post_response.status_code == 200, post_response.text
    body = post_response.json()
    assert body["management_mode"] == "deployment_owned"
    assert {plugin["name"] for plugin in body["plugins"]} >= {
        "min_value",
        "max_value",
        "baseline_drift",
    }
    assert {item["name"] for item in body["discovery"]["built_in"]} == {
        "min_value",
        "baseline_drift",
    }
    assert {item["name"] for item in body["discovery"]["entry_points"]} >= {
        "max_value"
    }
