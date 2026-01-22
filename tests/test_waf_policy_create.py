# tests/test_waf_policy_create.py
import pytest
from unittest.mock import MagicMock, patch


@patch("waf_policy_create.function.get_ssm_parameters")
@patch("waf_policy_create.function.app_firewall")
@patch("waf_policy_create.function.session")
def test_create_waf_policy_success(mock_session, mock_app_fw, mock_get_params):
    """Successfully create a WAF policy."""
    from waf_policy_create.function import create_waf
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_api = MagicMock()
    mock_app_fw.return_value = mock_api

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-waf", "namespace": "test-ns"},
        "spec": {"mode": "BLOCKING"}
    }

    result = create_waf(event, logger)

    assert result["status"] == "success"
    assert result["name"] == "test-waf"
    mock_api.create.assert_called_once()


@patch("waf_policy_create.function.get_ssm_parameters")
@patch("waf_policy_create.function.app_firewall")
@patch("waf_policy_create.function.session")
def test_create_waf_policy_already_exists(mock_session, mock_app_fw, mock_get_params):
    """Handle WAF policy that already exists (idempotent)."""
    from waf_policy_create.function import create_waf
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_api = MagicMock()
    mock_api.create.side_effect = Exception("already exist")
    mock_app_fw.return_value = mock_api

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
@patch("waf_policy_create.function.app_firewall")
@patch("waf_policy_create.function.session")
def test_create_waf_policy_http_409_conflict(mock_session, mock_app_fw, mock_get_params):
    """Handle HTTP 409 Conflict status code."""
    from waf_policy_create.function import create_waf
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_api = MagicMock()

    # Create exception with status_code attribute
    conflict_error = Exception("API Error")
    conflict_error.status_code = 409
    mock_api.create.side_effect = conflict_error
    mock_app_fw.return_value = mock_api

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-waf", "namespace": "test-ns"},
        "spec": {"mode": "BLOCKING"}
    }

    result = create_waf(event, logger)

    assert result["status"] == "success"
    assert result["already_existed"] is True


@pytest.mark.parametrize("error_message", [
    "already exist",
    "Resource already exists",
    "ALREADY EXISTS in namespace",
    "duplicate entry found",
    "Duplicate resource",
    "conflict detected",
    "Conflict: resource exists",
])
@patch("waf_policy_create.function.get_ssm_parameters")
@patch("waf_policy_create.function.app_firewall")
@patch("waf_policy_create.function.session")
def test_create_waf_policy_already_exists_patterns(mock_session, mock_app_fw, mock_get_params, error_message):
    """Handle various 'already exists' error message patterns."""
    from waf_policy_create.function import create_waf
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_api = MagicMock()
    mock_api.create.side_effect = Exception(error_message)
    mock_app_fw.return_value = mock_api

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-waf", "namespace": "test-ns"},
        "spec": {"mode": "BLOCKING"}
    }

    result = create_waf(event, logger)

    assert result["status"] == "success"
    assert result["already_existed"] is True


@patch("waf_policy_create.function.app_firewall")
@patch("waf_policy_create.function.session")
def test_create_waf_policy_transient_error_triggers_retry(mock_session, mock_app_fw):
    """Test that TransientError triggers retries in _create_waf_with_retry."""
    from waf_policy_create.function import _create_waf_with_retry
    from shared.errors import TransientError

    mock_api = MagicMock()
    # First two calls fail with transient error, third succeeds
    mock_api.create.side_effect = [
        Exception("Connection timeout"),
        Exception("Gateway error"),
        None,  # Success on third attempt
    ]

    # Should not raise - retries succeed
    _create_waf_with_retry(mock_api, {"metadata": {"name": "test"}}, "test-ns")

    assert mock_api.create.call_count == 3


@patch("waf_policy_create.function.app_firewall")
@patch("waf_policy_create.function.session")
def test_create_waf_policy_non_retryable_error_no_retry(mock_session, mock_app_fw):
    """Test that 'already exists' errors do not trigger retries."""
    from waf_policy_create.function import _create_waf_with_retry

    mock_api = MagicMock()
    mock_api.create.side_effect = Exception("Resource already exists")

    # Should raise immediately without retrying
    with pytest.raises(Exception) as exc_info:
        _create_waf_with_retry(mock_api, {"metadata": {"name": "test"}}, "test-ns")

    assert "already exists" in str(exc_info.value)
    # Should only be called once - no retries for already exists errors
    assert mock_api.create.call_count == 1
