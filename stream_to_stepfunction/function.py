"""Bridge DynamoDB stream events to Step Functions.

Triggered by DynamoDB deployment state table stream.
Starts the provisioning Step Function for INSERT events.
"""

import json
import os
import uuid
from typing import Any, Dict

from shared.decorators import lambda_handler
from shared.errors import PermanentError, TransientError
from shared.logging import StructuredLogger


# Lazy-initialized clients for testability
sfn_client = None
dynamodb = None

def _get_state_machine_arn() -> str:
    """Get state machine ARN from environment."""
    return os.getenv("STATE_MACHINE_ARN", "")


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


def get_job_id_for_lab(lab_id: str, logger: StructuredLogger) -> str:
    """Get job_id from lab configuration.

    For UDF labs, job_id = lab_id unless overridden in config.
    """
    step = logger.with_step("get_job_id")
    ddb = _get_dynamodb_client()
    try:
        response = ddb.get_item(
            TableName=_get_lab_config_table(),
            Key={"lab_id": {"S": lab_id}}
        )
        if "Item" not in response:
            step.warn("Lab config not found, using lab_id as job_id", lab_id=lab_id)
            return lab_id

        item = response["Item"]
        job_id = item.get("job_id", {}).get("S", lab_id)
        step.info("Found job_id for lab", lab_id=lab_id, job_id=job_id)
        return job_id
    except Exception as e:
        step.error("Failed to fetch lab config", error=str(e))
        return lab_id


def process_record(record: Dict[str, Any], logger: StructuredLogger) -> Dict[str, Any]:
    """Process a single DynamoDB stream record.

    Args:
        record: DynamoDB stream record.
        logger: Structured logger.

    Returns:
        Dict indicating whether Step Function was triggered.
    """
    step = logger.with_step("process_record")

    event_name = record.get("eventName")

    if event_name != "INSERT":
        step.info("Ignoring non-INSERT event", event_name=event_name)
        return {"triggered": False, "reason": f"Event type {event_name} ignored"}

    new_image = record.get("dynamodb", {}).get("NewImage", {})

    dep_id = new_image.get("dep_id", {}).get("S")
    lab_id = new_image.get("lab_id", {}).get("S")
    email = new_image.get("email", {}).get("S")
    petname = new_image.get("petname", {}).get("S")

    if not all([dep_id, lab_id, email, petname]):
        step.error("Missing required fields in stream record")
        return {"triggered": False, "reason": "Missing required fields"}

    # Get job_id from lab config
    job_id = get_job_id_for_lab(lab_id, logger)

    # Generate execution ID
    execution_id = str(uuid.uuid4())

    # Build Step Function input
    sfn_input = {
        "job_id": job_id,
        "job_execution_id": execution_id,
        "trigger_source": "udf",
        "dep_id": dep_id,
        "lab_id": lab_id,
        "email": email,
        "petname": petname,
    }

    step.info("Starting Step Function execution",
              execution_id=execution_id,
              job_id=job_id,
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
        step.info("Step Function started", execution_arn=execution_arn)

        return {
            "triggered": True,
            "execution_id": execution_id,
            "execution_arn": execution_arn
        }
    except Exception as e:
        step.error("Failed to start Step Function", error=str(e))
        raise TransientError(f"Failed to start Step Function: {e}") from e


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
