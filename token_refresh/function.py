"""
This module refreshes an F5 XC tenant token.
"""
import os
import boto3
from f5xc_tops_py_client import session, apicred, svccred

from shared.logging import StructuredLogger
from shared.errors import PermanentError, TransientError
from shared.decorators import lambda_handler, with_retry


@with_retry(max_attempts=3, backoff_base=2)
def get_parameters(parameters: list, region_name: str = "us-west-2") -> dict:
    """
    Fetch parameters from AWS Parameter Store.
    """
    aws = boto3.session.Session()
    ssm = aws.client("ssm", region_name=region_name)
    response = ssm.get_parameters(Names=parameters, WithDecryption=True)
    return {param["Name"].split("/")[-1]: param["Value"] for param in response["Parameters"]}


@with_retry(max_attempts=3, backoff_base=2)
def refresh_token(_api, token_name: str, expiration_days: int = 7):
    """
    Refresh the F5 XC tenant token.
    """
    try:
        payload = _api.renew_payload(name=token_name, expiration_days=expiration_days)
        _api.renew(payload)
    except (KeyError, ValueError) as e:
        raise PermanentError(f"Failed to renew token: {e}") from e


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

    region = boto3.session.Session().region_name or "us-west-2"
    params = get_parameters(
        [
            f"{base_path}/tenant-url",
            f"{base_path}/token-value",
            f"{base_path}/token-name",
            f"{base_path}/token-type",
        ],
        region_name=region,
    )

    cred_type = params.get("token-type", "").lower()
    if cred_type not in {"apicred", "svccred"}:
        raise PermanentError(f"Invalid token-type: {cred_type}. Must be 'apicred' or 'svccred'.")

    step_logger = logger.with_step("auth")
    step_logger.info("Creating API session", cred_type=cred_type)

    if cred_type == "svccred":
        _api = svccred(session(tenant_url=params["tenant-url"], api_token=params["token-value"]))
    else:
        _api = apicred(session(tenant_url=params["tenant-url"], api_token=params["token-value"]))

    step_logger = logger.with_step("refresh")
    step_logger.info("Refreshing token", token_name=params["token-name"])

    refresh_token(_api, params["token-name"], expiration_days=7)

    step_logger.info("Token refreshed successfully",
                     cred_type=cred_type,
                     token_name=params["token-name"])

    return f"{cred_type} token {params['token-name']} refreshed successfully."


# Keep lambda_handler name for AWS Lambda
lambda_handler = handler


if __name__ == "__main__":
    # For local testing
    class MockContext:
        function_name = "token_refresh"
    handler({}, MockContext())
