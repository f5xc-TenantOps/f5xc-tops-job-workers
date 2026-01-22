"""Create HTTP load balancer in F5 XC tenant."""

from typing import Any, Dict

from f5xc_tops_py_client import http_loadbalancer, session
from shared.decorators import lambda_handler, with_retry
from shared.errors import TransientError, is_already_exists_error
from shared.logging import StructuredLogger
from shared.ssm import get_ssm_parameters


@with_retry(max_attempts=3)
def _create_http_lb_with_retry(api, payload: dict, namespace: str) -> None:
    """Call XC API to create HTTP load balancer, with retry on transient failures."""
    try:
        api.create(payload=payload, namespace=namespace)
    except Exception as e:
        # Don't retry "already exists" errors - they're not transient
        if is_already_exists_error(e):
            raise
        raise TransientError(f"Failed to create HTTP load balancer: {e}") from e


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

    # Get XC client
    auth = session(tenant_url=params["tenant-url"], api_token=params["token-value"])
    api = http_loadbalancer(auth)

    # Build payload
    payload = {
        "metadata": metadata,
        "spec": spec
    }

    step.info("Creating HTTP load balancer", name=name, namespace=namespace, domains=spec.get("domains"))

    try:
        _create_http_lb_with_retry(api, payload, namespace)
        step.info("HTTP load balancer created", name=name)
        return {"status": "success", "name": name, "created": True}
    except Exception as e:
        if is_already_exists_error(e):
            step.info("HTTP load balancer already exists", name=name)
            return {"status": "success", "name": name, "already_existed": True}
        step.error("Failed to create HTTP load balancer", error=str(e))
        raise


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
