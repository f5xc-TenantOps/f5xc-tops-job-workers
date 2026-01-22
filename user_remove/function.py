"""
Remove a user from an F5 XC tenant.
"""
import boto3
from f5xc_tops_py_client import session, user

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
    required_fields = ["ssm_base_path", "email"]
    missing_fields = [field for field in required_fields if field not in payload]

    if missing_fields:
        raise PermanentError(f"Missing required fields in payload: {', '.join(missing_fields)}")


@with_retry(max_attempts=3)
def remove_user_from_tenant(_api, email: str) -> str:
    """
    Remove a user from the tenant.
    """
    try:
        payload = _api.delete_payload(email=email)
        _api.delete(payload)
        return f"User with email '{email}' removed successfully."
    except Exception as e:
        error_msg = str(e)
        if "not found" in error_msg.lower() or "404" in error_msg:
            # User already removed, treat as success (idempotent)
            return f"User with email '{email}' not found (already removed)."
        if "401" in error_msg or "403" in error_msg:
            raise PermanentError(f"Authentication/authorization failed: {e}") from e
        if "429" in error_msg:
            raise RateLimitError(f"Rate limited: {e}") from e
        if "502" in error_msg or "503" in error_msg or "504" in error_msg:
            raise TransientError(f"Gateway error: {e}") from e
        raise TransientError(f"Failed to remove user: {e}") from e


@lambda_handler
def handler(event: dict, context, logger: StructuredLogger):
    """
    Main handler to process the payload and remove the user.
    """
    step_logger = logger.with_step("validate_payload")
    step_logger.info("Validating payload")
    validate_payload(event)

    ssm_base_path = event["ssm_base_path"]
    email = event["email"]

    step_logger = logger.with_step("fetch_parameters")
    step_logger.info("Fetching parameters from SSM", ssm_base_path=ssm_base_path)
    region = boto3.session.Session().region_name
    params = get_parameters(
        [
            f"{ssm_base_path}/tenant-url",
            f"{ssm_base_path}/token-value"
        ],
        region_name=region,
    )

    auth = session(tenant_url=params["tenant-url"], api_token=params["token-value"])
    _api = user(auth)

    step_logger = logger.with_step("remove_user")
    step_logger.info("Removing user from tenant", email=email)
    result_message = remove_user_from_tenant(_api=_api, email=email)
    step_logger.info("User removal completed", email=email, result=result_message)

    return result_message


# Keep backward compatibility
def lambda_handler_entry(event, context):
    """
    AWS Lambda entry point.
    """
    return handler(event, context)


if __name__ == "__main__":
    # Simulated direct payload for local testing
    test_payload = {
        "ssm_base_path": "/tenantOps/app-lab",
        "email": "tops@f5demos.com"
    }

    class MockContext:
        function_name = "user_remove"

    handler(test_payload, MockContext())
