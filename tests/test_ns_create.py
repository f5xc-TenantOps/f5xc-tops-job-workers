# tests/test_ns_create.py
import pytest
from unittest.mock import MagicMock, patch


@patch("ns_create.function.get_ssm_parameters")
@patch("ns_create.function.XCClient")
def test_create_namespace_success(mock_xc_client, mock_get_params):
    """Successfully create a namespace."""
    from ns_create.function import handler
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_namespace.return_value = {"metadata": {"name": "test-ns"}}
    mock_client.get_namespace.return_value = {"metadata": {"name": "test-ns"}}
    mock_xc_client.return_value = mock_client

    class MockContext:
        function_name = "ns_create"

    event = {
        "ssm_base_path": "/tenantOps/test",
        "namespace_name": "test-ns",
        "description": "Test namespace"
    }

    result = handler(event, MockContext())

    assert result["statusCode"] == 200
    assert "created successfully" in result["body"]
    assert "available" in result["body"]
    mock_client.create_namespace.assert_called_once_with("test-ns", "Test namespace")
    mock_xc_client.assert_called_once_with(
        tenant_url="https://test.console.ves.volterra.io",
        api_token="token",
        validate=False
    )


@patch("ns_create.function.get_ssm_parameters")
@patch("ns_create.function.XCClient")
def test_create_namespace_already_exists(mock_xc_client, mock_get_params):
    """Handle namespace that already exists (idempotent)."""
    from ns_create.function import handler
    from shared.errors import ResourceExistsError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_namespace.side_effect = ResourceExistsError("already exists")
    mock_client.get_namespace.return_value = {"metadata": {"name": "test-ns"}}
    mock_xc_client.return_value = mock_client

    class MockContext:
        function_name = "ns_create"

    event = {
        "ssm_base_path": "/tenantOps/test",
        "namespace_name": "test-ns",
        "description": "Test namespace"
    }

    result = handler(event, MockContext())

    assert result["statusCode"] == 200
    assert "already exists" in result["body"]
    assert "available" in result["body"]


@patch("ns_create.function.get_ssm_parameters")
@patch("ns_create.function.XCClient")
def test_create_namespace_no_description(mock_xc_client, mock_get_params):
    """Create namespace without description."""
    from ns_create.function import handler

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_namespace.return_value = {"metadata": {"name": "test-ns"}}
    mock_client.get_namespace.return_value = {"metadata": {"name": "test-ns"}}
    mock_xc_client.return_value = mock_client

    class MockContext:
        function_name = "ns_create"

    event = {
        "ssm_base_path": "/tenantOps/test",
        "namespace_name": "test-ns"
    }

    result = handler(event, MockContext())

    assert result["statusCode"] == 200
    assert "created successfully" in result["body"]
    mock_client.create_namespace.assert_called_once_with("test-ns", "")


def test_validate_payload_missing_fields():
    """Raise PermanentError when required fields are missing."""
    from ns_create.function import validate_payload
    from shared.errors import PermanentError

    with pytest.raises(PermanentError, match="Missing required fields"):
        validate_payload({})

    with pytest.raises(PermanentError, match="namespace_name"):
        validate_payload({"ssm_base_path": "/test"})

    with pytest.raises(PermanentError, match="ssm_base_path"):
        validate_payload({"namespace_name": "test"})


@patch("ns_create.function.get_ssm_parameters")
@patch("ns_create.function.XCClient")
@patch("ns_create.function.time.sleep")
def test_wait_for_namespace_timeout(mock_sleep, mock_xc_client, mock_get_params):
    """Raise TransientError when namespace is not available within timeout."""
    from ns_create.function import wait_for_namespace
    from shared.errors import TransientError, ResourceNotFoundError
    from shared.logging import StructuredLogger

    mock_client = MagicMock()
    mock_client.get_namespace.side_effect = ResourceNotFoundError("not found")

    logger = StructuredLogger("test", "test-correlation-id")

    with pytest.raises(TransientError, match="was not available"):
        wait_for_namespace(mock_client, "test-ns", logger, timeout=1, interval=1)


@patch("ns_create.function.StateManager")
@patch("ns_create.function.get_ssm_parameters")
@patch("ns_create.function.XCClient")
def test_state_updates_on_success(mock_xc_client, mock_get_params, mock_state_manager_cls):
    """Namespace creation updates state on start and completion."""
    from ns_create.function import handler

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "test-token"
    }
    mock_client = MagicMock()
    mock_xc_client.return_value = mock_client
    mock_client.get_namespace.return_value = {"name": "test-ns"}

    mock_state_manager = MagicMock()
    mock_state_manager_cls.return_value = mock_state_manager

    class MockContext:
        function_name = "ns_create"

    event = {
        "ssm_base_path": "/test",
        "namespace_name": "test-ns",
        "job_state": {
            "job_execution_id": "exec-123",
            "job_id": "job-456",
            "trigger_source": "udf",
            "email": "user@test.com",
            "petname": "test-ns",
            "dep_id": "dep-789",
            "status": "IN_PROGRESS",
            "steps": {},
            "resources": {},
        },
        "lab_id": "lab-001",
    }

    result = handler(event, MockContext())

    assert result["statusCode"] == 200
    # Verify state was updated
    mock_state_manager.mark_step_started.assert_called_once()
    mock_state_manager.mark_step_complete.assert_called_once()
