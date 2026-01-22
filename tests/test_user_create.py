# tests/test_user_create.py
import pytest
from unittest.mock import MagicMock, patch


@patch("user_create.function.get_ssm_parameters")
@patch("user_create.function.XCClient")
def test_create_user_success(mock_xc_client_class, mock_get_params):
    """Successfully create a new user."""
    from user_create.function import handler

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_xc_client_class.return_value = mock_client

    class MockContext:
        function_name = "user_create"

    event = {
        "ssm_base_path": "/tenantOps/test",
        "first_name": "Test",
        "last_name": "User",
        "email": "test@example.com",
        "group_names": ["lab-users"],
        "namespace_roles": [{"namespace": "default", "role": "ves-io-monitor-role"}]
    }

    result = handler(event, MockContext())

    assert result["statusCode"] == 200
    assert "created successfully" in result["body"]
    mock_client.create_user.assert_called_once_with(
        "test@example.com",
        "Test",
        "User",
        ["lab-users"],
        [{"namespace": "default", "role": "ves-io-monitor-role"}]
    )
    mock_xc_client_class.assert_called_once_with(
        tenant_url="https://test.console.ves.volterra.io",
        api_token="token",
        validate=False
    )


@patch("user_create.function.get_ssm_parameters")
@patch("user_create.function.XCClient")
def test_create_user_already_exists_with_updates(mock_xc_client_class, mock_get_params):
    """User already exists, update with new roles and groups."""
    from user_create.function import handler
    from shared.errors import ResourceExistsError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_user.side_effect = ResourceExistsError("User already exists")
    mock_client.get_user.return_value = {
        "email": "test@example.com",
        "first_name": "Test",
        "last_name": "User",
        "group_names": ["existing-group"],
        "namespace_roles": [{"namespace": "system", "role": "ves-io-admin-role"}]
    }
    mock_xc_client_class.return_value = mock_client

    class MockContext:
        function_name = "user_create"

    event = {
        "ssm_base_path": "/tenantOps/test",
        "first_name": "Test",
        "last_name": "User",
        "email": "test@example.com",
        "group_names": ["new-group"],
        "namespace_roles": [{"namespace": "default", "role": "ves-io-monitor-role"}]
    }

    result = handler(event, MockContext())

    assert result["statusCode"] == 200
    assert "updated successfully" in result["body"]
    mock_client.create_user.assert_called_once()
    mock_client.get_user.assert_called_once_with("test@example.com")
    mock_client.update_user.assert_called_once()

    # Verify merged roles and groups were passed
    call_args = mock_client.update_user.call_args
    assert call_args[0][0] == "test@example.com"  # email
    assert call_args[0][1] == "Test"  # first_name
    assert call_args[0][2] == "User"  # last_name
    # merged_roles should contain both old and new roles
    merged_roles = call_args[0][3]
    assert len(merged_roles) == 2
    # merged_groups should contain both old and new groups
    merged_groups = call_args[0][4]
    assert set(merged_groups) == {"existing-group", "new-group"}


@patch("user_create.function.get_ssm_parameters")
@patch("user_create.function.XCClient")
def test_create_user_already_exists_no_changes(mock_xc_client_class, mock_get_params):
    """User already exists with same settings, no update needed."""
    from user_create.function import handler
    from shared.errors import ResourceExistsError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_user.side_effect = ResourceExistsError("User already exists")
    mock_client.get_user.return_value = {
        "email": "test@example.com",
        "first_name": "Test",
        "last_name": "User",
        "group_names": ["lab-users"],
        "namespace_roles": [{"namespace": "default", "role": "ves-io-monitor-role"}]
    }
    mock_xc_client_class.return_value = mock_client

    class MockContext:
        function_name = "user_create"

    event = {
        "ssm_base_path": "/tenantOps/test",
        "first_name": "Test",
        "last_name": "User",
        "email": "test@example.com",
        "group_names": ["lab-users"],
        "namespace_roles": [{"namespace": "default", "role": "ves-io-monitor-role"}]
    }

    result = handler(event, MockContext())

    assert result["statusCode"] == 200
    assert "No update needed" in result["body"]
    mock_client.create_user.assert_called_once()
    mock_client.get_user.assert_called_once_with("test@example.com")
    mock_client.update_user.assert_not_called()


@patch("user_create.function.get_ssm_parameters")
@patch("user_create.function.XCClient")
def test_create_user_exists_but_not_found_in_list(mock_xc_client_class, mock_get_params):
    """User reported as existing but not found when listing - should raise PermanentError."""
    from user_create.function import handler
    from shared.errors import ResourceExistsError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_user.side_effect = ResourceExistsError("User already exists")
    mock_client.get_user.return_value = None  # User not found
    mock_xc_client_class.return_value = mock_client

    class MockContext:
        function_name = "user_create"

    event = {
        "ssm_base_path": "/tenantOps/test",
        "first_name": "Test",
        "last_name": "User",
        "email": "test@example.com",
        "group_names": [],
        "namespace_roles": []
    }

    result = handler(event, MockContext())

    # PermanentError is caught by lambda_handler decorator and returns 400
    assert result["statusCode"] == 400
    assert "not found in the user list" in result["body"]


