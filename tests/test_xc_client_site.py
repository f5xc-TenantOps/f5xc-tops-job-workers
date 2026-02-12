import pytest
from unittest.mock import MagicMock, patch

from shared.errors import ResourceExistsError, ResourceNotFoundError


@patch("shared.xc_client.requests.Session")
def test_create_securemesh_site_v2(mock_session_class):
    """POST to /api/config/namespaces/system/securemesh_site_v2s with payload."""
    from shared.xc_client import XCClient

    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"metadata": {"name": "test-site"}}
    mock_session.post.return_value = mock_response
    mock_session_class.return_value = mock_session

    client = XCClient(tenant_url="https://t.console.ves.volterra.io", api_token="tok", validate=False)

    payload = {"namespace": "system", "metadata": {"name": "test-site"}, "spec": {"kvm": {"not_managed": {}}}}
    result = client.create_securemesh_site_v2(payload)

    assert result["metadata"]["name"] == "test-site"
    mock_session.post.assert_called_once()
    call_args = mock_session.post.call_args
    assert "/api/config/namespaces/system/securemesh_site_v2s" in call_args[0][0]


@patch("shared.xc_client.requests.Session")
def test_delete_securemesh_site_v2(mock_session_class):
    """DELETE to /api/config/namespaces/system/securemesh_site_v2s/{name}."""
    from shared.xc_client import XCClient

    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}
    mock_session.delete.return_value = mock_response
    mock_session_class.return_value = mock_session

    client = XCClient(tenant_url="https://t.console.ves.volterra.io", api_token="tok", validate=False)

    result = client.delete_securemesh_site_v2("test-site")

    assert result == {}
    mock_session.delete.assert_called_once()
    call_args = mock_session.delete.call_args
    assert "/api/config/namespaces/system/securemesh_site_v2s/test-site" in call_args[0][0]


@patch("shared.xc_client.requests.Session")
def test_create_registration_token(mock_session_class):
    """POST to /api/register/namespaces/system/tokens with site name."""
    from shared.xc_client import XCClient

    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "metadata": {"name": "jwt-token-123"},
        "spec": {"content": "eyJhb...", "site_name": "test-site", "state": "VALID", "type": "JWT"}
    }
    mock_session.post.return_value = mock_response
    mock_session_class.return_value = mock_session

    client = XCClient(tenant_url="https://t.console.ves.volterra.io", api_token="tok", validate=False)

    result = client.create_registration_token("test-site", "jwt-token-123")

    assert result["spec"]["content"] == "eyJhb..."
    assert result["spec"]["site_name"] == "test-site"
    mock_session.post.assert_called_once()
    call_args = mock_session.post.call_args
    assert "/api/register/namespaces/system/tokens" in call_args[0][0]
    payload = call_args[1]["json"]
    assert payload["metadata"]["name"] == "jwt-token-123"
    assert payload["spec"]["type"] == "JWT"
    assert payload["spec"]["site_name"] == "test-site"
