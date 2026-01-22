# tests/test_ns_remove.py
import pytest
from unittest.mock import MagicMock, patch


@patch("ns_remove.function.get_ssm_parameters")
@patch("ns_remove.function.XCClient")
def test_delete_namespace_success(mock_xc_client_class, mock_get_params):
    """Successfully delete a namespace."""
    from ns_remove.function import handler

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_xc_client_class.return_value = mock_client

    class MockContext:
        function_name = "ns_remove"

    event = {
        "ssm_base_path": "/tenantOps/test",
        "namespace_name": "test-ns"
    }

    result = handler(event, MockContext())

    assert result["statusCode"] == 200
    assert "removed successfully" in result["body"]
    mock_client.delete_namespace.assert_called_once_with("test-ns")
    mock_xc_client_class.assert_called_once_with(
        tenant_url="https://test.console.ves.volterra.io",
        api_token="token",
        validate=False
    )


@patch("ns_remove.function.get_ssm_parameters")
@patch("ns_remove.function.XCClient")
def test_delete_namespace_not_found(mock_xc_client_class, mock_get_params):
    """Handle namespace not found (idempotent - should still return success)."""
    from ns_remove.function import handler
    from shared.errors import ResourceNotFoundError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.delete_namespace.side_effect = ResourceNotFoundError("Namespace not found")
    mock_xc_client_class.return_value = mock_client

    class MockContext:
        function_name = "ns_remove"

    event = {
        "ssm_base_path": "/tenantOps/test",
        "namespace_name": "test-ns"
    }

    result = handler(event, MockContext())

    # Should return success even though namespace was not found
    assert result["statusCode"] == 200
    assert "does not exist" in result["body"] or "already removed" in result["body"]
    mock_client.delete_namespace.assert_called_once_with("test-ns")


@patch("ns_remove.function.get_ssm_parameters")
@patch("ns_remove.function.XCClient")
def test_delete_namespace_missing_fields(mock_xc_client_class, mock_get_params):
    """Handle missing required fields in payload."""
    from ns_remove.function import handler

    class MockContext:
        function_name = "ns_remove"

    # Missing namespace_name
    event = {
        "ssm_base_path": "/tenantOps/test"
    }

    result = handler(event, MockContext())

    # The lambda_handler decorator catches PermanentError and returns error response
    assert result["statusCode"] == 400
    assert "Missing required fields" in result["body"]


@patch("ns_remove.function.get_ssm_parameters")
@patch("ns_remove.function.XCClient")
def test_delete_namespace_api_error(mock_xc_client_class, mock_get_params):
    """Handle API errors from XCClient."""
    from ns_remove.function import handler
    from shared.errors import TransientError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.delete_namespace.side_effect = TransientError("API error 503: Service Unavailable")
    mock_xc_client_class.return_value = mock_client

    class MockContext:
        function_name = "ns_remove"

    event = {
        "ssm_base_path": "/tenantOps/test",
        "namespace_name": "test-ns"
    }

    # TransientError should be re-raised by the decorator
    with pytest.raises(TransientError):
        handler(event, MockContext())
