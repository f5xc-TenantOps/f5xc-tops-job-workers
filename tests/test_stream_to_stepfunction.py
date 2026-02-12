# tests/test_stream_to_stepfunction.py
import pytest
from unittest.mock import MagicMock, patch
import json
import os


@patch("stream_to_stepfunction.function.StateManager")
@patch("stream_to_stepfunction.function._get_sfn_client")
@patch("stream_to_stepfunction.function._get_dynamodb_client")
@patch.dict(os.environ, {"STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:test"})
def test_stream_triggers_stepfunction_on_insert(mock_get_ddb, mock_get_sfn, mock_state_manager):
    """DynamoDB INSERT event triggers Step Function."""
    from stream_to_stepfunction.function import process_record
    from shared.logging import StructuredLogger

    mock_ddb = MagicMock()
    mock_ddb.get_item.return_value = {
        "Item": {"job_id": {"S": "api-lab"}}
    }
    mock_get_ddb.return_value = mock_ddb

    mock_sfn = MagicMock()
    mock_sfn.start_execution.return_value = {
        "executionArn": "arn:aws:states:us-east-1:123:execution:test"
    }
    mock_get_sfn.return_value = mock_sfn

    logger = StructuredLogger("test", "test-correlation-id")
    record = {
        "eventName": "INSERT",
        "dynamodb": {
            "NewImage": {
                "dep_id": {"S": "dep-123"},
                "lab_id": {"S": "lab-456"},
                "email": {"S": "user@test.com"},
                "petname": {"S": "fuzzy-cat"}
            }
        }
    }

    result = process_record(record, logger)

    assert result["triggered"] is True
    mock_sfn.start_execution.assert_called_once()
    mock_state_manager.return_value.update_state.assert_called_once()


def test_stream_ignores_non_insert_events():
    """Non-INSERT events are ignored."""
    from stream_to_stepfunction.function import process_record
    from shared.logging import StructuredLogger

    logger = StructuredLogger("test", "test-correlation-id")
    record = {
        "eventName": "MODIFY",
        "dynamodb": {"NewImage": {}}
    }

    result = process_record(record, logger)

    assert result["triggered"] is False


@patch("stream_to_stepfunction.function._check_existing_user_in_tenant", return_value=False)
@patch("stream_to_stepfunction.function._get_sfn_client")
@patch("stream_to_stepfunction.function._get_dynamodb_client")
@patch.dict(os.environ, {"CLEANUP_STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:cleanup"})
def test_remove_with_manifest_derives_flags_from_resources(mock_get_ddb, mock_get_sfn, mock_check_user):
    """REMOVE with manifest derives namespace_enabled/user_enabled from resources."""
    from stream_to_stepfunction.function import process_remove
    from shared.logging import StructuredLogger

    mock_ddb = MagicMock()
    mock_ddb.get_item.return_value = {
        "Item": {"lab_id": {"S": "lab-1"}, "ssm_base_path": {"S": "/ssm/path"}}
    }
    mock_get_ddb.return_value = mock_ddb

    mock_sfn = MagicMock()
    mock_sfn.start_execution.return_value = {
        "executionArn": "arn:aws:states:us-east-1:123:execution:cleanup"
    }
    mock_get_sfn.return_value = mock_sfn

    logger = StructuredLogger("test", "test-id")
    record = {
        "dynamodb": {
            "OldImage": {
                "dep_id": {"S": "dep-123"},
                "lab_id": {"S": "lab-1"},
                "email": {"S": "user@test.com"},
                "petname": {"S": "fuzzy-cat"},
                "tenant_url": {"S": "https://tenant.example.com"},
                "resources": {"M": {
                    "fuzzy-cat": {"M": {"type": {"S": "namespace"}}},
                    "user@test.com": {"M": {"type": {"S": "user"}}},
                    "fuzzy-cat-origin": {"M": {"type": {"S": "origin_pool"}}},
                }},
            }
        }
    }

    result = process_remove(record, logger)

    assert result["triggered"] is True
    sfn_input = json.loads(mock_sfn.start_execution.call_args.kwargs["input"])
    assert sfn_input["namespace_enabled"] is True
    assert sfn_input["user_enabled"] is True


@patch("stream_to_stepfunction.function._check_existing_user_in_tenant", return_value=False)
@patch("stream_to_stepfunction.function._get_sfn_client")
@patch("stream_to_stepfunction.function._get_dynamodb_client")
@patch.dict(os.environ, {"CLEANUP_STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:cleanup"})
def test_remove_manifest_without_user_disables_user_flag(mock_get_ddb, mock_get_sfn, mock_check_user):
    """When manifest has no user type, user_enabled is False."""
    from stream_to_stepfunction.function import process_remove
    from shared.logging import StructuredLogger

    mock_ddb = MagicMock()
    mock_ddb.get_item.return_value = {
        "Item": {"lab_id": {"S": "lab-1"}, "ssm_base_path": {"S": "/ssm/path"}}
    }
    mock_get_ddb.return_value = mock_ddb

    mock_sfn = MagicMock()
    mock_sfn.start_execution.return_value = {
        "executionArn": "arn:aws:states:us-east-1:123:execution:cleanup"
    }
    mock_get_sfn.return_value = mock_sfn

    logger = StructuredLogger("test", "test-id")
    record = {
        "dynamodb": {
            "OldImage": {
                "dep_id": {"S": "dep-123"},
                "lab_id": {"S": "lab-1"},
                "email": {"S": "user@test.com"},
                "petname": {"S": "fuzzy-cat"},
                "tenant_url": {"S": "https://tenant.example.com"},
                "resources": {"M": {
                    "fuzzy-cat": {"M": {"type": {"S": "namespace"}}},
                    "fuzzy-cat-origin": {"M": {"type": {"S": "origin_pool"}}},
                }},
            }
        }
    }

    result = process_remove(record, logger)

    sfn_input = json.loads(mock_sfn.start_execution.call_args.kwargs["input"])
    assert sfn_input["namespace_enabled"] is True
    assert sfn_input["user_enabled"] is False
    assert sfn_input["skip_user_removal"] is False
    # Should NOT have called _check_existing_user_in_tenant since user_enabled is False
    mock_check_user.assert_not_called()


