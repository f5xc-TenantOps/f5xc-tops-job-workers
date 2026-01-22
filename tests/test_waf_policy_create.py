# tests/test_waf_policy_create.py
import pytest
from unittest.mock import MagicMock, patch


@patch("waf_policy_create.function.get_ssm_parameters")
@patch("waf_policy_create.function.XCClient")
def test_create_waf_policy_success(mock_xc_client_class, mock_get_params):
    """Successfully create a WAF policy."""
    from waf_policy_create.function import create_waf
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_client = MagicMock()
    mock_xc_client_class.return_value = mock_client

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-waf", "namespace": "test-ns"},
        "spec": {"mode": "BLOCKING"}
    }

    result = create_waf(event, logger)

    assert result["status"] == "success"
    assert result["name"] == "test-waf"
    assert result["created"] is True
    mock_client.create_app_firewall.assert_called_once_with(
        "test-ns",
        {"metadata": {"name": "test-waf", "namespace": "test-ns"}, "spec": {"mode": "BLOCKING"}}
    )


@patch("waf_policy_create.function.get_ssm_parameters")
@patch("waf_policy_create.function.XCClient")
def test_create_waf_policy_already_exists(mock_xc_client_class, mock_get_params):
    """Handle WAF policy that already exists (idempotent)."""
    from waf_policy_create.function import create_waf
    from shared.logging import StructuredLogger
    from shared.errors import ResourceExistsError

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_client = MagicMock()
    mock_client.create_app_firewall.side_effect = ResourceExistsError("Resource already exists")
    mock_xc_client_class.return_value = mock_client

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-waf", "namespace": "test-ns"},
        "spec": {"mode": "BLOCKING"}
    }

    result = create_waf(event, logger)

    assert result["status"] == "success"
    assert result["already_existed"] is True


@patch("waf_policy_create.function.get_ssm_parameters")
@patch("waf_policy_create.function.XCClient")
def test_create_waf_policy_permanent_error_raises(mock_xc_client_class, mock_get_params):
    """Permanent errors are raised to caller."""
    from waf_policy_create.function import create_waf
    from shared.logging import StructuredLogger
    from shared.errors import PermanentError

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_client = MagicMock()
    mock_client.create_app_firewall.side_effect = PermanentError("Invalid payload")
    mock_xc_client_class.return_value = mock_client

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-waf", "namespace": "test-ns"},
        "spec": {"mode": "BLOCKING"}
    }

    with pytest.raises(PermanentError):
        create_waf(event, logger)


@patch("waf_policy_create.function.get_ssm_parameters")
@patch("waf_policy_create.function.XCClient")
def test_create_waf_policy_client_init(mock_xc_client_class, mock_get_params):
    """XCClient initialized with correct parameters."""
    from waf_policy_create.function import create_waf
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "my-token"}

    mock_client = MagicMock()
    mock_xc_client_class.return_value = mock_client

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-waf", "namespace": "test-ns"},
        "spec": {"mode": "BLOCKING"}
    }

    create_waf(event, logger)

    mock_xc_client_class.assert_called_once_with(
        tenant_url="https://test.console.ves.volterra.io",
        api_token="my-token",
        validate=False
    )
