"""
Remove a user from an F5 XC tenant.
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
    required_fields = ["ssm_base_path", "email"]
    missing_fields = [field for field in required_fields if field not in payload]

    if missing_fields:
        raise PermanentError(f"Missing required fields in payload: {', '.join(missing_fields)}")


@lambda_handler
def handler(event: dict, context, logger: StructuredLogger):
    """
    Main handler to process the payload and remove the user.
    """
    validate_payload(event)

    ssm_base_path = event["ssm_base_path"]
    email = event["email"]

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

    # Remove user
    step_logger = logger.with_step("remove_user")
    step_logger.info("Removing user from tenant", email=email)

    try:
        client.delete_user(email)
        step_logger.info("User removed", email=email)
        return f"User with email '{email}' removed successfully."
    except ResourceNotFoundError:
        step_logger.info("User already removed", email=email)
        return f"User with email '{email}' not found (already removed)."


# Keep lambda_handler as the entry point for AWS Lambda
lambda_handler_entry = handler


if __name__ == "__main__":
    # Simulated direct payload for local testing
    test_payload = {
        "ssm_base_path": "/tenantOps/app-lab",
        "email": "tops@f5demos.com"
    }

    class MockContext:
        function_name = "user_remove"

    handler(test_payload, MockContext())
