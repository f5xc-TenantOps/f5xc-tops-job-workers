"""Bridge DynamoDB stream events to Step Functions.

Triggered by DynamoDB deployment state table stream.
Starts the provisioning Step Function for INSERT events
and the cleanup Step Function for REMOVE events.
"""

import json
import os
import uuid
from typing import Any, Dict, Optional

from shared.decorators import lambda_handler
from shared.errors import PermanentError, TransientError
from shared.job_state import JobState, JobStatus
from shared.logging import StructuredLogger
from shared.state import StateManager


# Lazy-initialized clients for testability
sfn_client = None
dynamodb = None

def _get_state_machine_arn() -> str:
    """Get provisioning state machine ARN from environment."""
    return os.getenv("STATE_MACHINE_ARN", "")


def _get_cleanup_state_machine_arn() -> str:
    """Get cleanup state machine ARN from environment."""
    return os.getenv("CLEANUP_STATE_MACHINE_ARN", "")


def _get_lab_config_table() -> str:
    """Get lab config table name from environment."""
    return os.getenv("LAB_CONFIGURATION_TABLE", "tops-udf-lab-config")


def _get_sfn_client():
    """Lazy load Step Functions client."""
    global sfn_client
    if sfn_client is None:
        import boto3
        sfn_client = boto3.client("stepfunctions")
    return sfn_client


def _get_dynamodb_client():
    """Lazy load DynamoDB client."""
    global dynamodb
    if dynamodb is None:
        import boto3
        dynamodb = boto3.client("dynamodb")
    return dynamodb


def _parse_dynamodb_value(v: Dict[str, Any]) -> Any:
    """Parse a single DynamoDB-typed value to native Python."""
    if "S" in v:
        return v["S"]
    elif "N" in v:
        return int(v["N"]) if "." not in v["N"] else float(v["N"])
    elif "BOOL" in v:
        return v["BOOL"]
    elif "L" in v:
        return [_parse_dynamodb_value(i) for i in v["L"]]
    elif "M" in v:
        return {k: _parse_dynamodb_value(val) for k, val in v["M"].items()}
    elif "NULL" in v:
        return None
    return v


