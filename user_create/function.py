"""
Create or update a user in an F5 XC tenant.
"""
from typing import Optional

from shared.decorators import lambda_handler
from shared.errors import PermanentError, ResourceExistsError
from shared.job_state import JobState, JobStatus, StepStatus
from shared.logging import StructuredLogger
from shared.ssm import get_ssm_parameters
from shared.state import StateManager
from shared.xc_client import XCClient


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


def _get_job_state_from_event(event: dict) -> Optional[JobState]:
    """Extract JobState from event if present."""
    job_state_data = event.get("job_state")
    if not job_state_data:
        return None

    return JobState(
        job_execution_id=job_state_data["job_execution_id"],
        job_id=job_state_data["job_id"],
        trigger_source=job_state_data["trigger_source"],
        email=job_state_data["email"],
        petname=job_state_data["petname"],
        status=JobStatus(job_state_data.get("status", "IN_PROGRESS")),
        dep_id=job_state_data.get("dep_id"),
        steps=job_state_data.get("steps", {}),
        resources=job_state_data.get("resources", {}),
    )


@lambda_handler
def handler(event: dict, context, logger: StructuredLogger):
    """Main handler to process the payload and create or update a user."""
    step_logger = logger.with_step("validate_payload")
    step_logger.info("Validating payload")
    validate_payload(event)

    ssm_base_path = event["ssm_base_path"]
    first_name = event["first_name"]
    last_name = event["last_name"]
    email = event["email"]
    group_names = event.get("group_names", [])
    namespace_roles = event.get("namespace_roles", [])
    lab_id = event.get("lab_id")

    # Get job state for state updates
    job_state = _get_job_state_from_event(event)
    state_manager = StateManager() if job_state else None

    # Mark step started
    if state_manager and job_state:
        state_manager.mark_step_started(job_state, "user", lab_id=lab_id)

    try:
        step_logger = logger.with_step("fetch_parameters")
        step_logger.info("Fetching parameters from SSM", ssm_base_path=ssm_base_path)
        params = get_ssm_parameters([
            f"{ssm_base_path}/tenant-url",
            f"{ssm_base_path}/token-value",
        ])

        # Initialize XC client
        client = XCClient(
            tenant_url=params["tenant-url"],
            api_token=params["token-value"],
            validate=False
        )

        # Attempt to create the user first
        step_logger = logger.with_step("create_user")
        step_logger.info("Attempting to create user", email=email)
        try:
            client.create_user(email, first_name, last_name, group_names, namespace_roles)
            step_logger.info("User created successfully", email=email)

            # Mark step complete
            if state_manager and job_state:
                state_manager.mark_step_complete(
                    job_state, "user", StepStatus.SUCCESS, lab_id=lab_id, email=email
                )

            return f"User '{email}' created successfully."

        except ResourceExistsError:
            step_logger.info("User already exists, checking for updates", email=email)

            # If the user already exists, fetch the current user
            existing_user = client.get_user(email)

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
                    client.update_user(email, first_name, last_name, merged_roles, merged_group_names)
                    step_logger.info("User updated successfully", email=email)

                    # Mark step complete
                    if state_manager and job_state:
                        state_manager.mark_step_complete(
                            job_state, "user", StepStatus.SUCCESS, lab_id=lab_id, email=email
                        )

                    return f"User '{email}' updated successfully."
                else:
                    step_logger.info("No changes detected, skipping update", email=email)

                    # Mark step complete
                    if state_manager and job_state:
                        state_manager.mark_step_complete(
                            job_state, "user", StepStatus.SUCCESS, lab_id=lab_id, email=email
                        )

                    return f"User '{email}' already exists with the correct settings. No update needed."
            else:
                raise PermanentError(f"User '{email}' reported existing but was not found in the user list.")

    except Exception as e:
        # Mark step failed (but don't double-mark if it's a PermanentError we raised)
        if state_manager and job_state:
            state_manager.mark_step_failed(job_state, "user", str(e), lab_id=lab_id)
        raise


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
