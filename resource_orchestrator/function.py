"""Resource orchestrator for provisioning workflow.

Builds dependency graph and executes resource lambdas in correct order.
"""

import json
import os
from typing import Any, Dict, List

from shared.decorators import lambda_handler
from shared.dependency_graph import build_execution_order, DependencyCycleError
from shared.errors import PermanentError, TransientError
from shared.job_config import ResourceDefinition
from shared.job_state import JobState, JobStatus, StepStatus
from shared.logging import StructuredLogger
from shared.state import StateManager, get_job_state_from_event


# Lazy-loaded boto3 client
lambda_client = None

# Lambda function name prefix (e.g., "tops-" in prod, "tops-dev-" in dev)
LAMBDA_PREFIX = os.getenv("LAMBDA_PREFIX", "tops-")

# Timeout for Lambda invoke calls (default 5 minutes)
LAMBDA_INVOKE_TIMEOUT_SECONDS = int(os.getenv("LAMBDA_INVOKE_TIMEOUT_SECONDS", "300"))


def _get_lambda_client():
    """Get or create the Lambda client with configured timeout."""
    global lambda_client
    if lambda_client is None:
        import boto3
        from botocore.config import Config

        config = Config(
            read_timeout=LAMBDA_INVOKE_TIMEOUT_SECONDS,
            connect_timeout=10,
        )
        lambda_client = boto3.client("lambda", config=config)
    return lambda_client


def build_execution_plan(resources: List[Dict[str, Any]], logger: StructuredLogger) -> List[List[Dict[str, Any]]]:
    """Build execution levels from resource list.

    Args:
        resources: List of resource dicts with type, depends_on, metadata, spec.
        logger: Structured logger.

    Returns:
        List of levels, each containing resources to execute in parallel.
    """
    step = logger.with_step("build_execution_plan")

    if not resources:
        step.info("No resources to process")
        return []

    # Convert to ResourceDefinition objects
    resource_defs = [
        ResourceDefinition(
            type=r["type"],
            depends_on=r.get("depends_on", []),
            metadata=r["metadata"],
            spec=r["spec"]
        )
        for r in resources
    ]

    try:
        levels = build_execution_order(resource_defs)
        # Convert back to dicts for JSON serialization
        result = [
            [
                {
                    "type": r.type,
                    "depends_on": r.depends_on,
                    "metadata": r.metadata,
                    "spec": r.spec
                }
                for r in level
            ]
            for level in levels
        ]
        step.info("Built execution plan", levels=len(result), total_resources=len(resources))
        return result
    except DependencyCycleError as e:
        step.error("Dependency cycle detected", error=str(e))
        raise PermanentError(f"Invalid resource dependencies: {e}") from e


def execute_resource(resource: Dict[str, Any], ssm_base_path: str, logger: StructuredLogger,
                     job_state: JobState = None, lab_id: str = None) -> Dict[str, Any]:
    """Execute a single resource creation lambda.

    Args:
        resource: Resource definition with type, metadata, spec.
        ssm_base_path: SSM parameter path for credentials.
        logger: Structured logger.
        job_state: Optional job state for state coordination.
        lab_id: Optional lab identifier.

    Returns:
        Result from the resource lambda.
    """
    resource_type = resource["type"]
    resource_name = resource["metadata"]["name"]
    step = logger.with_step(f"execute_{resource_type}")

    # Determine lambda function name
    function_name = f"{LAMBDA_PREFIX}{resource_type}_create"

    payload = {
        "ssm_base_path": ssm_base_path,
        "metadata": resource["metadata"],
        "spec": resource["spec"],
        "lab_id": lab_id,
    }

    # Include job_state if present
    if job_state:
        payload["job_state"] = {
            "job_execution_id": job_state.job_execution_id,
            "job_id": job_state.job_id,
            "trigger_source": job_state.trigger_source,
            "email": job_state.email,
            "petname": job_state.petname,
            "dep_id": job_state.dep_id,
            "status": job_state.status.value if isinstance(job_state.status, JobStatus) else job_state.status,
            "steps": job_state.steps,
            "resources": job_state.resources,
        }

    step.info("Invoking resource lambda",
              function=function_name,
              resource_name=resource_name)

    client = _get_lambda_client()

    try:
        response = client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload)
        )

        result = json.loads(response["Payload"].read())

        if result.get("statusCode") == 200:
            step.info("Resource created successfully", resource_name=resource_name)
            return {"status": "success", "name": resource_name, "type": resource_type}
        else:
            error = result.get("body", "Unknown error")
            step.error("Resource creation failed", resource_name=resource_name, error=error)
            raise TransientError(f"Resource creation failed: {error}")

    except client.exceptions.ResourceNotFoundException:
        step.error("Resource lambda not found", function=function_name)
        raise PermanentError(f"Lambda function not found: {function_name}")
    except Exception as e:
        step.error("Lambda invocation failed", error=str(e))
        raise TransientError(f"Failed to invoke {function_name}: {e}") from e


