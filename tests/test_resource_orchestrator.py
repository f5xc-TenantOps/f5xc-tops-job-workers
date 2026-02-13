import os
import json
import pytest
from unittest.mock import MagicMock, patch

from shared.errors import PermanentError, TransientError


def test_orchestrator_builds_execution_levels():
    """Orchestrator groups resources by dependency level."""
    from resource_orchestrator.function import build_execution_plan
    from shared.logging import StructuredLogger

    logger = StructuredLogger("test", "test-correlation-id")
    resources = [
        {"type": "origin_pool", "depends_on": [], "metadata": {"name": "pool-a", "namespace": "test"}, "spec": {}},
        {"type": "waf_policy", "depends_on": [], "metadata": {"name": "waf-a", "namespace": "test"}, "spec": {}},
        {"type": "http_lb", "depends_on": ["pool-a", "waf-a"], "metadata": {"name": "lb-a", "namespace": "test"}, "spec": {}},
    ]

    levels = build_execution_plan(resources, logger)
    assert len(levels) == 2
    assert len(levels[0]) == 2  # pool and waf in parallel
    assert len(levels[1]) == 1  # lb after


@patch("resource_orchestrator.function.LAMBDA_SUFFIX", "-v2")
@patch("resource_orchestrator.function._get_lambda_client")
def test_orchestrator_invokes_resource_lambdas(mock_get_client):
    """Orchestrator invokes correct lambda for each resource type."""
    from resource_orchestrator.function import execute_resource
    from shared.logging import StructuredLogger
    import json

    mock_lambda = MagicMock()
    mock_get_client.return_value = mock_lambda
    mock_lambda.invoke.return_value = {
        "Payload": MagicMock(read=lambda: json.dumps({"statusCode": 200, "body": {"status": "success"}}).encode())
    }

    logger = StructuredLogger("test", "test-correlation-id")
    resource = {
        "type": "origin_pool",
        "metadata": {"name": "test-pool", "namespace": "test"},
        "spec": {"port": 80}
    }

    result = execute_resource(resource, "/tenantOps/test", logger)

    mock_lambda.invoke.assert_called_once()
    call_args = mock_lambda.invoke.call_args
    assert call_args.kwargs["FunctionName"] == "tops-origin-pool-create-v2"


def test_orchestrator_empty_resources():
    """Orchestrator handles empty resources list."""
    from resource_orchestrator.function import build_execution_plan
    from shared.logging import StructuredLogger

    logger = StructuredLogger("test", "test-correlation-id")
    levels = build_execution_plan([], logger)
    assert levels == []


_RESOURCE = {
    "type": "origin_pool",
    "metadata": {"name": "test-pool", "namespace": "test"},
    "spec": {"port": 80},
}


@patch("resource_orchestrator.function._get_lambda_client")
def test_lambda_crash_extracts_error_and_raises_transient(mock_get_client):
    """Lambda crash with FunctionError extracts errorMessage/errorType."""
    from resource_orchestrator.function import execute_resource
    from shared.logging import StructuredLogger

    mock_lambda = MagicMock()
    mock_get_client.return_value = mock_lambda
    mock_lambda.invoke.return_value = {
        "FunctionError": "Unhandled",
        "Payload": MagicMock(read=lambda: json.dumps({
            "errorMessage": "name 'tenant_url' is not defined",
            "errorType": "TransientError",
        }).encode()),
    }

    logger = StructuredLogger("test", "test-id")
    with pytest.raises(TransientError, match="TransientError"):
        execute_resource(_RESOURCE, "/tenantOps/test", logger)


@patch("resource_orchestrator.function._get_lambda_client")
def test_lambda_crash_permanent_error_type(mock_get_client):
    """Lambda crash with non-transient error type raises PermanentError."""
    from resource_orchestrator.function import execute_resource
    from shared.logging import StructuredLogger

    mock_lambda = MagicMock()
    mock_get_client.return_value = mock_lambda
    mock_lambda.invoke.return_value = {
        "FunctionError": "Unhandled",
        "Payload": MagicMock(read=lambda: json.dumps({
            "errorMessage": "'tenant-url'",
            "errorType": "KeyError",
        }).encode()),
    }

    logger = StructuredLogger("test", "test-id")
    with pytest.raises(PermanentError, match="KeyError"):
        execute_resource(_RESOURCE, "/tenantOps/test", logger)


@patch("resource_orchestrator.function._get_lambda_client")
def test_status_400_raises_permanent_error(mock_get_client):
    """statusCode 400 from resource lambda raises PermanentError."""
    from resource_orchestrator.function import execute_resource
    from shared.logging import StructuredLogger

    mock_lambda = MagicMock()
    mock_get_client.return_value = mock_lambda
    mock_lambda.invoke.return_value = {
        "Payload": MagicMock(read=lambda: json.dumps({
            "statusCode": 400,
            "body": "Invalid configuration",
        }).encode()),
    }

    logger = StructuredLogger("test", "test-id")
    with pytest.raises(PermanentError, match="Invalid configuration"):
        execute_resource(_RESOURCE, "/tenantOps/test", logger)


@patch("resource_orchestrator.function._get_lambda_client")
def test_no_double_wrapping_of_permanent_error(mock_get_client):
    """PermanentError raised inside execute_resource is not re-wrapped as TransientError."""
    from resource_orchestrator.function import execute_resource
    from shared.logging import StructuredLogger

    mock_lambda = MagicMock()
    mock_get_client.return_value = mock_lambda
    mock_lambda.invoke.return_value = {
        "FunctionError": "Unhandled",
        "Payload": MagicMock(read=lambda: json.dumps({
            "errorMessage": "bad config",
            "errorType": "PermanentError",
        }).encode()),
    }

    logger = StructuredLogger("test", "test-id")
    # PermanentError is not in _TRANSIENT_ERROR_TYPES, so should raise PermanentError
    with pytest.raises(PermanentError):
        execute_resource(_RESOURCE, "/tenantOps/test", logger)
