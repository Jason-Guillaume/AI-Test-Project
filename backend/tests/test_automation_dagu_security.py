"""Secret filtering shared by Yunxiao and Dagu execution integrations."""

from app.features.automation_center.providers.dagu_client import DaguClient
from app.features.automation_center.services.center_service import AutomationCenterService


def test_provider_parameters_and_logs_redact_secret_like_values():
    """Keep credentials out of Yunxiao variables and externally sourced Dagu logs."""
    clean = AutomationCenterService._public_params({
        "TEST_SUITE": "smoke",
        "DEPLOY_API_KEY": "secret-value",
        "PRIVATE_KEY": "private-value",
        "SERVICE_CREDENTIAL": "credential-value",
    })
    assert clean == {"TEST_SUITE": "smoke"}
    client = DaguClient("https://dagu.example.com", "dagu-test-api-key")
    try:
        assert client.redact("api_key=another-secret private_key=private-value") == "api_key=*** private_key=***"
    finally:
        client.close()
