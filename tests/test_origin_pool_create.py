import pytest
from unittest.mock import MagicMock, patch


@patch("origin_pool_create.function.get_ssm_parameters")
@patch("origin_pool_create.function.origin_pool")
@patch("origin_pool_create.function.session")
def test_create_origin_pool_success(mock_session, mock_origin_pool, mock_get_params):
    """Successfully create an origin pool."""
    from origin_pool_create.function import create_pool
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_api = MagicMock()
    mock_origin_pool.return_value = mock_api

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-pool", "namespace": "test-ns"},
        "spec": {"port": 80, "origin_servers": [{"public_name": {"dns_name": "api.example.com"}}]}
    }

    result = create_pool(event, logger)

    assert result["status"] == "success"
    assert result["name"] == "test-pool"
    mock_api.create.assert_called_once()


@patch("origin_pool_create.function.get_ssm_parameters")
@patch("origin_pool_create.function.origin_pool")
@patch("origin_pool_create.function.session")
def test_create_origin_pool_already_exists(mock_session, mock_origin_pool, mock_get_params):
    """Handle origin pool that already exists (idempotent)."""
    from origin_pool_create.function import create_pool
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_api = MagicMock()
    mock_api.create.side_effect = Exception("already exist")
    mock_api.get.return_value = {"metadata": {"name": "test-pool"}}
    mock_origin_pool.return_value = mock_api

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-pool", "namespace": "test-ns"},
        "spec": {"port": 80}
    }

    result = create_pool(event, logger)

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
@patch("origin_pool_create.function.get_ssm_parameters")
@patch("origin_pool_create.function.origin_pool")
@patch("origin_pool_create.function.session")
def test_create_origin_pool_already_exists_patterns(mock_session, mock_origin_pool, mock_get_params, error_message):
    """Handle various 'already exists' error message patterns."""
    from origin_pool_create.function import create_pool
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_api = MagicMock()
    mock_api.create.side_effect = Exception(error_message)
    mock_origin_pool.return_value = mock_api

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-pool", "namespace": "test-ns"},
        "spec": {"port": 80}
    }

    result = create_pool(event, logger)

    assert result["status"] == "success"
    assert result["already_existed"] is True


@patch("origin_pool_create.function.get_ssm_parameters")
@patch("origin_pool_create.function.origin_pool")
@patch("origin_pool_create.function.session")
def test_create_origin_pool_http_409_conflict(mock_session, mock_origin_pool, mock_get_params):
    """Handle HTTP 409 Conflict status code."""
    from origin_pool_create.function import create_pool
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_api = MagicMock()

    # Create exception with status_code attribute
    conflict_error = Exception("API Error")
    conflict_error.status_code = 409
    mock_api.create.side_effect = conflict_error
    mock_origin_pool.return_value = mock_api

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-pool", "namespace": "test-ns"},
        "spec": {"port": 80}
    }

    result = create_pool(event, logger)

    assert result["status"] == "success"
    assert result["already_existed"] is True


@patch("origin_pool_create.function.get_ssm_parameters")
@patch("origin_pool_create.function.origin_pool")
@patch("origin_pool_create.function.session")
def test_create_origin_pool_http_409_via_response(mock_session, mock_origin_pool, mock_get_params):
    """Handle HTTP 409 Conflict via response object."""
    from origin_pool_create.function import create_pool
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_api = MagicMock()

    # Create exception with response.status_code attribute
    conflict_error = Exception("API Error")
    conflict_error.response = MagicMock()
    conflict_error.response.status_code = 409
    mock_api.create.side_effect = conflict_error
    mock_origin_pool.return_value = mock_api

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-pool", "namespace": "test-ns"},
        "spec": {"port": 80}
    }

    result = create_pool(event, logger)

    assert result["status"] == "success"
    assert result["already_existed"] is True
