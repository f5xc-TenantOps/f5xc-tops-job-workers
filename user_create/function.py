"""
Create or update a user in an F5 XC tenant.
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
    required_fields = ["ssm_base_path", "first_name", "last_name", "email"]
    missing_fields = [field for field in required_fields if field not in payload]

    if missing_fields:
        raise PermanentError(f"Missing required fields in payload: {', '.join(missing_fields)}")


def merge_namespace_roles(existing_roles: list, new_roles: list) -> list:
    """
    Merge existing and new namespace roles, ensuring no duplicates.
    """
    existing_roles_set = {frozenset(role.items()) for role in existing_roles}
    new_roles_set = {frozenset(role.items()) for role in new_roles}

    merged_roles = existing_roles_set | new_roles_set  # Union of both sets
    return [dict(role) for role in merged_roles]  # Convert back to list of dicts


@with_retry(max_attempts=3)
def create_user_in_tenant(_api, first_name: str, last_name: str, idm_type: str, email: str, group_names: list, namespace_roles: list) -> str:
    """
    Create a new user in the tenant.
    """
    try:
        payload = _api.create_payload(
            first_name=first_name,
            last_name=last_name,
            idm_type=idm_type,
            email=email,
            group_names=group_names,
            namespace_roles=namespace_roles
        )
        _api.create(payload)
        return f"User '{email}' created successfully."
    except Exception as e:
        error_msg = str(e)
        if "already exist" in error_msg:
            raise  # Re-raise to handle idempotency in caller
        if "401" in error_msg or "403" in error_msg:
            raise PermanentError(f"Authentication/authorization failed: {e}") from e
        if "429" in error_msg:
            raise RateLimitError(f"Rate limited: {e}") from e
        if "502" in error_msg or "503" in error_msg or "504" in error_msg:
            raise TransientError(f"Gateway error: {e}") from e
        raise TransientError(f"Failed to create user: {e}") from e


@with_retry(max_attempts=3)
def update_user_in_tenant(_api, first_name: str, last_name: str, email: str, merged_roles: list, merged_group_names: list) -> str:
    """
    Update an existing user in the tenant with merged namespace roles and group names.
    """
    try:
        updated_payload = _api.update_payload(
            email=email,
            first_name=first_name,
            last_name=last_name,
            namespace_roles=merged_roles,
            group_names=merged_group_names
        )
        _api.update(updated_payload)
        return f"User '{email}' updated successfully."
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "403" in error_msg:
            raise PermanentError(f"Authentication/authorization failed: {e}") from e
        if "429" in error_msg:
            raise RateLimitError(f"Rate limited: {e}") from e
        if "502" in error_msg or "503" in error_msg or "504" in error_msg:
            raise TransientError(f"Gateway error: {e}") from e
        raise TransientError(f"Failed to update user: {e}") from e


@with_retry(max_attempts=3)
def list_users(_api):
    """
    List users from the tenant.
    """
    try:
        return _api.list()
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg:
            raise RateLimitError(f"Rate limited: {e}") from e
        if "502" in error_msg or "503" in error_msg or "504" in error_msg:
            raise TransientError(f"Gateway error: {e}") from e
        raise TransientError(f"Failed to list users: {e}") from e


@lambda_handler
def handler(event: dict, context, logger: StructuredLogger):
    """
    Main handler to process the payload and create or update a user.
    """
    step_logger = logger.with_step("validate_payload")
    step_logger.info("Validating payload")
    validate_payload(event)

    ssm_base_path = event["ssm_base_path"]
    first_name = event["first_name"]
    last_name = event["last_name"]
    email = event["email"]
    group_names = event.get("group_names", [])
    namespace_roles = event.get("namespace_roles", [])

    step_logger = logger.with_step("fetch_parameters")
    step_logger.info("Fetching parameters from SSM", ssm_base_path=ssm_base_path)
    region = boto3.session.Session().region_name
    params = get_parameters(
        [
            f"{ssm_base_path}/tenant-url",
            f"{ssm_base_path}/token-value",
            f"{ssm_base_path}/idm-type",
        ],
        region_name=region,
    )

    auth = session(tenant_url=params["tenant-url"], api_token=params["token-value"])
    _api = user(auth)

    # Attempt to create the user first
    step_logger = logger.with_step("create_user")
    step_logger.info("Attempting to create user", email=email)
    try:
        result_message = create_user_in_tenant(
            _api, first_name, last_name, params["idm-type"], email, group_names, namespace_roles
        )
        step_logger.info("User created successfully", email=email)
    except Exception as e:
        if "already exist" not in str(e):
            raise  # If it's a different error, re-raise it

        step_logger.info("User already exists, checking for updates", email=email)

        # If the user already exists, fetch the current user list
        existing_users = list_users(_api)
        existing_user = next((u for u in existing_users if u.get("email") == email), None)

        if existing_user:
            existing_roles = existing_user.get("namespace_roles", [])
            existing_group_names = existing_user.get("group_names", [])

            # Merge namespace roles
            merged_roles = merge_namespace_roles(existing_roles, namespace_roles)

            # Merge group names (remove duplicates)
            merged_group_names = list(set(existing_group_names) | set(group_names))

            # Only update if changes are detected
            step_logger = logger.with_step("update_user")
            if existing_roles != merged_roles or existing_group_names != merged_group_names:
                step_logger.info(
                    "Changes detected, updating user",
                    email=email,
                    roles_changed=existing_roles != merged_roles,
                    groups_changed=existing_group_names != merged_group_names
                )
                result_message = update_user_in_tenant(_api, first_name, last_name, email, merged_roles, merged_group_names)
                step_logger.info("User updated successfully", email=email)
            else:
                step_logger.info("No changes detected, skipping update", email=email)
                result_message = f"User '{email}' already exists with the correct settings. No update needed."
        else:
            raise PermanentError(f"User '{email}' reported existing but was not found in the user list.") from e

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
        "first_name": "Tenant",
        "last_name": "Ops",
        "email": "tops@f5demos.com",
        "group_names": [],
        "namespace_roles": [{"namespace": "default", "role": "ves-io-monitor-role"}]
    }

    class MockContext:
        function_name = "user_create"

    handler(test_payload, MockContext())
