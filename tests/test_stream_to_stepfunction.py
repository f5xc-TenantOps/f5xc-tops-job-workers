# tests/test_stream_to_stepfunction.py
import pytest
from unittest.mock import MagicMock, patch
import json
import os


@patch("stream_to_stepfunction.function._get_sfn_client")
@patch("stream_to_stepfunction.function._get_dynamodb_client")
@patch.dict(os.environ, {"STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:test"})
def test_stream_triggers_stepfunction_on_insert(mock_get_ddb, mock_get_sfn):
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


@patch("stream_to_stepfunction.function._get_sfn_client")
@patch("stream_to_stepfunction.function._get_dynamodb_client")
def test_stream_ignores_remove_events(mock_get_ddb, mock_get_sfn):
    """REMOVE events are ignored."""
    from stream_to_stepfunction.function import process_record
    from shared.logging import StructuredLogger

    mock_sfn = MagicMock()
    mock_get_sfn.return_value = mock_sfn

    logger = StructuredLogger("test", "test-correlation-id")
    record = {
        "eventName": "REMOVE",
        "dynamodb": {"OldImage": {"dep_id": {"S": "dep-123"}}}
    }

    result = process_record(record, logger)

    assert result["triggered"] is False
    mock_sfn.start_execution.assert_not_called()


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


@patch("stream_to_stepfunction.function._get_sfn_client")
@patch("stream_to_stepfunction.function._get_dynamodb_client")
@patch.dict(os.environ, {"STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:test"})
def test_stream_uses_lab_id_as_job_id_when_not_found(mock_get_ddb, mock_get_sfn):
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
