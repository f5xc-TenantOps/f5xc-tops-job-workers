# tests/test_user_remove.py
import pytest
from unittest.mock import MagicMock, patch


@patch("user_remove.function.get_ssm_parameters")
@patch("user_remove.function.XCClient")
def test_delete_user_success(mock_xc_client_class, mock_get_params):
    """Successfully delete a user."""
    from user_remove.function import handler

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_xc_client_class.return_value = mock_client

    class MockContext:
        function_name = "user_remove"

    event = {
        "ssm_base_path": "/tenantOps/test",
        "email": "test@example.com"
    }

    result = handler(event, MockContext())

    assert result["statusCode"] == 200
    assert "removed successfully" in result["body"]
    mock_client.delete_user.assert_called_once_with("test@example.com")
    mock_xc_client_class.assert_called_once_with(
        tenant_url="https://test.console.ves.volterra.io",
        api_token="token",
        validate=False
    )


@patch("user_remove.function.get_ssm_parameters")
@patch("user_remove.function.XCClient")
def test_delete_user_not_found(mock_xc_client_class, mock_get_params):
    """Handle user not found (idempotent - should still return success)."""
    from user_remove.function import handler
    from shared.errors import ResourceNotFoundError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.delete_user.side_effect = ResourceNotFoundError("User not found")
    mock_xc_client_class.return_value = mock_client

    class MockContext:
        function_name = "user_remove"

    event = {
        "ssm_base_path": "/tenantOps/test",
        "email": "test@example.com"
    }

    result = handler(event, MockContext())

    # Should return success even though user was not found
    assert result["statusCode"] == 200
    assert "not found" in result["body"] or "already removed" in result["body"]
    mock_client.delete_user.assert_called_once_with("test@example.com")


@patch("user_remove.function.get_ssm_parameters")
@patch("user_remove.function.XCClient")
def test_delete_user_missing_fields(mock_xc_client_class, mock_get_params):
    """Handle missing required fields in payload."""
    from user_remove.function import handler

    class MockContext:
        function_name = "user_remove"

    # Missing email
    event = {
        "ssm_base_path": "/tenantOps/test"
    }

    result = handler(event, MockContext())

    # The lambda_handler decorator catches PermanentError and returns error response
    assert result["statusCode"] == 400
    assert "Missing required fields" in result["body"]


@patch("user_remove.function.get_ssm_parameters")
@patch("user_remove.function.XCClient")
def test_delete_user_api_error(mock_xc_client_class, mock_get_params):
    """Handle API errors from XCClient."""
    from user_remove.function import handler
    from shared.errors import TransientError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.delete_user.side_effect = TransientError("API error 503: Service Unavailable")
    mock_xc_client_class.return_value = mock_client

    class MockContext:
        function_name = "user_remove"

    event = {
        "ssm_base_path": "/tenantOps/test",
        "email": "test@example.com"
    }

    # TransientError should be re-raised by the decorator
    with pytest.raises(TransientError):
        handler(event, MockContext())
