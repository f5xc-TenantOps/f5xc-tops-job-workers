import os
import pytest
from unittest.mock import MagicMock, patch


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