@patch("user_create.function.get_ssm_parameters")
@patch("user_create.function.XCClient")
def test_create_user_missing_required_fields(mock_xc_client_class, mock_get_params):
    """Handle missing required fields in payload."""
    from user_create.function import handler

    class MockContext:
        function_name = "user_create"

    # Missing email
    event = {
        "ssm_base_path": "/tenantOps/test",
        "first_name": "Test",
        "last_name": "User"
    }

    result = handler(event, MockContext())

    assert result["statusCode"] == 400
    assert "Missing required fields" in result["body"]
    assert "email" in result["body"]


@patch("user_create.function.get_ssm_parameters")
@patch("user_create.function.XCClient")
def test_create_user_api_error(mock_xc_client_class, mock_get_params):
    """Handle transient API errors from XCClient."""
    from user_create.function import handler
    from shared.errors import TransientError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_user.side_effect = TransientError("API error 503: Service Unavailable")
    mock_xc_client_class.return_value = mock_client

    class MockContext:
        function_name = "user_create"

    event = {
        "ssm_base_path": "/tenantOps/test",
        "first_name": "Test",
        "last_name": "User",
        "email": "test@example.com",
        "group_names": [],
        "namespace_roles": []
    }

    # TransientError should be re-raised by the decorator
    with pytest.raises(TransientError):
        handler(event, MockContext())


@patch("user_create.function.get_ssm_parameters")
@patch("user_create.function.XCClient")
def test_create_user_defaults_for_optional_fields(mock_xc_client_class, mock_get_params):
    """Test that optional fields default to empty lists."""
    from user_create.function import handler

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_xc_client_class.return_value = mock_client

    class MockContext:
        function_name = "user_create"

    # No group_names or namespace_roles provided
    event = {
        "ssm_base_path": "/tenantOps/test",
        "first_name": "Test",
        "last_name": "User",
        "email": "test@example.com"
    }

    result = handler(event, MockContext())

    assert result["statusCode"] == 200
    mock_client.create_user.assert_called_once_with(
        "test@example.com",
        "Test",
        "User",
        [],  # default empty group_names
        []   # default empty namespace_roles
    )


def test_merge_namespace_roles():
    """Test merging namespace roles without duplicates."""
    from user_create.function import merge_namespace_roles

    existing = [
        {"namespace": "system", "role": "admin"},
        {"namespace": "default", "role": "viewer"}
    ]
    new = [
        {"namespace": "default", "role": "viewer"},  # duplicate
        {"namespace": "prod", "role": "editor"}      # new
    ]

    merged = merge_namespace_roles(existing, new)

    assert len(merged) == 3
    # Convert to sets of frozensets for comparison
    merged_set = {frozenset(role.items()) for role in merged}
    expected_set = {
        frozenset({"namespace": "system", "role": "admin"}.items()),
        frozenset({"namespace": "default", "role": "viewer"}.items()),
        frozenset({"namespace": "prod", "role": "editor"}.items())
    }
    assert merged_set == expected_set


def test_merge_namespace_roles_empty_inputs():
    """Test merging with empty lists."""
    from user_create.function import merge_namespace_roles

    # Both empty
    assert merge_namespace_roles([], []) == []

    # Existing empty
    new = [{"namespace": "default", "role": "viewer"}]
    merged = merge_namespace_roles([], new)
    assert len(merged) == 1

    # New empty
    existing = [{"namespace": "system", "role": "admin"}]
    merged = merge_namespace_roles(existing, [])
    assert len(merged) == 1


@patch("user_create.function.StateManager")
@patch("user_create.function.get_ssm_parameters")
@patch("user_create.function.XCClient")
def test_state_updates_on_success(mock_xc_client_class, mock_get_params, mock_state_manager_cls):
    """User creation updates state on start and completion."""
    from user_create.function import handler

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "test-token"
    }
    mock_client = MagicMock()
    mock_xc_client_class.return_value = mock_client

    mock_state_manager = MagicMock()
    mock_state_manager_cls.return_value = mock_state_manager

    class MockContext:
        function_name = "user_create"

    event = {
        "ssm_base_path": "/test",
        "first_name": "Test",
        "last_name": "User",
        "email": "user@test.com",
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


@patch("user_create.function.StateManager")
@patch("user_create.function.get_ssm_parameters")
def test_state_updates_on_failure(mock_get_params, mock_state_manager_cls):
    """User creation marks step failed on exception."""
    from user_create.function import handler
    from shared.errors import TransientError

    mock_get_params.side_effect = TransientError("SSM unavailable")

    mock_state_manager = MagicMock()
    mock_state_manager_cls.return_value = mock_state_manager

    class MockContext:
        function_name = "user_create"

    event = {
        "ssm_base_path": "/test",
        "first_name": "Test",
        "last_name": "User",
        "email": "user@test.com",
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

    with pytest.raises(TransientError):
        handler(event, MockContext())

    mock_state_manager.mark_step_started.assert_called_once()
    mock_state_manager.mark_step_failed.assert_called_once()
