"""Create HTTP load balancer in F5 XC tenant."""

from typing import Any, Dict

from shared.decorators import lambda_handler
from shared.errors import ResourceExistsError
from shared.logging import StructuredLogger
from shared.ssm import get_ssm_parameters
from shared.xc_client import XCClient


def create_lb(event: Dict[str, Any], logger: StructuredLogger) -> Dict[str, Any]:
    """Create an HTTP load balancer in F5 XC.

    Args:
        event: Contains ssm_base_path, metadata, and spec.
        logger: Structured logger.

    Returns:
        Dict with status and resource name.
    """
    step = logger.with_step("create_http_lb")

    ssm_base_path = event["ssm_base_path"]
    metadata = event["metadata"]
    spec = event["spec"]
    name = metadata["name"]
    namespace = metadata["namespace"]

    # Get XC credentials
    params = get_ssm_parameters(
        [f"{ssm_base_path}/tenant-url", f"{ssm_base_path}/token-value"]
    )

    # Create XC client (has built-in retry logic)
    client = XCClient(
        tenant_url=params["tenant-url"],
        api_token=params["token-value"],
        validate=False  # Skip validation for performance
    )

    # Build payload
    payload = {
        "metadata": metadata,
        "spec": spec
    }

    step.info("Creating HTTP load balancer", name=name, namespace=namespace, domains=spec.get("domains"))

    try:
        client.create_http_loadbalancer(namespace, payload)
        step.info("HTTP load balancer created", name=name)
        return {"status": "success", "name": name, "created": True}
    except ResourceExistsError:
        step.info("HTTP load balancer already exists", name=name)
        return {"status": "success", "name": name, "already_existed": True}


@lambda_handler
def handler(event: Dict[str, Any], context, logger: StructuredLogger) -> Dict[str, Any]:
    """Lambda entry point."""
    return create_lb(event, logger)


if __name__ == "__main__":
    class MockContext:
        function_name = "http_lb_create"

    test_event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-lb", "namespace": "test"},
        "spec": {"domains": ["test.example.com"]}
    }
    handler(test_event, MockContext())
