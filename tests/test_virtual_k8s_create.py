"""Tests for virtual_k8s_create lambda."""

import pytest
from unittest.mock import MagicMock, patch, call


@patch("virtual_k8s_create.function.time")
@patch("virtual_k8s_create.function.get_ssm_parameters")
@patch("virtual_k8s_create.function.XCClient")
def test_create_vk8s_success(mock_xc_client_class, mock_get_params, mock_time):
    """Successfully create vk8s and poll until ready."""
    from virtual_k8s_create.function import create_vk8s
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_virtual_k8s.return_value = {
        "metadata": {"name": "fuzzy-cat-vk8s"}
    }
    # First poll: not ready yet, second poll: ready
    mock_client.get_virtual_k8s.side_effect = [
        Exception("not ready"),
        {"metadata": {"name": "fuzzy-cat-vk8s"}, "spec": {}},
    ]
    mock_xc_client_class.return_value = mock_client

    # Mock time so polling doesn't actually wait
    mock_time.time.side_effect = [0, 5, 10]
    mock_time.sleep = MagicMock()

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/mcn-lab",
        "metadata": {"name": "fuzzy-cat-vk8s", "namespace": "fuzzy-cat"},
        "spec": {
            "vsite_refs": [{"name": "vs1", "namespace": "shared", "tenant": "t1"}]
        },
    }

    result = create_vk8s(event, logger)

    assert result["status"] == "success"
    assert result["name"] == "fuzzy-cat-vk8s"
    assert result["created"] is True

    mock_client.create_virtual_k8s.assert_called_once()
    payload = mock_client.create_virtual_k8s.call_args[0][1]
    assert payload["metadata"]["name"] == "fuzzy-cat-vk8s"


@patch("virtual_k8s_create.function.get_ssm_parameters")
@patch("virtual_k8s_create.function.XCClient")
def test_create_vk8s_already_exists(mock_xc_client_class, mock_get_params):
    """vk8s already exists - treat as success, skip polling."""
    from virtual_k8s_create.function import create_vk8s
    from shared.logging import StructuredLogger
    from shared.errors import ResourceExistsError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_virtual_k8s.side_effect = ResourceExistsError("exists")
    mock_xc_client_class.return_value = mock_client

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/mcn-lab",
        "metadata": {"name": "fuzzy-cat-vk8s", "namespace": "fuzzy-cat"},
        "spec": {"vsite_refs": [{"name": "vs1", "namespace": "shared", "tenant": "t1"}]},
    }

    result = create_vk8s(event, logger)

    assert result["status"] == "success"
    assert result["already_existed"] is True


@patch("virtual_k8s_create.function.time")
@patch("virtual_k8s_create.function.get_ssm_parameters")
@patch("virtual_k8s_create.function.XCClient")
def test_create_vk8s_timeout(mock_xc_client_class, mock_get_params, mock_time):
    """Raises TransientError when vk8s not ready within timeout."""
    from virtual_k8s_create.function import create_vk8s
    from shared.logging import StructuredLogger
    from shared.errors import TransientError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_virtual_k8s.return_value = {"metadata": {"name": "fuzzy-cat-vk8s"}}
    mock_client.get_virtual_k8s.side_effect = Exception("not ready")
    mock_xc_client_class.return_value = mock_client

    # Simulate time passing beyond 60s timeout
    mock_time.time.side_effect = [0, 10, 20, 30, 40, 50, 60, 70]
    mock_time.sleep = MagicMock()

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/mcn-lab",
        "metadata": {"name": "fuzzy-cat-vk8s", "namespace": "fuzzy-cat"},
        "spec": {"vsite_refs": [{"name": "vs1", "namespace": "shared", "tenant": "t1"}]},
    }

    with pytest.raises(TransientError, match="not available within 60 seconds"):
        create_vk8s(event, logger)


@patch("virtual_k8s_create.function.get_ssm_parameters")
@patch("virtual_k8s_create.function.XCClient")
def test_create_vk8s_permanent_error_raises(mock_xc_client_class, mock_get_params):
    """Permanent errors from creation propagate."""
    from virtual_k8s_create.function import create_vk8s
    from shared.logging import StructuredLogger
    from shared.errors import PermanentError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_virtual_k8s.side_effect = PermanentError("Invalid payload")
    mock_xc_client_class.return_value = mock_client

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/mcn-lab",
        "metadata": {"name": "test-vk8s", "namespace": "test"},
        "spec": {"vsite_refs": []}
    }

    with pytest.raises(PermanentError):
        create_vk8s(event, logger)


@patch("virtual_k8s_create.function.StateManager")
@patch("virtual_k8s_create.function.time")
@patch("virtual_k8s_create.function.get_ssm_parameters")
@patch("virtual_k8s_create.function.XCClient")
def test_handler_tracks_state(mock_xc_client_class, mock_get_params, mock_time, mock_state_manager_class):
    """Handler updates job state on success."""
    from virtual_k8s_create.function import handler

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_virtual_k8s.return_value = {"metadata": {"name": "test-vk8s"}}
    mock_client.get_virtual_k8s.return_value = {"metadata": {"name": "test-vk8s"}, "spec": {}}
    mock_xc_client_class.return_value = mock_client

    mock_time.time.side_effect = [0, 5]
    mock_time.sleep = MagicMock()

    mock_state_manager = MagicMock()
    mock_state_manager_class.return_value = mock_state_manager

    class MockContext:
        function_name = "virtual_k8s_create"

    event = {
        "ssm_base_path": "/tenantOps/mcn-lab",
        "metadata": {"name": "test-vk8s", "namespace": "test"},
        "spec": {"vsite_refs": [{"name": "vs1", "namespace": "shared", "tenant": "t1"}]},
        "job_state": {
            "job_execution_id": "exec-1",
            "job_id": "job-1",
            "trigger_source": "test",
            "email": "test@f5.com",
            "petname": "test",
            "dep_id": "dep-123",
        },
    }

    result = handler(event, MockContext())

    assert result["statusCode"] == 200
    assert result["body"]["status"] == "success"

    # Verify state was updated
    assert mock_state_manager.update_state.called
