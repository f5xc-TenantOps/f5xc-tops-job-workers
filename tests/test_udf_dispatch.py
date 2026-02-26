# tests/test_udf_dispatch.py
import json
import os

# Must be set before importing udf_dispatch.function (module-level boto3.client + env check)
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("DEPLOYMENT_STATE_TABLE", "tops-udf-lab-deployment-state-v2")
os.environ.setdefault("LAB_CONFIGURATION_TABLE", "tops-udf-lab-config-v2")

from unittest.mock import MagicMock, patch

import pytest

import udf_dispatch.function as udf_mod


@patch.object(udf_mod, "get_ssm_parameters")
@patch.object(udf_mod, "dynamodb")
def test_insert_includes_tenant_url(mock_dynamodb, mock_get_ssm):
    """When lab config + SSM resolve successfully, put_item includes tenant_url."""
    from shared.logging import StructuredLogger

    mock_dynamodb.get_item.return_value = {
        "Item": {
            "lab_id": {"S": "lab-123"},
            "ssm_base_path": {"S": "/tenantOps/test"},
        }
    }
    mock_dynamodb.put_item.return_value = {}
    mock_get_ssm.return_value = {"tenant-url": "https://tenant.example.com"}

    logger = StructuredLogger("test", "test-correlation-id")
    message = {
        "dep_id": "dep-001",
        "lab_id": "lab-123",
        "email": "user@test.com",
        "petname": "fuzzy-cat",
    }

    udf_mod.insert_into_dynamodb(message, logger)

    put_call = mock_dynamodb.put_item.call_args
    item = put_call.kwargs["Item"]
    assert "tenant_url" in item
    assert item["tenant_url"] == {"S": "https://tenant.example.com"}


@patch.object(udf_mod, "get_ssm_parameters")
@patch.object(udf_mod, "dynamodb")
def test_insert_without_tenant_url_on_ssm_failure(mock_dynamodb, mock_get_ssm):
    """When SSM raises, put_item still succeeds without tenant_url."""
    from shared.logging import StructuredLogger

    mock_dynamodb.get_item.return_value = {
        "Item": {
            "lab_id": {"S": "lab-123"},
            "ssm_base_path": {"S": "/tenantOps/test"},
        }
    }
    mock_dynamodb.put_item.return_value = {}
    mock_get_ssm.side_effect = Exception("SSM unavailable")

    logger = StructuredLogger("test", "test-correlation-id")
    message = {
        "dep_id": "dep-001",
        "lab_id": "lab-123",
        "email": "user@test.com",
        "petname": "fuzzy-cat",
    }

    udf_mod.insert_into_dynamodb(message, logger)

    put_call = mock_dynamodb.put_item.call_args
    item = put_call.kwargs["Item"]
    assert "tenant_url" not in item


@patch.object(udf_mod, "get_ssm_parameters")
@patch.object(udf_mod, "dynamodb")
def test_insert_without_tenant_url_on_missing_lab_config(mock_dynamodb, mock_get_ssm):
    """When lab config table returns no item, put_item still succeeds without tenant_url."""
    from shared.logging import StructuredLogger

    mock_dynamodb.get_item.return_value = {}  # No Item
    mock_dynamodb.put_item.return_value = {}

    logger = StructuredLogger("test", "test-correlation-id")
    message = {
        "dep_id": "dep-001",
        "lab_id": "lab-123",
        "email": "user@test.com",
        "petname": "fuzzy-cat",
    }

    udf_mod.insert_into_dynamodb(message, logger)

    put_call = mock_dynamodb.put_item.call_args
    item = put_call.kwargs["Item"]
    assert "tenant_url" not in item
    mock_get_ssm.assert_not_called()


@patch.object(udf_mod, "get_ssm_parameters")
@patch.object(udf_mod, "dynamodb")
def test_extend_ttl_does_not_fetch_tenant_url(mock_dynamodb, mock_get_ssm):
    """Heartbeat path (extend_ttl) skips the lab config/SSM lookup."""
    mock_dynamodb.get_item.return_value = {
        "Item": {
            "dep_id": {"S": "dep-001"},
            "lab_id": {"S": "lab-123"},
        }
    }
    mock_dynamodb.update_item.return_value = {}

    event = {
        "Records": [
            {
                "body": json.dumps({
                    "dep_id": "dep-001",
                    "lab_id": "lab-123",
                    "email": "user@test.com",
                    "petname": "fuzzy-cat",
                })
            }
        ]
    }

    class MockContext:
        function_name = "udf_dispatch"

    udf_mod.handler(event, MockContext())

    mock_get_ssm.assert_not_called()
    mock_dynamodb.update_item.assert_called_once()
