import pytest
from unittest.mock import MagicMock, patch


@patch("origin_pool_create.function._get_parameters")
@patch("origin_pool_create.function._get_xc_client")
def test_create_origin_pool_success(mock_get_xc_client, mock_get_params):
    """Successfully create an origin pool."""
    from origin_pool_create.function import create_pool
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_origin_pool = MagicMock()
    mock_session = MagicMock()
    mock_api = MagicMock()
    mock_origin_pool.return_value = mock_api
    mock_get_xc_client.return_value = (mock_origin_pool, mock_session)

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


@patch("origin_pool_create.function._get_parameters")
@patch("origin_pool_create.function._get_xc_client")
def test_create_origin_pool_already_exists(mock_get_xc_client, mock_get_params):
    """Handle origin pool that already exists (idempotent)."""
    from origin_pool_create.function import create_pool
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_origin_pool = MagicMock()
    mock_session = MagicMock()
    mock_api = MagicMock()
    mock_api.create.side_effect = Exception("already exist")
    mock_api.get.return_value = {"metadata": {"name": "test-pool"}}
    mock_origin_pool.return_value = mock_api
    mock_get_xc_client.return_value = (mock_origin_pool, mock_session)

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-pool", "namespace": "test-ns"},
        "spec": {"port": 80}
    }

    result = create_pool(event, logger)

    assert result["status"] == "success"
    assert result["already_existed"] is True
