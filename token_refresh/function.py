"""
This module refreshes an F5 XC tenant token.
"""
import os

from shared.decorators import lambda_handler
from shared.logging import StructuredLogger
from shared.ssm import get_ssm_parameters
from shared.xc_client import XCClient
from shared.errors import PermanentError


@lambda_handler
def handler(event, context, logger: StructuredLogger):
    """
    AWS Lambda entry point for token refresh.
    """
    step_logger = logger.with_step("init")

    base_path = os.environ.get("SSM_BASE_PATH")
    if not base_path:
        raise PermanentError("Environment variable SSM_BASE_PATH is not set.")

    step_logger.info("Fetching parameters from SSM", base_path=base_path)

    params = get_ssm_parameters([
        f"{base_path}/tenant-url",
        f"{base_path}/token-value",
        f"{base_path}/token-name",
        f"{base_path}/token-type",
    ])

    cred_type = params.get("token-type", "").lower()
    if cred_type not in {"apicred", "svccred"}:
        raise PermanentError(f"Invalid token-type: {cred_type}. Must be 'apicred' or 'svccred'.")

    step_logger = logger.with_step("auth")
    step_logger.info("Creating XC client", cred_type=cred_type)

    client = XCClient(
        tenant_url=params["tenant-url"],
        api_token=params["token-value"],
    )

    step_logger = logger.with_step("refresh")
    step_logger.info("Refreshing token", token_name=params["token-name"])

    token_name = params["token-name"]
    expiration_days = 7

    if cred_type == "svccred":
        client.renew_service_credential(token_name, expiration_days)
    else:
        client.renew_api_credential(token_name, expiration_days)

    step_logger.info("Token refreshed successfully",
                     cred_type=cred_type,
                     token_name=token_name)

    return f"{cred_type} token {token_name} refreshed successfully."


# Keep lambda_handler name for AWS Lambda
lambda_handler = handler


if __name__ == "__main__":
    # For local testing
    class MockContext:
        function_name = "token_refresh"
    handler({}, MockContext())
