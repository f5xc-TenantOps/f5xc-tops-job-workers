import pytest
from unittest.mock import MagicMock, patch, call


@patch("securemesh_site_v2_create.function.get_ssm_parameters")
@patch("securemesh_site_v2_create.function.XCClient")
def test_create_site_success(mock_xc_client_class, mock_get_params):
    """Successfully create site and return token."""
    from securemesh_site_v2_create.function import create_site
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_securemesh_site_v2.return_value = {
        "metadata": {"name": "fuzzy-cat-site"},
        "spec": {"site_state": "WAITING_FOR_REGISTRATION"}
    }
    mock_client.create_registration_token.return_value = {
        "spec": {"content": "eyJhbGci.jwt.token", "site_name": "fuzzy-cat-site"}
    }
    mock_xc_client_class.return_value = mock_client

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/mcn-lab",
        "metadata": {"name": "fuzzy-cat-site", "namespace": "system"},
        "spec": {"kvm": {"not_managed": {}}},
    }

    result = create_site(event, logger)

    assert result["status"] == "success"
    assert result["name"] == "fuzzy-cat-site"
    assert result["created"] is True
    assert result["site_token"] == "eyJhbGci.jwt.token"

    # Verify site was created
    mock_client.create_securemesh_site_v2.assert_called_once()
    create_payload = mock_client.create_securemesh_site_v2.call_args[0][0]
    assert create_payload["metadata"]["name"] == "fuzzy-cat-site"
    assert create_payload["namespace"] == "system"

    # Verify token was created (name starts with jwt-token-)
    mock_client.create_registration_token.assert_called_once()
    token_call_args = mock_client.create_registration_token.call_args[0]
    assert token_call_args[0] == "fuzzy-cat-site"  # site_name
    assert token_call_args[1].startswith("jwt-token-")  # token_name


@patch("securemesh_site_v2_create.function.get_ssm_parameters")
@patch("securemesh_site_v2_create.function.XCClient")
def test_create_site_already_exists(mock_xc_client_class, mock_get_params):
    """Site already exists - still create token."""
    from securemesh_site_v2_create.function import create_site
    from shared.logging import StructuredLogger
    from shared.errors import ResourceExistsError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_securemesh_site_v2.side_effect = ResourceExistsError("exists")
    mock_client.create_registration_token.return_value = {
        "spec": {"content": "eyJhbGci.jwt.token", "site_name": "fuzzy-cat-site"}
    }
    mock_xc_client_class.return_value = mock_client

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/mcn-lab",
        "metadata": {"name": "fuzzy-cat-site", "namespace": "system"},
        "spec": {"kvm": {"not_managed": {}}},
    }

    result = create_site(event, logger)

    assert result["status"] == "success"
    assert result["already_existed"] is True
    assert result["site_token"] == "eyJhbGci.jwt.token"

    # Token should still be created even if site already existed
    mock_client.create_registration_token.assert_called_once()


@patch("securemesh_site_v2_create.function.get_ssm_parameters")
@patch("securemesh_site_v2_create.function.XCClient")
def test_create_site_permanent_error_raises(mock_xc_client_class, mock_get_params):
    """Permanent errors from site creation propagate."""
    from securemesh_site_v2_create.function import create_site
    from shared.logging import StructuredLogger
    from shared.errors import PermanentError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_securemesh_site_v2.side_effect = PermanentError("Invalid payload")
    mock_xc_client_class.return_value = mock_client

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/mcn-lab",
        "metadata": {"name": "test-site", "namespace": "system"},
        "spec": {"kvm": {"not_managed": {}}}
    }

    with pytest.raises(PermanentError):
        create_site(event, logger)


@patch("securemesh_site_v2_create.function.StateManager")
@patch("securemesh_site_v2_create.function.get_ssm_parameters")
@patch("securemesh_site_v2_create.function.XCClient")
def test_handler_publishes_site_token_output(mock_xc_client_class, mock_get_params, mock_state_manager_class):
    """Handler publishes site_token via add_output."""
    from securemesh_site_v2_create.function import handler

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_securemesh_site_v2.return_value = {"metadata": {"name": "test-site"}}
    mock_client.create_registration_token.return_value = {
        "spec": {"content": "jwt-abc-123", "site_name": "test-site"}
    }
    mock_xc_client_class.return_value = mock_client

    mock_state_manager = MagicMock()
    mock_state_manager_class.return_value = mock_state_manager

    class MockContext:
        function_name = "securemesh_site_v2_create"

    event = {
        "ssm_base_path": "/tenantOps/mcn-lab",
        "metadata": {"name": "test-site", "namespace": "system"},
        "spec": {"kvm": {"not_managed": {}}},
        "job_state": {
            "job_execution_id": "exec-1",
            "job_id": "job-1",
            "trigger_source": "test",
            "email": "test@f5.com",
            "petname": "test-site",
            "dep_id": "dep-123",
        },
    }

    result = handler(event, MockContext())

    assert result["statusCode"] == 200
    assert result["body"]["status"] == "success"

    # Verify site_token was published as output
    mock_state_manager.add_output.assert_called_once()
    add_output_call = mock_state_manager.add_output.call_args
    assert add_output_call[0][1] == "site_token"
    assert add_output_call[0][2] == "jwt-abc-123"
