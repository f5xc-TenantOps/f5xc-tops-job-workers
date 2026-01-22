"""Fetch and validate job configuration for provisioning workflow."""

import os
from typing import Any, Dict

from shared.decorators import lambda_handler
from shared.errors import PermanentError
from shared.job_config import validate_job_config, substitute_variables
from shared.logging import StructuredLogger


# Lazy-loaded boto3 client (avoids region issues at import time during tests)
dynamodb = None
JOB_CONFIG_TABLE = os.getenv("JOB_CONFIG_TABLE", "tops-job-configs")


def _get_dynamodb_client():
    """Get or create the DynamoDB client."""
    global dynamodb
    if dynamodb is None:
        import boto3
        dynamodb = boto3.client("dynamodb")
    return dynamodb


def parse_dynamodb_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Convert DynamoDB item to plain dict."""
    def parse_value(v):
        if "S" in v:
            return v["S"]
        elif "N" in v:
            return int(v["N"]) if "." not in v["N"] else float(v["N"])
        elif "BOOL" in v:
            return v["BOOL"]
        elif "L" in v:
            return [parse_value(i) for i in v["L"]]
        elif "M" in v:
            return {k: parse_value(val) for k, val in v["M"].items()}
        elif "NULL" in v:
            return None
        return v

    return {k: parse_value(v) for k, v in item.items()}


def fetch_config_from_dynamodb(job_id: str, logger: StructuredLogger) -> Dict[str, Any]:
    """Fetch job config from DynamoDB by job_id."""
    step = logger.with_step("fetch_from_dynamodb")
    try:
        client = _get_dynamodb_client()
        response = client.get_item(
            TableName=JOB_CONFIG_TABLE,
            Key={"job_id": {"S": job_id}}
        )
        if "Item" not in response:
            raise PermanentError(f"Job config not found: {job_id}")

        config = parse_dynamodb_item(response["Item"])
        step.info("Fetched job config", job_id=job_id)
        return config
    except PermanentError:
        raise
    except Exception as e:
        step.error("Failed to fetch job config", error=str(e))
        raise PermanentError(f"Failed to fetch job config: {e}") from e


def fetch_config(event: Dict[str, Any], logger: StructuredLogger) -> Dict[str, Any]:
    """Fetch and process job configuration.

    Args:
        event: Contains either job_config dict or job_id to lookup.
               Must include email and petname for variable substitution.
        logger: Structured logger.

    Returns:
        Dict with validated job_config and variables.
    """
    step = logger.with_step("fetch_config")

    # Get job config - either from event or DynamoDB
    if "job_config" in event:
        raw_config = event["job_config"]
        step.info("Using job config from event")
    elif "job_id" in event:
        raw_config = fetch_config_from_dynamodb(event["job_id"], logger)
    else:
        raise PermanentError("Event must contain either 'job_config' or 'job_id'")

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
            "depends_on": resource.depends_on,
            "metadata": substitute_variables(resource.metadata, variables),
            "spec": substitute_variables(resource.spec, variables),
        })

    # Build result
    result = {
        "job_config": {
            "job_id": job_config.job_id,
            "ssm_base_path": job_config.ssm_base_path,
            "description": job_config.description,
            "user": {
                "enabled": job_config.user.enabled,
                "group_names": job_config.user.group_names,
                "namespace_roles": job_config.user.namespace_roles,
            },
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

    step.info("Job config processed",
              job_id=job_config.job_id,
              resource_count=len(substituted_resources))

    return result


@lambda_handler
def handler(event: Dict[str, Any], context, logger: StructuredLogger) -> Dict[str, Any]:
    """Lambda entry point."""
    return fetch_config(event, logger)


if __name__ == "__main__":
    class MockContext:
        function_name = "fetch_job_config"

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
