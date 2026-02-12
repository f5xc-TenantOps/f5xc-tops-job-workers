import pytest
from unittest.mock import MagicMock, patch


@patch("securemesh_site_v2_remove.function.get_ssm_parameters")
@patch("securemesh_site_v2_remove.function.XCClient")
def test_delete_site_success(mock_xc_client_class, mock_get_params):
    """Successfully delete a SecureMesh Site v2."""
    from securemesh_site_v2_remove.function import handler

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.delete_securemesh_site_v2.return_value = {}
    mock_xc_client_class.return_value = mock_client

    class MockContext:
        function_name = "securemesh_site_v2_remove"

    event = {
        "ssm_base_path": "/tenantOps/mcn-lab",
        "site_name": "fuzzy-cat-site"
    }

    result = handler(event, MockContext())

    assert result["statusCode"] == 200
    assert "removed successfully" in result["body"]
    mock_client.delete_securemesh_site_v2.assert_called_once_with("fuzzy-cat-site")


@patch("securemesh_site_v2_remove.function.get_ssm_parameters")
@patch("securemesh_site_v2_remove.function.XCClient")
def test_delete_site_not_found(mock_xc_client_class, mock_get_params):
    """Handle site not found (idempotent)."""
    from securemesh_site_v2_remove.function import handler
    from shared.errors import ResourceNotFoundError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.delete_securemesh_site_v2.side_effect = ResourceNotFoundError("Not found")
    mock_xc_client_class.return_value = mock_client

    class MockContext:
        function_name = "securemesh_site_v2_remove"

    event = {
        "ssm_base_path": "/tenantOps/mcn-lab",
        "site_name": "fuzzy-cat-site"
    }

    result = handler(event, MockContext())

    assert result["statusCode"] == 200
    assert "does not exist" in result["body"] or "already removed" in result["body"]


@patch("securemesh_site_v2_remove.function.get_ssm_parameters")
@patch("securemesh_site_v2_remove.function.XCClient")
def test_delete_site_missing_fields(mock_xc_client_class, mock_get_params):
    """Handle missing required fields."""
    from securemesh_site_v2_remove.function import handler

    class MockContext:
        function_name = "securemesh_site_v2_remove"

    event = {
        "ssm_base_path": "/tenantOps/mcn-lab"
        # Missing site_name
    }

    result = handler(event, MockContext())

    assert result["statusCode"] == 400
    assert "Missing required fields" in result["body"]


@patch("securemesh_site_v2_remove.function.get_ssm_parameters")
@patch("securemesh_site_v2_remove.function.XCClient")
def test_delete_site_transient_error(mock_xc_client_class, mock_get_params):
    """Transient errors are re-raised for infrastructure retry."""
    from securemesh_site_v2_remove.function import handler
    from shared.errors import TransientError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.delete_securemesh_site_v2.side_effect = TransientError("503")
    mock_xc_client_class.return_value = mock_client

    class MockContext:
        function_name = "securemesh_site_v2_remove"

    event = {
        "ssm_base_path": "/tenantOps/mcn-lab",
        "site_name": "fuzzy-cat-site"
    }

    with pytest.raises(TransientError):
        handler(event, MockContext())
