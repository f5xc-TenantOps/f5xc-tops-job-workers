# tests/test_http_lb_create.py
import pytest
from unittest.mock import MagicMock, patch


@patch("http_lb_create.function.get_ssm_parameters")
@patch("http_lb_create.function.XCClient")
def test_create_http_lb_success(mock_xc_client_class, mock_get_params):
    """Successfully create an HTTP load balancer."""
    from http_lb_create.function import create_lb
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_client = MagicMock()
    mock_xc_client_class.return_value = mock_client

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
    assert result["created"] is True
    mock_client.create_http_loadbalancer.assert_called_once_with(
        "test-ns",
        {"metadata": {"name": "test-lb", "namespace": "test-ns"}, "spec": event["spec"]}
    )


@patch("http_lb_create.function.get_ssm_parameters")
@patch("http_lb_create.function.XCClient")
def test_create_http_lb_already_exists(mock_xc_client_class, mock_get_params):
    """Handle HTTP load balancer that already exists (idempotent)."""
    from http_lb_create.function import create_lb
    from shared.logging import StructuredLogger
    from shared.errors import ResourceExistsError

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_client = MagicMock()
    mock_client.create_http_loadbalancer.side_effect = ResourceExistsError("Resource already exists")
    mock_xc_client_class.return_value = mock_client

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
@patch("http_lb_create.function.XCClient")
def test_create_http_lb_permanent_error_raises(mock_xc_client_class, mock_get_params):
    """Permanent errors are raised to caller."""
    from http_lb_create.function import create_lb
    from shared.logging import StructuredLogger
    from shared.errors import PermanentError

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "token"}

    mock_client = MagicMock()
    mock_client.create_http_loadbalancer.side_effect = PermanentError("Invalid payload")
    mock_xc_client_class.return_value = mock_client

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-lb", "namespace": "test-ns"},
        "spec": {"domains": ["test.example.com"]}
    }

    with pytest.raises(PermanentError):
        create_lb(event, logger)


@patch("http_lb_create.function.get_ssm_parameters")
@patch("http_lb_create.function.XCClient")
def test_create_http_lb_client_init(mock_xc_client_class, mock_get_params):
    """XCClient initialized with correct parameters."""
    from http_lb_create.function import create_lb
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {"tenant-url": "https://test.console.ves.volterra.io", "token-value": "my-token"}

    mock_client = MagicMock()
    mock_xc_client_class.return_value = mock_client

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-lb", "namespace": "test-ns"},
        "spec": {"domains": ["test.example.com"]}
    }

    create_lb(event, logger)

    mock_xc_client_class.assert_called_once_with(
        tenant_url="https://test.console.ves.volterra.io",
        api_token="my-token",
        validate=False
    )


@patch("http_lb_create.function.StateManager")
@patch("http_lb_create.function.get_ssm_parameters")
@patch("http_lb_create.function.XCClient")
def test_handler_publishes_lb_hostname_output(mock_xc_client_class, mock_get_params, mock_state_manager_class):
    """Handler publishes lb_hostname via add_output."""
    from http_lb_create.function import handler

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_xc_client_class.return_value = mock_client

    mock_state_manager = MagicMock()
    mock_state_manager_class.return_value = mock_state_manager

    class MockContext:
        function_name = "http_lb_create"

    event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-lb", "namespace": "test-ns"},
        "spec": {"domains": ["fuzzy-cat.lab-sec.f5demos.com"]},
        "job_state": {
            "job_execution_id": "exec-1",
            "job_id": "job-1",
            "trigger_source": "test",
            "email": "test@f5.com",
            "petname": "fuzzy-cat",
            "dep_id": "dep-123",
        },
    }

    result = handler(event, MockContext())

    assert result["statusCode"] == 200

    # Verify lb_hostname was published as output
    mock_state_manager.add_output.assert_called_once()
    add_output_call = mock_state_manager.add_output.call_args
    assert add_output_call[0][1] == "lb_hostname"
    assert add_output_call[0][2] == "fuzzy-cat.lab-sec.f5demos.com"
