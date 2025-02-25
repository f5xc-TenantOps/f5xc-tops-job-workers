import os
import time
import boto3

# AWS Clients
dynamodb = boto3.client("dynamodb")

# Environment Variables
DEPLOYMENT_TABLE = os.getenv("DEPLOYMENT_STATE_TABLE")

if not DEPLOYMENT_TABLE:
    raise ValueError("DEPLOYMENT_STATE_TABLE environment variable is not set.")


def get_expired_entries():
    """
    Scan the DynamoDB table and retrieve entries where the TTL has expired.
    """
    current_time = int(time.time())

    try:
        response = dynamodb.scan(
            TableName=DEPLOYMENT_TABLE,
            FilterExpression="ttl < :now",
            ExpressionAttributeValues={":now": {"N": str(current_time)}}
        )

        return response.get("Items", [])
    except Exception as e:
        raise RuntimeError(f"Error scanning for expired entries: {e}") from e


def delete_expired_entries():
    """
    Find and delete all expired entries from the DynamoDB table.
    """
    expired_items = get_expired_entries()
    
    if not expired_items:
        return "No expired entries found."

    deleted_count = 0
    for item in expired_items:
        try:
            dynamodb.delete_item(
                TableName=DEPLOYMENT_TABLE,
                Key={"dep_id": item["dep_id"]}
            )
            deleted_count += 1
        except Exception as e:
            print(f"Failed to delete expired entry {item['dep_id']['S']}: {e}")

    return f"Deleted {deleted_count} expired entries from {DEPLOYMENT_TABLE}."


def lambda_handler(event, context):
    """
    AWS Lambda entry point for cleaning expired deployments.
    """
    try:
        result = delete_expired_entries()
        print(result)
        return {"statusCode": 200, "body": result}
    except Exception as e:
        print(f"Error: {e}")
        return {"statusCode": 500, "body": f"Error deleting expired entries: {e}"}


if __name__ == "__main__":
    # Local testing
    print(delete_expired_entries())