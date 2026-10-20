from fastapi.testclient import TestClient

from api.main import app


client = TestClient(app)


def test_plugin_diagnostics_require_admin_authentication():
    response = client.get("/admin/plugins")
    assert response.status_code in {401, 403}


def test_plugin_diagnostics_expose_validated_contract(admin_auth_headers):
    response = client.get("/admin/plugins", headers=admin_auth_headers)
    assert response.status_code == 200, response.text

    maximum = next(
        plugin
        for plugin in response.json()["plugins"]
        if plugin["name"] == "max_value"
    )
    assert maximum["qc_api"] == 1
    assert maximum["required_access"] == "api-only"
    assert maximum["param_schema"]["max"]["required"] is True
    assert maximum["version"] == "1.0.0"
    assert maximum["origin"] == "entry_point"
    assert maximum["module"] == "compassaq_max_value.plugin"
    assert maximum["entrypoint"] == (
        "max_value=compassaq_max_value.plugin:plugin"
    )
    assert maximum["distribution"] == "compassaq-max-value"