def orchestrate(event: Dict[str, Any], logger: StructuredLogger) -> Dict[str, Any]:
    """Orchestrate resource creation.

    Args:
        event: Contains job_config with resources and ssm_base_path.
        logger: Structured logger.

    Returns:
        Dict with created resources and their statuses.
    """
    step = logger.with_step("orchestrate")

    job_config = event.get("job_config", {})
    resources = job_config.get("resources", [])
    ssm_base_path = event.get("ssm_base_path", job_config.get("ssm_base_path"))
    lab_id = event.get("lab_id")

    if not ssm_base_path:
        raise PermanentError("Missing ssm_base_path")

    # Get job state for state updates
    job_state = get_job_state_from_event(event)
    state_manager = StateManager() if job_state else None

    # Mark resources step started
    if state_manager and job_state:
        state_manager.mark_step_started(job_state, "resources", lab_id=lab_id)

    # Build execution plan
    levels = build_execution_plan(resources, logger)

    if not levels:
        step.info("No resources to create")
        if state_manager and job_state:
            job_state.update_step("resources", StepStatus.SUCCESS)
            state_manager.update_state(job_state, lab_id=lab_id)
        return {"status": "success", "resources": {}}

    # Execute each level
    results = {}
    failed_resources = set()
    for level_idx, level in enumerate(levels):
        step.info(f"Executing level {level_idx}", resource_count=len(level))

        for resource in level:
            resource_name = resource["metadata"]["name"]
            depends_on = resource.get("depends_on", [])

            # Check if any dependency failed
            failed_deps = [dep for dep in depends_on if dep in failed_resources]
            if failed_deps:
                step.warn("Skipping resource due to failed dependencies",
                          resource_name=resource_name,
                          failed_dependencies=failed_deps)
                results[resource_name] = {
                    "status": "failed",
                    "name": resource_name,
                    "type": resource["type"],
                    "error": "dependency failed"
                }
                failed_resources.add(resource_name)
                continue

            try:
                result = execute_resource(resource, ssm_base_path, logger, job_state, lab_id)
                results[resource_name] = result
            except Exception as e:
                results[resource_name] = {
                    "status": "failed",
                    "name": resource_name,
                    "type": resource["type"],
                    "error": str(e)
                }
                failed_resources.add(resource_name)

    # Check for any failures and update state
    failed = [r for r in results.values() if r.get("status") == "failed"]
    if failed:
        step.warn("Some resources failed", failed_count=len(failed))
        if state_manager and job_state:
            job_state.update_step("resources", StepStatus.FAILED, error=f"{len(failed)} resources failed")
            state_manager.update_state(job_state, lab_id=lab_id)
        return {"status": "partial", "resources": results}

    step.info("All resources created successfully")
    if state_manager and job_state:
        job_state.update_step("resources", StepStatus.SUCCESS)
        state_manager.update_state(job_state, lab_id=lab_id)
    return {"status": "success", "resources": results}


@lambda_handler
def handler(event: Dict[str, Any], context, logger: StructuredLogger) -> Dict[str, Any]:
    """Lambda entry point."""
    return orchestrate(event, logger)


if __name__ == "__main__":
    class MockContext:
        function_name = "resource_orchestrator"

    test_event = {
        "ssm_base_path": "/tenantOps/test",
        "job_config": {
            "resources": [
                {"type": "origin_pool", "depends_on": [], "metadata": {"name": "test-pool", "namespace": "test"}, "spec": {}}
            ]
        }
    }
    handler(test_event, MockContext())
