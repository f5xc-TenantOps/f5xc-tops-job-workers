"""Create WAF policy (app_firewall) in F5 XC tenant."""

from typing import Any, Dict

from f5xc_tops_py_client import app_firewall, session
from shared.decorators import lambda_handler, with_retry
from shared.errors import TransientError, is_already_exists_error
from shared.logging import StructuredLogger
from shared.ssm import get_ssm_parameters


@with_retry(max_attempts=3)
def _create_waf_with_retry(api, payload: dict, namespace: str) -> None:
    """Call XC API to create WAF policy, with retry on transient failures."""
    try:
        api.create(payload=payload, namespace=namespace)
    except Exception as e:
        # Don't retry "already exists" errors - they're not transient
        if is_already_exists_error(e):
            raise
        raise TransientError(f"Failed to create WAF policy: {e}") from e


def create_waf(event: Dict[str, Any], logger: StructuredLogger) -> Dict[str, Any]:
    """Create a WAF policy in F5 XC.

    Args:
        event: Contains ssm_base_path, metadata, and spec.
        logger: Structured logger.

    Returns:
        Dict with status and resource name.
    """
    step = logger.with_step("create_waf_policy")

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
    api = app_firewall(auth)

    # Build payload
    payload = {
        "metadata": metadata,
        "spec": spec
    }

    step.info("Creating WAF policy", name=name, namespace=namespace)

    try:
        _create_waf_with_retry(api, payload, namespace)
        step.info("WAF policy created", name=name)
        return {"status": "success", "name": name, "created": True}
    except Exception as e:
        if is_already_exists_error(e):
            step.info("WAF policy already exists", name=name)
            return {"status": "success", "name": name, "already_existed": True}
        step.error("Failed to create WAF policy", error=str(e))
        raise


@lambda_handler
def handler(event: Dict[str, Any], context, logger: StructuredLogger) -> Dict[str, Any]:
    """Lambda entry point."""
    return create_waf(event, logger)


if __name__ == "__main__":
    class MockContext:
        function_name = "waf_policy_create"

    test_event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-waf", "namespace": "test"},
        "spec": {"mode": "BLOCKING"}
    }
    handler(test_event, MockContext())
