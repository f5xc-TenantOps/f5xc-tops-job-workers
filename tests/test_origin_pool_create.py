import pytest
from unittest.mock import MagicMock, patch


@patch("origin_pool_create.function.get_ssm_parameters")
@patch("origin_pool_create.function.XCClient")
def test_create_origin_pool_success(mock_xc_client_class, mock_get_params):
    """Successfully create an origin pool."""
    from origin_pool_create.function import create_pool
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_client = MagicMock()
    mock_xc_client_class.return_value = mock_client

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-pool", "namespace": "test-ns"},
        "spec": {"port": 80, "origin_servers": [{"public_name": {"dns_name": "api.example.com"}}]}
    }

    result = create_pool(event, logger)

    assert result["status"] == "success"
    assert result["name"] == "test-pool"
    assert result["created"] is True
    mock_client.create_origin_pool.assert_called_once_with(
        "test-ns",
        {"metadata": {"name": "test-pool", "namespace": "test-ns"}, "spec": event["spec"]}
    )


@patch("origin_pool_create.function.get_ssm_parameters")
@patch("origin_pool_create.function.XCClient")
def test_create_origin_pool_already_exists(mock_xc_client_class, mock_get_params):
    """Handle origin pool that already exists (idempotent)."""
    from origin_pool_create.function import create_pool
    from shared.logging import StructuredLogger
    from shared.errors import ResourceExistsError

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_client = MagicMock()
    mock_client.create_origin_pool.side_effect = ResourceExistsError("Resource already exists")
    mock_xc_client_class.return_value = mock_client

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
@patch("origin_pool_create.function.XCClient")
def test_create_origin_pool_permanent_error_raises(mock_xc_client_class, mock_get_params):
    """Permanent errors are raised to caller."""
    from origin_pool_create.function import create_pool
    from shared.logging import StructuredLogger
    from shared.errors import PermanentError

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_client = MagicMock()
    mock_client.create_origin_pool.side_effect = PermanentError("Invalid payload")
    mock_xc_client_class.return_value = mock_client

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-pool", "namespace": "test-ns"},
        "spec": {"port": 80}
    }

    with pytest.raises(PermanentError):
        create_pool(event, logger)


@patch("origin_pool_create.function.get_ssm_parameters")
@patch("origin_pool_create.function.XCClient")
def test_create_origin_pool_client_init(mock_xc_client_class, mock_get_params):
    """XCClient initialized with correct parameters."""
    from origin_pool_create.function import create_pool
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "my-token"}

    mock_client = MagicMock()
    mock_xc_client_class.return_value = mock_client

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-pool", "namespace": "test-ns"},
        "spec": {"port": 80}
    }

    create_pool(event, logger)

    mock_xc_client_class.assert_called_once_with(
        tenant_url="https://test.console.ves.volterra.io",
        api_token="my-token",
        validate=False
    )
