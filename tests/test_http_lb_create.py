# tests/test_http_lb_create.py
import pytest
from unittest.mock import MagicMock, patch


@patch("http_lb_create.function.get_ssm_parameters")
@patch("http_lb_create.function.http_loadbalancer")
@patch("http_lb_create.function.session")
def test_create_http_lb_success(mock_session, mock_http_lb, mock_get_params):
    """Successfully create an HTTP load balancer."""
    from http_lb_create.function import create_lb
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_api = MagicMock()
    mock_http_lb.return_value = mock_api

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-lb", "namespace": "test-ns"},
        "spec": {
            "domains": ["test.example.com"],
            "default_route_pools": [{"pool": {"name": "test-pool", "namespace": "test-ns"}}]
        }
    }

    result = create_lb(event, logger)

    assert result["status"] == "success"
    assert result["name"] == "test-lb"
    mock_api.create.assert_called_once()


@patch("http_lb_create.function.get_ssm_parameters")
@patch("http_lb_create.function.http_loadbalancer")
@patch("http_lb_create.function.session")
def test_create_http_lb_already_exists(mock_session, mock_http_lb, mock_get_params):
    """Handle HTTP load balancer that already exists (idempotent)."""
    from http_lb_create.function import create_lb
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_api = MagicMock()
    mock_api.create.side_effect = Exception("already exist")
    mock_http_lb.return_value = mock_api

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-lb", "namespace": "test-ns"},
        "spec": {"domains": ["test.example.com"]}
    }

    result = create_lb(event, logger)

    assert result["status"] == "success"
    assert result["already_existed"] is True


@patch("http_lb_create.function.get_ssm_parameters")
@patch("http_lb_create.function.http_loadbalancer")
@patch("http_lb_create.function.session")
def test_create_http_lb_http_409_conflict(mock_session, mock_http_lb, mock_get_params):
    """Handle HTTP 409 Conflict status code."""
    from http_lb_create.function import create_lb
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_api = MagicMock()

    # Create exception with status_code attribute
    conflict_error = Exception("API Error")
    conflict_error.status_code = 409
    mock_api.create.side_effect = conflict_error
    mock_http_lb.return_value = mock_api

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-lb", "namespace": "test-ns"},
        "spec": {"domains": ["test.example.com"]}
    }

    result = create_lb(event, logger)

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
@patch("http_lb_create.function.get_ssm_parameters")
@patch("http_lb_create.function.http_loadbalancer")
@patch("http_lb_create.function.session")
def test_create_http_lb_already_exists_patterns(mock_session, mock_http_lb, mock_get_params, error_message):
    """Handle various 'already exists' error message patterns."""
    from http_lb_create.function import create_lb
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_api = MagicMock()
    mock_api.create.side_effect = Exception(error_message)
    mock_http_lb.return_value = mock_api

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-lb", "namespace": "test-ns"},
        "spec": {"domains": ["test.example.com"]}
    }

    result = create_lb(event, logger)

    assert result["status"] == "success"
    assert result["already_existed"] is True


@patch("http_lb_create.function.get_ssm_parameters")
@patch("http_lb_create.function.http_loadbalancer")
@patch("http_lb_create.function.session")
def test_create_http_lb_http_409_via_response(mock_session, mock_http_lb, mock_get_params):
    """Handle HTTP 409 Conflict via response object."""
    from http_lb_create.function import create_lb
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_api = MagicMock()

    # Create exception with response.status_code attribute
    conflict_error = Exception("API Error")
    conflict_error.response = MagicMock()
    conflict_error.response.status_code = 409
    mock_api.create.side_effect = conflict_error
    mock_http_lb.return_value = mock_api

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-lb", "namespace": "test-ns"},
        "spec": {"domains": ["test.example.com"]}
    }

    result = create_lb(event, logger)

    assert result["status"] == "success"
    assert result["already_existed"] is True


@patch("http_lb_create.function.http_loadbalancer")
@patch("http_lb_create.function.session")
def test_create_http_lb_transient_error_triggers_retry(mock_session, mock_http_lb):
    """Test that transient errors trigger retries."""
    from http_lb_create.function import _create_http_lb_with_retry

    mock_api = MagicMock()
    call_count = 0

    def failing_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("Gateway timeout")
        return None

    mock_api.create.side_effect = failing_create

    with patch("shared.decorators.time.sleep"):
        _create_http_lb_with_retry(mock_api, {"metadata": {"name": "test"}}, "test-ns")

    assert call_count == 3


@patch("http_lb_create.function.http_loadbalancer")
@patch("http_lb_create.function.session")
def test_create_http_lb_already_exists_no_retry(mock_session, mock_http_lb):
    """Test that 'already exists' errors do not trigger retries."""
    from http_lb_create.function import _create_http_lb_with_retry

    mock_api = MagicMock()
    call_count = 0

    def already_exists_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise Exception("Resource already exists")

    mock_api.create.side_effect = already_exists_create

    with patch("shared.decorators.time.sleep"):
        with pytest.raises(Exception) as exc_info:
            _create_http_lb_with_retry(mock_api, {"metadata": {"name": "test"}}, "test-ns")

    assert "already exists" in str(exc_info.value)
    assert call_count == 1  # No retries for already exists errors


@patch("http_lb_create.function.http_loadbalancer")
@patch("http_lb_create.function.session")
def test_create_http_lb_conflict_status_no_retry(mock_session, mock_http_lb):
    """Test that HTTP 409 Conflict errors do not trigger retries."""
    from http_lb_create.function import _create_http_lb_with_retry

    mock_api = MagicMock()
    call_count = 0

    def conflict_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        error = Exception("API Error")
        error.status_code = 409
        raise error

    mock_api.create.side_effect = conflict_create

    with patch("shared.decorators.time.sleep"):
        with pytest.raises(Exception) as exc_info:
            _create_http_lb_with_retry(mock_api, {"metadata": {"name": "test"}}, "test-ns")

    assert exc_info.value.status_code == 409
    assert call_count == 1  # No retries for 409 errors
