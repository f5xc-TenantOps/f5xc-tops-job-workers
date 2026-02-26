"""Validate and prepare job configuration for provisioning workflow."""

from typing import Any, Dict

from shared.decorators import lambda_handler
from shared.errors import PermanentError
from shared.job_config import validate_job_config, substitute_variables
from shared.logging import StructuredLogger


def prepare_config(event: Dict[str, Any], logger: StructuredLogger) -> Dict[str, Any]:
    """Validate and prepare job configuration.

    Args:
        event: Must contain job_config dict.
               Must include email and petname for variable substitution.
        logger: Structured logger.

    Returns:
        Dict with validated job_config and variables.
    """
    step = logger.with_step("prepare_config")

    if "job_config" not in event:
        raise PermanentError("Event must contain 'job_config'")

    raw_config = event["job_config"]
    step.info("Using job config from event")

    # Extract variables for substitution
    variables = {
        "petname": event.get("petname", ""),
        "email": event.get("email", ""),
        "job_id": raw_config.get("job_id", ""),
    }

    # Validate the config
    job_config = validate_job_config(raw_config)

    # Substitute variables in resources
    substituted_resources = []
    for resource in job_config.resources:
        substituted_resources.append({
            "type": resource.type,
            "depends_on": substitute_variables(resource.depends_on, variables),
            "metadata": substitute_variables(resource.metadata, variables),
            "spec": substitute_variables(resource.spec, variables),
        })

    # Build result
    result = {
        "job_config": {
            "job_id": job_config.job_id,
            "ssm_base_path": job_config.ssm_base_path,
            "description": job_config.description,
            "user": substitute_variables({
                "enabled": job_config.user.enabled,
                "group_names": job_config.user.group_names,
                "namespace_roles": job_config.user.namespace_roles,
            }, variables),
            "namespace": {
                "enabled": job_config.namespace.enabled,
            },
            "resources": substituted_resources,
        },
        "variables": variables,
        "email": event.get("email"),
        "petname": event.get("petname"),
        "ssm_base_path": job_config.ssm_base_path,
    }

    step.info("Job config prepared",
              job_id=job_config.job_id,
              resource_count=len(substituted_resources))

    return result


@lambda_handler
def handler(event: Dict[str, Any], context, logger: StructuredLogger) -> Dict[str, Any]:
    """Lambda entry point."""
    return prepare_config(event, logger)


if __name__ == "__main__":
    class MockContext:
        function_name = "prepare_job_config"

    test_event = {
        "job_config": {
            "job_id": "test",
            "ssm_base_path": "/test",
            "user": {"enabled": True, "group_names": [], "namespace_roles": []},
            "namespace": {"enabled": True},
            "resources": []
        },
        "email": "test@test.com",
        "petname": "test-pet"
    }
    handler(test_event, MockContext())
