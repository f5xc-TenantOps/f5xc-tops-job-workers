"""
Create a namespace in an F5 XC tenant and verify its availability.
"""
import time
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
def create_namespace_in_tenant(_api, namespace_name: str, description: str, logger: StructuredLogger) -> str:
    """
    Create a namespace in the tenant. Idempotent - checks if exists first.
    """
    step_logger = logger.with_step("create_namespace")

    # Check if namespace already exists
    try:
        existing = _api.get(name=namespace_name)
        if existing:
            step_logger.info("Namespace already exists", namespace=namespace_name)
            return f"Namespace '{namespace_name}' already exists."
    except Exception:
        # Namespace doesn't exist, proceed with creation
        pass

    try:
        step_logger.info("Creating namespace", namespace=namespace_name)
        payload = _api.create_payload(name=namespace_name, description=description)
        _api.create(payload)
        step_logger.info("Namespace created", namespace=namespace_name)
        return f"Namespace '{namespace_name}' created successfully."
    except Exception as e:
        step_logger.error("Failed to create namespace", namespace=namespace_name, error=str(e))
        classify_xc_error(e, "create_namespace")


@with_retry(max_attempts=3, backoff_base=2)
def wait_for_namespace(_api, namespace_name: str, logger: StructuredLogger, timeout: int = 20, interval: int = 5) -> str:
    """
    Wait for the namespace to be available.
    """
    step_logger = logger.with_step("wait_for_namespace")
    start_time = time.time()

    step_logger.info("Waiting for namespace", namespace=namespace_name, timeout=timeout)

    while time.time() - start_time < timeout:
        try:
            response = _api.get(name=namespace_name)
            if response:
                step_logger.info("Namespace available", namespace=namespace_name)
                return f"Namespace '{namespace_name}' is available."
        except Exception as e:
            step_logger.info("Namespace not ready yet", namespace=namespace_name, error=str(e))
            time.sleep(interval)

    raise TransientError(f"Namespace '{namespace_name}' was not available within {timeout} seconds.")


@lambda_handler
def handler(event: dict, context, logger: StructuredLogger):
    """
    Main handler to process the payload, create a namespace, and verify its availability.
    """
    validate_payload(event)

    ssm_base_path = event["ssm_base_path"]
    namespace_name = event["namespace_name"]
    description = event.get("description", "")

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

    # Create namespace
    create_result = create_namespace_in_tenant(_api, namespace_name, description, logger)

    # Wait for the namespace to be available
    wait_result = wait_for_namespace(_api, namespace_name, logger)

    return f"{create_result} | {wait_result}"


# Keep lambda_handler as the entry point for AWS Lambda
lambda_handler_entry = handler


if __name__ == "__main__":
    # Simulated direct payload for local testing
    test_payload_create_ns = {
        "ssm_base_path": "/tenantOps/app-lab",
        "namespace_name": "snarky-petname",
        "description": "testing namespace creation"
    }

    # Create a mock context for local testing
    class MockContext:
        function_name = "ns_create"

    handler(test_payload_create_ns, MockContext())
