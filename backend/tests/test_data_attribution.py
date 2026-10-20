from api.routes.admin.devices import _apply_openaq_device_attribution
from services.data_attribution import serialize_device_data_attribution
import models


def test_airgradient_via_openaq_preserves_transport_origin_contributor_and_license():
    device = models.Device(
        name="Manila Observatory",
        external_api_id=1,
        external_id="4565934",
    )
    _apply_openaq_device_attribution(
        device,
        {
            "provider_name": "AirGradient",
            "owner_name": "Manila Observatory",
            "instruments": [{"name": "AirGradient ONE Generation 9"}],
            "licenses": [
                {
                    "name": "CC BY 4.0",
                    "attribution": {
                        "name": "Manila Observatory",
                        "url": "https://example.org/manila-observatory",
                    },
                    "dateTo": None,
                }
            ],
        },
    )

    assert serialize_device_data_attribution(device, "OpenAQ") == {
        "acquisition_path": "openaq",
        "data_provider_name": "OpenAQ",
        "hardware_provider_name": "AirGradient",
        "provider_url": "https://openaq.org",
        "contributor_name": "Manila Observatory",
        "contributor_url": "https://example.org/manila-observatory",
        "license_code": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "license_share_alike": False,
    }


def test_direct_airgradient_and_airgradient_via_openaq_are_not_collapsed():
    direct = models.Device(
        name="Direct location",
        external_api_id=1,
        acquisition_path="airgradient_public_reference",
        hardware_provider_name="AirGradient",
        provider_url="https://www.airgradient.com",
        license_code="CC-BY-SA-4.0",
        license_url="https://creativecommons.org/licenses/by-sa/4.0/",
        license_share_alike=True,
    )
    via_openaq = models.Device(
        name="OpenAQ location",
        external_api_id=2,
        acquisition_path="openaq",
        hardware_provider_name="AirGradient",
        provider_url="https://openaq.org",
        license_code="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        license_share_alike=False,
    )

    direct_attribution = serialize_device_data_attribution(direct, "AirGradient")
    openaq_attribution = serialize_device_data_attribution(via_openaq, "OpenAQ")
    assert direct_attribution["data_provider_name"] == "AirGradient"
    assert direct_attribution["license_share_alike"] is True
    assert openaq_attribution["data_provider_name"] == "OpenAQ"
    assert openaq_attribution["hardware_provider_name"] == "AirGradient"
    assert openaq_attribution["license_share_alike"] is False
