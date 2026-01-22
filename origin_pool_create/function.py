"""Create origin pool in F5 XC tenant."""

from typing import Any, Dict

from shared.decorators import lambda_handler, with_retry
from shared.errors import TransientError
from shared.logging import StructuredLogger


# Lazy imports for testability
origin_pool = None
session = None


def _get_xc_client():
    """Lazy load f5xc_tops_py_client modules."""
    global origin_pool, session
    if origin_pool is None:
        from f5xc_tops_py_client import origin_pool as op, session as sess
        origin_pool = op
        session = sess
    return origin_pool, session


def _get_parameters(parameters: list, region_name: str = "us-east-1") -> dict:
    """Fetch parameters from AWS Parameter Store."""
    import boto3
    try:
        aws = boto3.session.Session()
        ssm = aws.client("ssm", region_name=region_name)
        response = ssm.get_parameters(Names=parameters, WithDecryption=True)
        return {param["Name"].split("/")[-1]: param["Value"] for param in response["Parameters"]}
    except Exception as e:
        raise TransientError(f"Failed to fetch parameters: {e}") from e


@with_retry(max_attempts=3)
def _create_origin_pool_with_retry(api, payload: dict, namespace: str) -> None:
    """Call XC API to create origin pool, with retry on transient failures."""
    try:
        api.create(payload=payload, namespace=namespace)
    except Exception as e:
        error_msg = str(e).lower()
        # Don't retry "already exists" errors - they're not transient
        already_exists_patterns = ["already exist", "already exists", "duplicate", "conflict"]
        if any(pattern in error_msg for pattern in already_exists_patterns):
            raise
        # Check for HTTP 409 Conflict
        if hasattr(e, 'status_code') and e.status_code == 409:
            raise
        if hasattr(e, 'response') and hasattr(e.response, 'status_code') and e.response.status_code == 409:
            raise
        raise TransientError(f"Failed to create origin pool: {e}") from e


def create_pool(event: Dict[str, Any], logger: StructuredLogger) -> Dict[str, Any]:
    """Create an origin pool in F5 XC.

    Args:
        event: Contains ssm_base_path, metadata, and spec.
        logger: Structured logger.

    Returns:
        Dict with status and resource name.
    """
    step = logger.with_step("create_origin_pool")

    ssm_base_path = event["ssm_base_path"]
    metadata = event["metadata"]
    spec = event["spec"]
    name = metadata["name"]
    namespace = metadata["namespace"]

    # Get XC credentials
    import boto3
    region = boto3.session.Session().region_name or "us-east-1"
    params = _get_parameters(
        [f"{ssm_base_path}/tenant-url", f"{ssm_base_path}/token-value"],
        region_name=region
    )

    # Get XC client
    op_module, sess_module = _get_xc_client()
    auth = sess_module(tenant_url=params["tenant-url"], api_token=params["token-value"])
    api = op_module(auth)

    # Build payload
    payload = {
        "metadata": metadata,
        "spec": spec
    }

    step.info("Creating origin pool", name=name, namespace=namespace)

    try:
        _create_origin_pool_with_retry(api, payload, namespace)
        step.info("Origin pool created", name=name)
        return {"status": "success", "name": name, "created": True}
    except Exception as e:
        error_msg = str(e).lower()

        # Check for HTTP 409 Conflict status code
        is_conflict_status = False
        if hasattr(e, 'status_code'):
            is_conflict_status = e.status_code == 409
        elif hasattr(e, 'response') and hasattr(e.response, 'status_code'):
            is_conflict_status = e.response.status_code == 409

        # Check for common "already exists" error message patterns
        already_exists_patterns = [
            "already exist",
            "already exists",
            "duplicate",
            "conflict",
        ]
        is_already_exists_error = any(pattern in error_msg for pattern in already_exists_patterns)

        if is_conflict_status or is_already_exists_error:
            step.info("Origin pool already exists", name=name)
            return {"status": "success", "name": name, "already_existed": True}
        step.error("Failed to create origin pool", error=str(e))
        raise


@lambda_handler
def handler(event: Dict[str, Any], context, logger: StructuredLogger) -> Dict[str, Any]:
    """Lambda entry point."""
    return create_pool(event, logger)


if __name__ == "__main__":
    class MockContext:
        function_name = "origin_pool_create"

    test_event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-pool", "namespace": "test"},
        "spec": {"port": 80}
    }
    handler(test_event, MockContext())
