"""Clean expired deployments from DynamoDB."""

import os
import time

import boto3

from shared.decorators import lambda_handler
from shared.errors import PermanentError, TransientError
from shared.logging import StructuredLogger

# AWS Clients
dynamodb = boto3.client("dynamodb")

# Environment Variables
DEPLOYMENT_TABLE = os.getenv("DEPLOYMENT_STATE_TABLE")

if not DEPLOYMENT_TABLE:
    raise ValueError("DEPLOYMENT_STATE_TABLE environment variable is not set.")


def get_expired_entries(logger: StructuredLogger) -> list:
    """Scan the DynamoDB table and retrieve entries where the TTL has expired."""
    step_logger = logger.with_step("get_expired_entries")
    current_time = int(time.time())

    try:
        response = dynamodb.scan(
            TableName=DEPLOYMENT_TABLE,
            FilterExpression="#ttl_attr < :now",
            ExpressionAttributeNames={"#ttl_attr": "ttl"},
            ExpressionAttributeValues={":now": {"N": str(current_time)}},
        )
        items = response.get("Items", [])
        step_logger.info("Scanned for expired entries", count=len(items))
        return items
    except Exception as e:
        step_logger.error("Failed to scan for expired entries", error=str(e))
        raise TransientError(f"Error scanning for expired entries: {e}") from e


def delete_expired_entries(logger: StructuredLogger) -> str:
    """Find and delete all expired entries from the DynamoDB table."""
    step_logger = logger.with_step("delete_expired_entries")
    expired_items = get_expired_entries(logger)

    if not expired_items:
        step_logger.info("No expired entries found")
        return "No expired entries found."

    deleted_count = 0
    for item in expired_items:
        dep_id = item["dep_id"]["S"]
        try:
            dynamodb.delete_item(
                TableName=DEPLOYMENT_TABLE, Key={"dep_id": item["dep_id"]}
            )
            deleted_count += 1
            step_logger.info("Deleted expired entry", dep_id=dep_id)
        except Exception as e:
            step_logger.error("Failed to delete expired entry", dep_id=dep_id, error=str(e))

    result = f"Deleted {deleted_count} expired entries from {DEPLOYMENT_TABLE}."
    step_logger.info("Cleanup complete", deleted_count=deleted_count)
    return result


@lambda_handler
def handler(event, context, logger: StructuredLogger):
    """AWS Lambda entry point for cleaning expired deployments."""
    result = delete_expired_entries(logger)
    return result


if __name__ == "__main__":
    # Local testing
    class MockContext:
        function_name = "udf_clean"

    handler({}, MockContext())
