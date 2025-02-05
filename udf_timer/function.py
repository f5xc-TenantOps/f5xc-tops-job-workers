import json
import os
import time
from datetime import datetime, timedelta
import boto3

# AWS Clients
dynamodb = boto3.client("dynamodb")

# Environment Variables
DEPLOYMENT_TABLE = os.getenv("DEPLOYMENT_TABLE_NAME")
TTL_EXTENSION_SECONDS = 300  # Always set TTL to 5 minutes from now


def validate_message(message: dict):
    """
    Validate that required fields exist in the SQS message.
    """
    required_fields = ["deployment_id", "lab_id", "email", "petname"]
    missing_fields = [field for field in required_fields if field not in message]

    if missing_fields:
        raise ValueError(f"Missing required fields in message: {', '.join(missing_fields)}")


def check_existing_deployment(deployment_id: str):
    """
    Check if a deployment_id already exists in DynamoDB.
    """
    try:
        response = dynamodb.get_item(
            TableName=DEPLOYMENT_TABLE,
            Key={"deployment_id": {"S": deployment_id}}
        )
        return response.get("Item")
    except Exception as e:
        raise RuntimeError(f"Error checking existing deployment: {e}") from e


def extend_ttl(deployment_id: str):
    """
    Extend the TTL of an existing deployment_id to always be 5 minutes from the current time.
    """
    try:
        new_expiration_time = int(time.time()) + TTL_EXTENSION_SECONDS  # Always set TTL to 5 minutes from now
        human_readable_expiration = datetime.utcfromtimestamp(new_expiration_time).strftime('%Y-%m-%d %H:%M:%S UTC')

        update_expression = "SET ttl = :ttl, expiration = :expiration, updated_at = :timestamp"
        expression_values = {
            ":ttl": {"N": str(new_expiration_time)},
            ":expiration": {"S": human_readable_expiration},
            ":timestamp": {"N": str(int(time.time()))}
        }

        dynamodb.update_item(
            TableName=DEPLOYMENT_TABLE,
            Key={"deployment_id": {"S": deployment_id}},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_values
        )
        return f"TTL updated to 5 minutes from now for deployment_id {deployment_id}"
    except Exception as e:
        raise RuntimeError(f"Failed to update TTL: {e}") from e


def insert_into_dynamodb(message: dict):
    """
    Insert the processed message into DynamoDB as a new deployment with a TTL of 5 minutes from now.
    """
    expiration_time = int(time.time()) + TTL_EXTENSION_SECONDS  # Always set to 5 minutes from now

    item = {
        "deployment_id": {"S": message["deployment_id"]},
        "lab_id": {"S": message["lab_id"]},
        "email": {"S": message["email"]},
        "petname": {"S": message["petname"]},
        "status": {"S": "PENDING"},
        "created_at": {"S": datetime.utcnow().isoformat()},
        "ttl": {"N": str(expiration_time)}
    }

    try:
        dynamodb.put_item(
            TableName=DEPLOYMENT_TABLE,
            Item=item
        )
        return f"Inserted new deployment_id {message['deployment_id']} into {DEPLOYMENT_TABLE}."
    except Exception as e:
        raise RuntimeError(f"Failed to insert into DynamoDB: {e}") from e


def main(event: dict):
    """
    Process SQS event and insert/update records in DynamoDB.
    """
    try:
        for record in event["Records"]:
            message_body = json.loads(record["body"])  # Read SQS message
            validate_message(message_body)

            deployment_id = message_body["deployment_id"]

            # Check if the deployment already exists
            existing_item = check_existing_deployment(deployment_id)

            if existing_item:
                # Always set TTL to 5 minutes from now
                result = extend_ttl(deployment_id)
            else:
                # Insert new record with a TTL of 5 minutes
                result = insert_into_dynamodb(message_body)

            print(result)

        return {"statusCode": 200, "body": "Processed SQS messages successfully"}

    except Exception as e:
        print(f"Error: {e}")
        return {"statusCode": 500, "body": f"Error processing SQS messages: {e}"}


def lambda_handler(event, context):
    """
    AWS Lambda entry point.
    """
    return main(event)


if __name__ == "__main__":
    # Simulated SQS event for local testing
    test_event = {
        "Records": [
            {
                "body": json.dumps({
                    "deployment_id": "deploy-001",
                    "lab_id": "lab-123",
                    "email": "test.user@example.com",
                    "namespace_name": "test-namespace"
                })
            }
        ]
    }
    main(test_event)