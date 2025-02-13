import json
import os
import time
from datetime import datetime
import boto3

# AWS Clients
dynamodb = boto3.client("dynamodb")

# Environment Variables
DEPLOYMENT_TABLE = os.getenv("DEPLOYMENT_STATE_TABLE")
TTL_EXTENSION_SECONDS = 300

if not DEPLOYMENT_TABLE:
    raise ValueError("DEPLOYMENT_STATE_TABLE environment variable is not set.")

def validate_message(message: dict):
    """
    Validate that required fields exist in the SQS message.
    """
    required_fields = ["dep_id", "lab_id", "email", "petname"]
    missing_fields = [field for field in required_fields if field not in message]

    if missing_fields:
        raise ValueError(f"Missing required fields in message: {', '.join(missing_fields)}")


def check_existing_deployment(dep_id: str):
    """
    Check if a dep_id (deployment_id) already exists in DynamoDB.
    """
    try:
        response = dynamodb.get_item(
            TableName=DEPLOYMENT_TABLE,
            Key={"dep_id": {"S": dep_id}}
        )
        return response.get("Item")
    except Exception as e:
        raise RuntimeError(f"Error checking existing deployment: {e}") from e


def extend_ttl(dep_id: str):
    """
    Extend the TTL of an existing deployment to always be 5 minutes from the current time.
    """
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
        return f"TTL updated to 5 minutes from now for deployment {dep_id}"
    except Exception as e:
        raise RuntimeError(f"Failed to update TTL: {e}") from e


def insert_into_dynamodb(message: dict):
    """
    Insert the processed message into DynamoDB as a new deployment with a TTL of 5 minutes from now.
    """
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

    try:
        dynamodb.put_item(
            TableName=DEPLOYMENT_TABLE,
            Item=item
        )
        return f"Inserted new deployment {message['dep_id']} into {DEPLOYMENT_TABLE}."
    except Exception as e:
        raise RuntimeError(f"Failed to insert into DynamoDB: {e}") from e


def main(event: dict):
    """
    Process SQS event and insert/update records in DynamoDB.
    """
    try:
        for record in event["Records"]:
            message_body = json.loads(record["body"])
            validate_message(message_body)

            dep_id = message_body["dep_id"]

            existing_item = check_existing_deployment(dep_id)

            if existing_item:
                result = extend_ttl(dep_id)
            else:
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
                    "dep_id": "deploy-001",
                    "lab_id": "lab-123",
                    "email": "test.user@example.com",
                    "petname": "fluffy-panda"
                })
            }
        ]
    }
    main(test_event)