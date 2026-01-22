"""
Create a namespace in an F5 XC tenant and verify its availability.
"""
import time
from typing import Optional

from shared.decorators import lambda_handler
from shared.errors import PermanentError, ResourceExistsError, TransientError
from shared.job_state import StepStatus
from shared.logging import StructuredLogger
from shared.ssm import get_ssm_parameters
from shared.state import get_job_state_from_event, StateManager
from shared.xc_client import XCClient


def validate_payload(payload: dict):
    """
    Validate the payload for required fields.
    """
    required_fields = ["ssm_base_path", "namespace_name"]
    missing_fields = [field for field in required_fields if field not in payload]

    if missing_fields:
        raise PermanentError(f"Missing required fields in payload: {', '.join(missing_fields)}")


def wait_for_namespace(client: XCClient, namespace_name: str, logger: StructuredLogger, timeout: int = 20, interval: int = 5) -> str:
    """
    Wait for the namespace to be available.
    """
    step_logger = logger.with_step("wait_for_namespace")
    start_time = time.time()

    step_logger.info("Waiting for namespace", namespace=namespace_name, timeout=timeout)

    while time.time() - start_time < timeout:
        try:
            response = client.get_namespace(namespace_name)
            if response:
                step_logger.info("Namespace available", namespace=namespace_name)
                return f"Namespace '{namespace_name}' is available."
        except Exception as e:
            step_logger.info("Namespace not ready yet", namespace=namespace_name, error=str(e))
            time.sleep(interval)

    raise TransientError(f"Namespace '{namespace_name}' was not available within {timeout} seconds.")


@lambda_handler
def handler(event: dict, context, logger: StructuredLogger):
    """Main handler to process the payload, create a namespace, and verify its availability."""
    validate_payload(event)

    ssm_base_path = event["ssm_base_path"]
    namespace_name = event["namespace_name"]
    description = event.get("description", "")
    lab_id = event.get("lab_id")

    # Get job state for state updates
    job_state = get_job_state_from_event(event)
    state_manager = StateManager() if job_state else None

    # Mark step started
    if state_manager and job_state:
        state_manager.mark_step_started(job_state, "namespace", lab_id=lab_id)

    try:
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

        # Create namespace
        step_logger = logger.with_step("create_namespace")
        try:
            step_logger.info("Creating namespace", namespace=namespace_name)
            client.create_namespace(namespace_name, description)
            step_logger.info("Namespace created", namespace=namespace_name)
            create_result = f"Namespace '{namespace_name}' created successfully."
        except ResourceExistsError:
            step_logger.info("Namespace already exists", namespace=namespace_name)
            create_result = f"Namespace '{namespace_name}' already exists."

        # Wait for the namespace to be available
        wait_result = wait_for_namespace(client, namespace_name, logger)

        # Mark step complete
        if state_manager and job_state:
            state_manager.mark_step_complete(
                job_state, "namespace", StepStatus.SUCCESS, lab_id=lab_id, name=namespace_name
            )

        return f"{create_result} | {wait_result}"

    except Exception as e:
        # Mark step failed
        if state_manager and job_state:
            state_manager.mark_step_failed(job_state, "namespace", str(e), lab_id=lab_id)
        raise


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
