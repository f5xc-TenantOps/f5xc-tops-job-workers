"""Create Virtual K8s object in F5 XC tenant."""

import time
from typing import Any, Dict

from shared.decorators import lambda_handler
from shared.errors import ResourceExistsError, TransientError
from shared.job_state import StepStatus
from shared.logging import StructuredLogger
from shared.ssm import get_ssm_parameters
from shared.state import StateManager, get_job_state_from_event
from shared.xc_client import XCClient

POLL_INTERVAL = 5
POLL_TIMEOUT = 60


def wait_for_virtual_k8s(client: XCClient, namespace: str, name: str, logger: StructuredLogger, timeout: int = POLL_TIMEOUT, interval: int = POLL_INTERVAL) -> None:
    """Wait for the virtual_k8s object to be available."""
    step = logger.with_step("wait_for_virtual_k8s")
    start_time = time.time()

    step.info("Waiting for virtual_k8s", name=name, namespace=namespace, timeout=timeout)

    while time.time() - start_time < timeout:
        try:
            response = client.get_virtual_k8s(namespace, name)
            if response:
                step.info("Virtual K8s available", name=name)
                return
        except Exception as e:
            step.info("Virtual K8s not ready yet", name=name, error=str(e))
        time.sleep(interval)

    raise TransientError(f"Virtual K8s '{name}' was not available within {timeout} seconds.")


def create_vk8s(event: Dict[str, Any], logger: StructuredLogger) -> Dict[str, Any]:
    """Create a Virtual K8s object in F5 XC.

    Args:
        event: Contains ssm_base_path, metadata, and spec.
        logger: Structured logger.

    Returns:
        Dict with status and resource name.
    """
    step = logger.with_step("create_virtual_k8s")

    ssm_base_path = event["ssm_base_path"]
    metadata = event["metadata"]
    spec = event["spec"]
    name = metadata["name"]
    namespace = metadata["namespace"]

    params = get_ssm_parameters(
        [f"{ssm_base_path}/tenant-url", f"{ssm_base_path}/token-value"]
    )

    client = XCClient(
        tenant_url=params["tenant-url"],
        api_token=params["token-value"],
        validate=False
    )

    payload = {
        "metadata": metadata,
        "spec": spec
    }

    step.info("Creating virtual_k8s", name=name, namespace=namespace)

    try:
        client.create_virtual_k8s(namespace, payload)
        step.info("Virtual K8s created, waiting for readiness", name=name)
        wait_for_virtual_k8s(client, namespace, name, logger)
        return {"status": "success", "name": name, "created": True}
    except ResourceExistsError:
        step.info("Virtual K8s already exists", name=name)
        return {"status": "success", "name": name, "already_existed": True}


@lambda_handler
def handler(event: Dict[str, Any], context, logger: StructuredLogger) -> Dict[str, Any]:
    """Lambda entry point."""
    lab_id = event.get("lab_id")
    job_state = get_job_state_from_event(event)
    state_manager = StateManager() if job_state else None

    resource_name = event.get("metadata", {}).get("name", "unknown")
    resource_type = "virtual_k8s"

    if state_manager and job_state:
        job_state.update_resource(resource_name, StepStatus.IN_PROGRESS, type=resource_type)
        state_manager.update_state(job_state, lab_id=lab_id)

    try:
        result = create_vk8s(event, logger)

        if state_manager and job_state:
            job_state.update_resource(resource_name, StepStatus.SUCCESS, type=resource_type)
            state_manager.update_state(job_state, lab_id=lab_id)

        return result
    except Exception as e:
        if state_manager and job_state:
            job_state.update_resource(resource_name, StepStatus.FAILED, type=resource_type, error=str(e))
            state_manager.update_state(job_state, lab_id=lab_id)
        raise


if __name__ == "__main__":
    class MockContext:
        function_name = "virtual_k8s_create"

    test_event = {
        "ssm_base_path": "/tenantOps/test",
        "metadata": {"name": "test-vk8s", "namespace": "test"},
        "spec": {"vsite_refs": [{"name": "vs1", "namespace": "shared", "tenant": "t1"}]}
    }
    handler(test_event, MockContext())
