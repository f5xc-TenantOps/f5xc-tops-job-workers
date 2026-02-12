"""Create SecureMesh Site v2 and registration token in F5 XC tenant."""

import os
import time
from typing import Any, Dict

import boto3

from shared.decorators import lambda_handler
from shared.errors import ResourceExistsError
from shared.job_state import StepStatus
from shared.logging import StructuredLogger
from shared.ssm import get_ssm_parameters
from shared.state import StateManager, get_job_state_from_event
from shared.xc_client import XCClient

DEPLOYMENT_STATE_BUCKET = os.environ.get("DEPLOYMENT_STATE_BUCKET", "")


def create_site(event: Dict[str, Any], logger: StructuredLogger) -> Dict[str, Any]:
    """Create a SecureMesh Site v2 and its registration token.

    Steps:
        1. Create the site via XC API (system namespace).
        2. Create a JWT registration token for the site.
        3. Write the JWT to the deployment S3 bucket (if dep_id provided).

    Args:
        event: Contains ssm_base_path, metadata, spec, and optional dep_id.
        logger: Structured logger.

    Returns:
        Dict with status and resource name.
    """
    step = logger.with_step("create_securemesh_site_v2")

    ssm_base_path = event["ssm_base_path"]
    metadata = event["metadata"]
    spec = event["spec"]
    name = metadata["name"]
    dep_id = event.get("dep_id")

    # Get XC credentials
    params = get_ssm_parameters(
        [f"{ssm_base_path}/tenant-url", f"{ssm_base_path}/token-value"]
    )

    # Create XC client (has built-in retry logic)
    client = XCClient(
        tenant_url=params["tenant-url"],
        api_token=params["token-value"],
        validate=False  # Skip validation for performance
    )

    # Step 1: Create the site
    payload = {
        "namespace": "system",
        "metadata": metadata,
        "spec": spec
    }

    already_existed = False
    step.info("Creating SecureMesh Site v2", name=name)

    try:
        client.create_securemesh_site_v2(payload)
        step.info("Site created", name=name)
    except ResourceExistsError:
        step.info("Site already exists", name=name)
        already_existed = True

    # Step 2: Create registration token
    token_name = f"jwt-token-{int(time.time() * 1000)}"
    step.info("Creating registration token", site_name=name, token_name=token_name)

    token_response = client.create_registration_token(name, token_name)
    jwt_content = token_response["spec"]["content"]
    step.info("Registration token created", token_name=token_name)

    # Step 3: Write token to S3 (only if dep_id provided)
    if dep_id:
        s3 = boto3.client("s3")
        s3_key = f"{dep_id}/site_token"
        step.info("Writing token to S3", bucket=DEPLOYMENT_STATE_BUCKET, key=s3_key)
        s3.put_object(
            Bucket=DEPLOYMENT_STATE_BUCKET,
            Key=s3_key,
            Body=jwt_content,
            ContentType="text/plain"
        )
        step.info("Token written to S3")

    if already_existed:
        return {"status": "success", "name": name, "already_existed": True}
    return {"status": "success", "name": name, "created": True}


@lambda_handler
def handler(event: Dict[str, Any], context, logger: StructuredLogger) -> Dict[str, Any]:
    """Lambda entry point."""
    lab_id = event.get("lab_id")
    job_state = get_job_state_from_event(event)
    state_manager = StateManager() if job_state else None

    # Get resource info for state tracking
    resource_name = event.get("metadata", {}).get("name", "unknown")
    resource_type = "securemesh_site_v2"

    # Mark resource started
    if state_manager and job_state:
        job_state.update_resource(resource_name, StepStatus.IN_PROGRESS, type=resource_type)
        state_manager.update_state(job_state, lab_id=lab_id)

    try:
        result = create_site(event, logger)

        # Mark resource complete
        if state_manager and job_state:
            job_state.update_resource(resource_name, StepStatus.SUCCESS, type=resource_type)
            state_manager.update_state(job_state, lab_id=lab_id)

        return result
    except Exception as e:
        # Mark resource failed
        if state_manager and job_state:
            job_state.update_resource(resource_name, StepStatus.FAILED, type=resource_type, error=str(e))
            state_manager.update_state(job_state, lab_id=lab_id)
        raise


if __name__ == "__main__":
    class MockContext:
        function_name = "securemesh_site_v2_create"

    test_event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-site", "namespace": "system"},
        "spec": {"kvm": {"not_managed": {}}}
    }
    handler(test_event, MockContext())
