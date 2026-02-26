import json
import os
import time
from datetime import datetime
import boto3

from shared.logging import StructuredLogger
from shared.errors import PermanentError, TransientError
from shared.decorators import lambda_handler, extract_correlation_id
from shared.ssm import get_ssm_parameters

# AWS Clients
dynamodb = boto3.client("dynamodb")

# Environment Variables
DEPLOYMENT_TABLE = os.getenv("DEPLOYMENT_STATE_TABLE")
LAB_CONFIGURATION_TABLE = os.getenv("LAB_CONFIGURATION_TABLE", "")
TTL_EXTENSION_SECONDS = 300

if not DEPLOYMENT_TABLE:
    raise ValueError("DEPLOYMENT_STATE_TABLE environment variable is not set.")


def validate_message(message: dict, logger: StructuredLogger):
    """
    Validate that required fields exist in the SQS message.
    """
    step_logger = logger.with_step("validate_message")
    required_fields = ["dep_id", "lab_id", "email", "petname"]
    missing_fields = [field for field in required_fields if field not in message]

    if missing_fields:
        step_logger.error("Missing required fields", missing_fields=missing_fields)
        raise PermanentError(f"Missing required fields in message: {', '.join(missing_fields)}")

    step_logger.info("Message validated successfully", dep_id=message.get("dep_id"))


def check_existing_deployment(dep_id: str, logger: StructuredLogger):
    """
    Check if a dep_id (deployment_id) already exists in DynamoDB.
    """
    step_logger = logger.with_step("check_deployment")
    try:
        step_logger.info("Checking for existing deployment", dep_id=dep_id)
        response = dynamodb.get_item(
            TableName=DEPLOYMENT_TABLE,
            Key={"dep_id": {"S": dep_id}}
        )
        exists = response.get("Item") is not None
        step_logger.info("Deployment check complete", dep_id=dep_id, exists=exists)
        return response.get("Item")
    except Exception as e:
        step_logger.error("DynamoDB get_item failed", dep_id=dep_id, error=str(e))
        raise TransientError(f"Error checking existing deployment: {e}") from e


def extend_ttl(dep_id: str, logger: StructuredLogger):
    """
    Extend the TTL of an existing deployment to always be 5 minutes from the current time.
    """
    step_logger = logger.with_step("extend_ttl")
    try:
        new_expiration_time = int(time.time()) + TTL_EXTENSION_SECONDS
        human_readable_expiration = datetime.utcfromtimestamp(new_expiration_time).strftime('%Y-%m-%d %H:%M:%S UTC')

        update_expression = "SET #ttl = :ttl, expiration = :expiration, updated_at = :timestamp"
        expression_values = {
            ":ttl": {"N": str(new_expiration_time)},
            ":expiration": {"S": human_readable_expiration},
            ":timestamp": {"N": str(int(time.time()))}
        }

        expression_names = {
            "#ttl": "ttl"
        }

        dynamodb.update_item(
            TableName=DEPLOYMENT_TABLE,
            Key={"dep_id": {"S": dep_id}},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_names,
            ExpressionAttributeValues=expression_values
        )
        step_logger.info("TTL extended successfully", dep_id=dep_id, new_expiration=human_readable_expiration)
        return f"TTL updated to 5 minutes from now for deployment {dep_id}"
    except Exception as e:
        step_logger.error("Failed to extend TTL", dep_id=dep_id, error=str(e))
        raise TransientError(f"Failed to update TTL: {e}") from e


def _resolve_tenant_url(lab_id: str, logger: StructuredLogger):
    """Best-effort lookup of tenant_url from lab config + SSM.

    Returns the tenant URL string, or None on any failure.
    """
    step_logger = logger.with_step("resolve_tenant_url")
    try:
        if not LAB_CONFIGURATION_TABLE:
            step_logger.warn("LAB_CONFIGURATION_TABLE not set, skipping tenant_url lookup")
            return None

        response = dynamodb.get_item(
            TableName=LAB_CONFIGURATION_TABLE,
            Key={"lab_id": {"S": lab_id}}
        )
        item = response.get("Item")
        if not item:
            step_logger.warn("Lab config not found, skipping tenant_url lookup", lab_id=lab_id)
            return None

        ssm_base_path = item.get("ssm_base_path", {}).get("S")
        if not ssm_base_path:
            step_logger.warn("ssm_base_path missing from lab config", lab_id=lab_id)
            return None

        params = get_ssm_parameters([f"{ssm_base_path}/tenant-url"])
        tenant_url = params.get("tenant-url")
        step_logger.info("Resolved tenant_url", lab_id=lab_id, tenant_url=tenant_url)
        return tenant_url
    except Exception as e:
        step_logger.warn("Failed to resolve tenant_url, proceeding without it", lab_id=lab_id, error=str(e))
        return None


def insert_into_dynamodb(message: dict, logger: StructuredLogger):
    """
    Insert the processed message into DynamoDB as a new deployment with a TTL of 5 minutes from now.
    """
    step_logger = logger.with_step("insert_deployment")
    expiration_time = int(time.time()) + TTL_EXTENSION_SECONDS

    item = {
        "dep_id": {"S": message["dep_id"]},
        "lab_id": {"S": message["lab_id"]},
        "email": {"S": message["email"]},
        "petname": {"S": message["petname"]},
        "deployment_status": {"S": "STARTING"},
        "created_at": {"S": datetime.utcnow().isoformat()},
        "ttl": {"N": str(expiration_time)}
    }

    tenant_url = _resolve_tenant_url(message["lab_id"], logger)
    if tenant_url:
        item["tenant_url"] = {"S": tenant_url}

    try:
        step_logger.info("Inserting new deployment", dep_id=message["dep_id"])
        dynamodb.put_item(
            TableName=DEPLOYMENT_TABLE,
            Item=item
        )
        step_logger.info("Deployment inserted successfully", dep_id=message["dep_id"])
        return f"Inserted new deployment {message['dep_id']} into {DEPLOYMENT_TABLE}."
    except Exception as e:
        step_logger.error("Failed to insert deployment", dep_id=message["dep_id"], error=str(e))
        raise TransientError(f"Failed to insert into DynamoDB: {e}") from e


@lambda_handler
def handler(event: dict, context, logger: StructuredLogger) -> dict:
    """
    Process SQS event and insert/update records in DynamoDB.
    """
    step_logger = logger.with_step("process_records")

    for record in event["Records"]:
        message_body = json.loads(record["body"])
        validate_message(message_body, logger)

        dep_id = message_body["dep_id"]

        existing_item = check_existing_deployment(dep_id, logger)

        if existing_item:
            result = extend_ttl(dep_id, logger)
        else:
            result = insert_into_dynamodb(message_body, logger)

        step_logger.info("Record processed", dep_id=dep_id, result=result)

    return "Processed SQS messages successfully"


if __name__ == "__main__":
    # Simulated SQS event for local testing
    test_event = {
        "Records": [
            {
                "body": json.dumps({
                    "dep_id": "deploy-001",
                    "lab_id": "lab-123",
                    "email": "test.user@example.com",
                    "petname": "fluffy-panda"
                })
            }
        ]
    }

    class MockContext:
        function_name = "udf_dispatch"

    handler(test_event, MockContext())
