"""
Remove a namespace in an F5 XC tenant.
"""
from shared.decorators import lambda_handler
from shared.errors import PermanentError, ResourceNotFoundError
from shared.logging import StructuredLogger
from shared.ssm import get_ssm_parameters
from shared.xc_client import XCClient


def validate_payload(payload: dict):
    """
    Validate the payload for required fields.
    """
    required_fields = ["ssm_base_path", "namespace_name"]
    missing_fields = [field for field in required_fields if field not in payload]

    if missing_fields:
        raise PermanentError(f"Missing required fields in payload: {', '.join(missing_fields)}")


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

    params = get_ssm_parameters([
        f"{ssm_base_path}/tenant-url",
        f"{ssm_base_path}/token-value"
    ])
    fetch_logger.info("Parameters fetched successfully")

    # Initialize XC client
    client = XCClient(
        tenant_url=params["tenant-url"],
        api_token=params["token-value"],
        validate=False
    )

    # Remove namespace
    step_logger = logger.with_step("remove_namespace")
    step_logger.info("Removing namespace", namespace=namespace_name)

    try:
        client.delete_namespace(namespace_name)
        step_logger.info("Namespace removed", namespace=namespace_name)
        return f"Namespace '{namespace_name}' removed successfully."
    except ResourceNotFoundError:
        step_logger.info("Namespace already removed", namespace=namespace_name)
        return f"Namespace '{namespace_name}' does not exist (already removed)."


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