@patch("stream_to_stepfunction.function._check_existing_user_in_tenant", return_value=False)
@patch("stream_to_stepfunction.function._get_sfn_client")
@patch("stream_to_stepfunction.function._get_dynamodb_client")
@patch.dict(os.environ, {"CLEANUP_STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:cleanup"})
def test_remove_without_manifest_falls_back_to_lab_config(mock_get_ddb, mock_get_sfn, mock_check_user):
    """Legacy: no manifest in OldImage falls back to lab config flags."""
    from stream_to_stepfunction.function import process_remove
    from shared.logging import StructuredLogger

    mock_ddb = MagicMock()
    mock_ddb.get_item.return_value = {
        "Item": {
            "lab_id": {"S": "lab-1"},
            "ssm_base_path": {"S": "/ssm/path"},
            "namespace": {"M": {"enabled": {"BOOL": True}}},
            "user": {"M": {"enabled": {"BOOL": False}}},
        }
    }
    mock_get_ddb.return_value = mock_ddb

    mock_sfn = MagicMock()
    mock_sfn.start_execution.return_value = {
        "executionArn": "arn:aws:states:us-east-1:123:execution:cleanup"
    }
    mock_get_sfn.return_value = mock_sfn

    logger = StructuredLogger("test", "test-id")
    record = {
        "dynamodb": {
            "OldImage": {
                "dep_id": {"S": "dep-123"},
                "lab_id": {"S": "lab-1"},
                "email": {"S": "user@test.com"},
                "petname": {"S": "fuzzy-cat"},
                "tenant_url": {"S": "https://tenant.example.com"},
                # No resources field — legacy deployment
            }
        }
    }

    result = process_remove(record, logger)

    sfn_input = json.loads(mock_sfn.start_execution.call_args.kwargs["input"])
    assert sfn_input["namespace_enabled"] is True
    assert sfn_input["user_enabled"] is False


@patch("stream_to_stepfunction.function._get_sfn_client")
@patch("stream_to_stepfunction.function._get_dynamodb_client")
def test_stream_handles_missing_fields(mock_get_ddb, mock_get_sfn):
    """Missing required fields returns triggered=False."""
    from stream_to_stepfunction.function import process_record
    from shared.logging import StructuredLogger

    mock_sfn = MagicMock()
    mock_get_sfn.return_value = mock_sfn

    logger = StructuredLogger("test", "test-correlation-id")
    record = {
        "eventName": "INSERT",
        "dynamodb": {
            "NewImage": {
                "dep_id": {"S": "dep-123"},
                # Missing lab_id, email, petname
            }
        }
    }

    result = process_record(record, logger)

    assert result["triggered"] is False
    mock_sfn.start_execution.assert_not_called()


@patch("stream_to_stepfunction.function.StateManager")
@patch("stream_to_stepfunction.function._get_sfn_client")
@patch("stream_to_stepfunction.function._get_dynamodb_client")
@patch.dict(os.environ, {"STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:test"})
def test_stream_uses_lab_id_as_job_id_when_not_found(mock_get_ddb, mock_get_sfn, mock_state_manager):
    """When lab config not found, use lab_id as job_id."""
    from stream_to_stepfunction.function import process_record
    from shared.logging import StructuredLogger

    mock_ddb = MagicMock()
    mock_ddb.get_item.return_value = {}  # No Item found
    mock_get_ddb.return_value = mock_ddb

    mock_sfn = MagicMock()
    mock_sfn.start_execution.return_value = {
        "executionArn": "arn:aws:states:us-east-1:123:execution:test"
    }
    mock_get_sfn.return_value = mock_sfn

    logger = StructuredLogger("test", "test-correlation-id")
    record = {
        "eventName": "INSERT",
        "dynamodb": {
            "NewImage": {
                "dep_id": {"S": "dep-123"},
                "lab_id": {"S": "my-lab-id"},
                "email": {"S": "user@test.com"},
                "petname": {"S": "fuzzy-cat"}
            }
        }
    }

    result = process_record(record, logger)

    assert result["triggered"] is True
    # Check that job_id in the input equals lab_id
    call_args = mock_sfn.start_execution.call_args
    sfn_input = json.loads(call_args.kwargs["input"])
    assert sfn_input["job_id"] == "my-lab-id"
    mock_state_manager.return_value.update_state.assert_called_once()