def _parse_dynamodb_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a full DynamoDB item to a plain dict."""
    return {k: _parse_dynamodb_value(v) for k, v in item.items()}


def get_lab_config(lab_id: str, logger: StructuredLogger) -> Dict[str, Any]:
    """Get full lab configuration including inline resources.

    Returns the parsed lab config item with user, namespace, resources fields.
    """
    step = logger.with_step("get_lab_config")
    ddb = _get_dynamodb_client()
    try:
        response = ddb.get_item(
            TableName=_get_lab_config_table(),
            Key={"lab_id": {"S": lab_id}}
        )
        if "Item" not in response:
            step.error("Lab config not found", lab_id=lab_id)
            raise PermanentError(f"Lab config not found for lab_id: {lab_id}")

        config = _parse_dynamodb_item(response["Item"])
        step.info("Lab config loaded", lab_id=lab_id, job_id=config.get("job_id", lab_id))
        return config
    except PermanentError:
        raise
    except Exception as e:
        step.error("Failed to fetch lab config", error=str(e))
        raise TransientError(f"Failed to fetch lab config: {e}") from e


def build_job_config(lab_config: Dict[str, Any]) -> Dict[str, Any]:
    """Build inline job_config from enriched lab config.

    Translates the lab config item into the format expected by prepare_job_config.
    """
    return {
        "job_id": lab_config.get("job_id", lab_config["lab_id"]),
        "ssm_base_path": lab_config["ssm_base_path"],
        "description": lab_config.get("description", ""),
        "user": lab_config.get("user", {"enabled": False, "group_names": [], "namespace_roles": []}),
        "namespace": lab_config.get("namespace", {"enabled": False}),
        "resources": lab_config.get("resources", []),
    }


def process_insert(record: Dict[str, Any], logger: StructuredLogger) -> Dict[str, Any]:
    """Process an INSERT event - start provisioning workflow.

    Args:
        record: DynamoDB stream record.
        logger: Structured logger.

    Returns:
        Dict indicating whether Step Function was triggered.
    """
    step = logger.with_step("process_insert")

    new_image = record.get("dynamodb", {}).get("NewImage", {})

    dep_id = new_image.get("dep_id", {}).get("S")
    lab_id = new_image.get("lab_id", {}).get("S")
    email = new_image.get("email", {}).get("S")
    petname = new_image.get("petname", {}).get("S")

    if not all([dep_id, lab_id, email, petname]):
        step.error("Missing required fields in stream record")
        return {"triggered": False, "reason": "Missing required fields"}

    # Get enriched lab config with inline resources
    lab_config = get_lab_config(lab_id, logger)
    job_config = build_job_config(lab_config)

    # Generate execution ID
    execution_id = str(uuid.uuid4())

    # Create initial job state
    state_manager = StateManager()
    job_state = JobState(
        job_execution_id=execution_id,
        job_id=job_config["job_id"],
        trigger_source="udf",
        email=email,
        petname=petname,
        dep_id=dep_id,
        status=JobStatus.PENDING,
    )

    # Write initial state to S3 and DynamoDB
    state_manager.update_state(job_state, lab_id=lab_id)
    step.info("Initial job state created", execution_id=execution_id)

    # Build Step Function input with inline job_config
    sfn_input = {
        "job_id": job_config["job_id"],
        "job_config": job_config,
        "job_execution_id": execution_id,
        "trigger_source": "udf",
        "dep_id": dep_id,
        "lab_id": lab_id,
        "email": email,
        "petname": petname,
        "job_state": {
            "job_execution_id": execution_id,
            "job_id": job_config["job_id"],
            "trigger_source": "udf",
            "email": email,
            "petname": petname,
            "dep_id": dep_id,
            "status": "IN_PROGRESS",
            "steps": {},
            "resources": {},
        },
    }

    step.info("Starting provisioning Step Function",
              execution_id=execution_id,
              job_id=job_config["job_id"],
              dep_id=dep_id)

    state_machine_arn = _get_state_machine_arn()
    if not state_machine_arn:
        raise PermanentError("STATE_MACHINE_ARN environment variable not set")

    sfn = _get_sfn_client()
    try:
        response = sfn.start_execution(
            stateMachineArn=state_machine_arn,
            name=f"{dep_id}-{execution_id[:8]}",
            input=json.dumps(sfn_input)
        )

        execution_arn = response["executionArn"]
        step.info("Provisioning Step Function started", execution_arn=execution_arn)

        return {
            "triggered": True,
            "execution_id": execution_id,
            "execution_arn": execution_arn
        }
    except Exception as e:
        step.error("Failed to start provisioning Step Function", error=str(e))
        raise TransientError(f"Failed to start Step Function: {e}") from e


def _check_existing_user_in_tenant(email: str, tenant_url: Optional[str], logger: StructuredLogger) -> bool:
    """Check if another active deployment exists for the same user in the same tenant.

    Returns True if user removal should be skipped (another deployment exists).
    """
    step = logger.with_step("check_existing_user")
    if not tenant_url:
        step.warn("No tenant_url available, will not skip user removal")
        return False

    ddb = _get_dynamodb_client()
    deployment_state_table = os.getenv("DEPLOYMENT_STATE_TABLE", "")
    if not deployment_state_table:
        step.warn("DEPLOYMENT_STATE_TABLE not set, will not skip user removal")
        return False

    try:
        response = ddb.scan(
            TableName=deployment_state_table,
            FilterExpression="email = :email AND tenant_url = :tenant",
            ExpressionAttributeValues={
                ":email": {"S": email},
                ":tenant": {"S": tenant_url}
            }
        )
        exists = bool(response.get("Items"))
        if exists:
            step.info("Another active deployment found, will skip user removal",
                      email=email, tenant_url=tenant_url)
        return exists
    except Exception as e:
        step.warn("Error checking for duplicate user, proceeding with removal", error=str(e))
        return False


def process_remove(record: Dict[str, Any], logger: StructuredLogger) -> Dict[str, Any]:
    """Process a REMOVE event - start cleanup workflow.

    Args:
        record: DynamoDB stream record with OldImage.
        logger: Structured logger.

    Returns:
        Dict indicating whether cleanup Step Function was triggered.
    """
    step = logger.with_step("process_remove")

    old_image = record.get("dynamodb", {}).get("OldImage", {})

    dep_id = old_image.get("dep_id", {}).get("S")
    lab_id = old_image.get("lab_id", {}).get("S")
    email = old_image.get("email", {}).get("S")
    petname = old_image.get("petname", {}).get("S")
    tenant_url = old_image.get("tenant_url", {}).get("S")

    if not all([dep_id, lab_id, email, petname]):
        step.error("Missing required fields in REMOVE record")
        return {"triggered": False, "reason": "Missing required fields"}

    # Get lab config for ssm_base_path
    lab_config = get_lab_config(lab_id, logger)

    # Check for duplicate user in same tenant (preserve legacy behavior)
    skip_user_removal = _check_existing_user_in_tenant(email, tenant_url, logger)

    cleanup_state_machine_arn = _get_cleanup_state_machine_arn()
    if not cleanup_state_machine_arn:
        step.error("CLEANUP_STATE_MACHINE_ARN not set")
        raise PermanentError("CLEANUP_STATE_MACHINE_ARN environment variable not set")

    execution_id = str(uuid.uuid4())

    sfn_input = {
        "dep_id": dep_id,
        "lab_id": lab_id,
        "email": email,
        "petname": petname,
        "tenant_url": tenant_url,
        "ssm_base_path": lab_config["ssm_base_path"],
        "namespace_enabled": lab_config.get("namespace", {}).get("enabled", True),
        "user_enabled": lab_config.get("user", {}).get("enabled", True),
        "skip_user_removal": skip_user_removal,
    }

    step.info("Starting cleanup Step Function",
              dep_id=dep_id,
              email=email,
              petname=petname)

    sfn = _get_sfn_client()
    try:
        response = sfn.start_execution(
            stateMachineArn=cleanup_state_machine_arn,
            name=f"cleanup-{dep_id}-{execution_id[:8]}",
            input=json.dumps(sfn_input)
        )

        execution_arn = response["executionArn"]
        step.info("Cleanup Step Function started", execution_arn=execution_arn)

        return {
            "triggered": True,
            "execution_id": execution_id,
            "execution_arn": execution_arn
        }
    except Exception as e:
        step.error("Failed to start cleanup Step Function", error=str(e))
        raise TransientError(f"Failed to start cleanup Step Function: {e}") from e


def process_record(record: Dict[str, Any], logger: StructuredLogger) -> Dict[str, Any]:
    """Process a single DynamoDB stream record.

    Args:
        record: DynamoDB stream record.
        logger: Structured logger.

    Returns:
        Dict indicating whether Step Function was triggered.
    """
    event_name = record.get("eventName")

    if event_name == "INSERT":
        return process_insert(record, logger)
    elif event_name == "REMOVE":
        return process_remove(record, logger)
    else:
        logger.info("Ignoring event", event_name=event_name)
        return {"triggered": False, "reason": f"Event type {event_name} ignored"}


@lambda_handler
def handler(event: Dict[str, Any], context, logger: StructuredLogger) -> Dict[str, Any]:
    """Lambda entry point for DynamoDB stream trigger."""
    results = []

    for record in event.get("Records", []):
        result = process_record(record, logger)
        results.append(result)

    triggered_count = sum(1 for r in results if r.get("triggered"))
    logger.info("Stream processing complete",
                total_records=len(results),
                triggered=triggered_count)

    return {"processed": len(results), "triggered": triggered_count}


if __name__ == "__main__":
    class MockContext:
        function_name = "stream_to_stepfunction"

    test_event = {
        "Records": [
            {
                "eventName": "INSERT",
                "dynamodb": {
                    "NewImage": {
                        "dep_id": {"S": "dep-test"},
                        "lab_id": {"S": "lab-test"},
                        "email": {"S": "test@test.com"},
                        "petname": {"S": "test-pet"}
                    }
                }
            }
        ]
    }
    handler(test_event, MockContext())
