"""
Remove a namespace in an F5 XC tenant.
"""
import boto3
from f5xc_tops_py_client import session, ns

from shared.logging import StructuredLogger
from shared.errors import PermanentError, TransientError, RateLimitError
from shared.decorators import lambda_handler, with_retry


def get_parameters(parameters: list, region_name: str = "us-east-1") -> dict:
    """
    Fetch parameters from AWS Parameter Store.
    """
    try:
        aws = boto3.session.Session()
        ssm = aws.client("ssm", region_name=region_name)
        response = ssm.get_parameters(Names=parameters, WithDecryption=True)
        return {param["Name"].split("/")[-1]: param["Value"] for param in response["Parameters"]}
    except Exception as e:
        raise TransientError(f"Failed to fetch parameters: {e}") from e


def validate_payload(payload: dict):
    """
    Validate the payload for required fields.
    """
    required_fields = ["ssm_base_path", "namespace_name"]
    missing_fields = [field for field in required_fields if field not in payload]

    if missing_fields:
        raise PermanentError(f"Missing required fields in payload: {', '.join(missing_fields)}")


def classify_xc_error(e: Exception, operation: str):
    """
    Classify XC API errors into appropriate error types.
    """
    error_str = str(e).lower()

    # Check for rate limiting
    if "429" in str(e) or "rate limit" in error_str:
        raise RateLimitError(f"{operation} rate limited: {e}") from e

    # Check for server errors (5xx)
    if any(code in str(e) for code in ["500", "502", "503", "504"]):
        raise TransientError(f"{operation} server error: {e}") from e

    # Check for client errors (4xx)
    if any(code in str(e) for code in ["400", "401", "403", "404"]):
        raise PermanentError(f"{operation} client error: {e}") from e

    # Default to transient for unknown errors
    raise TransientError(f"{operation} failed: {e}") from e


@with_retry(max_attempts=3, backoff_base=2)
def remove_namespace_from_tenant(_api, namespace_name: str, logger: StructuredLogger) -> str:
    """
    Remove a namespace from the tenant. Idempotent - checks if exists first.
    """
    step_logger = logger.with_step("remove_namespace")

    # Check if namespace exists
    try:
        existing = _api.get(name=namespace_name)
        if not existing:
            step_logger.info("Namespace does not exist", namespace=namespace_name)
            return f"Namespace '{namespace_name}' does not exist (already removed)."
    except Exception:
        # If we can't check, try to delete anyway
        step_logger.info("Could not check namespace existence, proceeding with delete", namespace=namespace_name)

    try:
        step_logger.info("Removing namespace", namespace=namespace_name)
        payload = _api.delete_payload(name=namespace_name)
        _api.delete(payload=payload, name=namespace_name)
        step_logger.info("Namespace removed", namespace=namespace_name)
        return f"Namespace '{namespace_name}' removed successfully."
    except Exception as e:
        # Check if it's a 404 (already deleted)
        if "404" in str(e) or "not found" in str(e).lower():
            step_logger.info("Namespace already removed", namespace=namespace_name)
            return f"Namespace '{namespace_name}' does not exist (already removed)."
        step_logger.error("Failed to remove namespace", namespace=namespace_name, error=str(e))
        classify_xc_error(e, "remove_namespace")


@lambda_handler
def handler(event: dict, context, logger: StructuredLogger):
    """
    Main handler to process the payload and remove the namespace.
    """
    validate_payload(event)

    ssm_base_path = event["ssm_base_path"]
    namespace_name = event["namespace_name"]

    # Fetch parameters
    fetch_logger = logger.with_step("fetch_parameters")
    fetch_logger.info("Fetching SSM parameters", ssm_base_path=ssm_base_path)

    region = boto3.session.Session().region_name
    params = get_parameters(
        [
            f"{ssm_base_path}/tenant-url",
            f"{ssm_base_path}/token-value"
        ],
        region_name=region,
    )
    fetch_logger.info("Parameters fetched successfully")

    # Initialize XC client
    auth = session(tenant_url=params["tenant-url"], api_token=params["token-value"])
    _api = ns(auth)

    # Remove namespace
    result = remove_namespace_from_tenant(_api, namespace_name, logger)

    return result


# Keep lambda_handler as the entry point for AWS Lambda
lambda_handler_entry = handler


if __name__ == "__main__":
    # Simulated direct payload for local testing
    test_payload_remove_ns = {
        "ssm_base_path": "/tenantOps/app-lab",
        "namespace_name": "snarky-petname"
    }

    # Create a mock context for local testing
    class MockContext:
        function_name = "ns_remove"

    handler(test_payload_remove_ns, MockContext())
