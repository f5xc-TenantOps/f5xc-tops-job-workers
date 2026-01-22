# tests/test_token_refresh.py
import os
import pytest
from unittest.mock import MagicMock, patch


class MockContext:
    function_name = "token_refresh"


@patch.dict(os.environ, {"SSM_BASE_PATH": "/tenantOps/test"})
@patch("token_refresh.function.get_ssm_parameters")
@patch("token_refresh.function.XCClient")
def test_refresh_api_credential_success(mock_xc_client, mock_get_params):
    """Successfully refresh an API credential."""
    from token_refresh.function import handler

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "test-token",
        "token-name": "my-api-token",
        "token-type": "apicred"
    }

    mock_client = MagicMock()
    mock_client.renew_api_credential.return_value = {}
    mock_xc_client.return_value = mock_client

    result = handler({}, MockContext())

    assert result["statusCode"] == 200
    assert "apicred token my-api-token refreshed successfully" in result["body"]
    mock_client.renew_api_credential.assert_called_once_with("my-api-token", 7)
    mock_xc_client.assert_called_once_with(
        tenant_url="https://test.console.ves.volterra.io",
        api_token="test-token",
    )


@patch.dict(os.environ, {"SSM_BASE_PATH": "/tenantOps/test"})
@patch("token_refresh.function.get_ssm_parameters")
@patch("token_refresh.function.XCClient")
def test_refresh_service_credential_success(mock_xc_client, mock_get_params):
    """Successfully refresh a service credential."""
    from token_refresh.function import handler

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "test-token",
        "token-name": "my-svc-token",
        "token-type": "svccred"
    }

    mock_client = MagicMock()
    mock_client.renew_service_credential.return_value = {}
    mock_xc_client.return_value = mock_client

    result = handler({}, MockContext())

    assert result["statusCode"] == 200
    assert "svccred token my-svc-token refreshed successfully" in result["body"]
    mock_client.renew_service_credential.assert_called_once_with("my-svc-token", 7)


@patch.dict(os.environ, {"SSM_BASE_PATH": "/tenantOps/test"})
@patch("token_refresh.function.get_ssm_parameters")
@patch("token_refresh.function.XCClient")
def test_refresh_token_type_case_insensitive(mock_xc_client, mock_get_params):
    """Token type should be case insensitive."""
    from token_refresh.function import handler

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "test-token",
        "token-name": "my-api-token",
        "token-type": "APICRED"  # uppercase
    }

    mock_client = MagicMock()
    mock_client.renew_api_credential.return_value = {}
    mock_xc_client.return_value = mock_client

    result = handler({}, MockContext())

    assert result["statusCode"] == 200
    mock_client.renew_api_credential.assert_called_once()


@patch.dict(os.environ, {"SSM_BASE_PATH": "/tenantOps/test"})
@patch("token_refresh.function.get_ssm_parameters")
def test_invalid_token_type(mock_get_params):
    """Raise PermanentError for invalid token type."""
    from token_refresh.function import handler

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "test-token",
        "token-name": "my-token",
        "token-type": "invalid"
    }

    result = handler({}, MockContext())

    assert result["statusCode"] == 400
    assert "Invalid token-type" in result["body"]


@patch.dict(os.environ, {}, clear=True)
def test_missing_ssm_base_path():
    """Raise PermanentError when SSM_BASE_PATH is not set."""
    from token_refresh.function import handler

    # Remove SSM_BASE_PATH if present
    os.environ.pop("SSM_BASE_PATH", None)

    result = handler({}, MockContext())

    assert result["statusCode"] == 400
    assert "SSM_BASE_PATH is not set" in result["body"]


@patch.dict(os.environ, {"SSM_BASE_PATH": "/tenantOps/test"})
@patch("token_refresh.function.get_ssm_parameters")
@patch("token_refresh.function.XCClient")
def test_xc_client_api_error(mock_xc_client, mock_get_params):
    """Propagate PermanentError from XCClient."""
    from token_refresh.function import handler
    from shared.errors import PermanentError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "test-token",
        "token-name": "my-api-token",
        "token-type": "apicred"
    }

    mock_client = MagicMock()
    mock_client.renew_api_credential.side_effect = PermanentError("API error 404: not found")
    mock_xc_client.return_value = mock_client

    result = handler({}, MockContext())

    assert result["statusCode"] == 400
    assert "API error 404" in result["body"]


@patch.dict(os.environ, {"SSM_BASE_PATH": "/tenantOps/test"})
@patch("token_refresh.function.get_ssm_parameters")
@patch("token_refresh.function.XCClient")
def test_transient_error_propagates(mock_xc_client, mock_get_params):
    """TransientError should propagate for retry."""
    from token_refresh.function import handler
    from shared.errors import TransientError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "test-token",
        "token-name": "my-api-token",
        "token-type": "apicred"
    }

    mock_client = MagicMock()
    mock_client.renew_api_credential.side_effect = TransientError("Server error")
    mock_xc_client.return_value = mock_client

    with pytest.raises(TransientError):
        handler({}, MockContext())
