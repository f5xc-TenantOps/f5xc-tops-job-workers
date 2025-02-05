"""
Cleanup expired deployments by removing the user and namespace.
Triggered by DynamoDB Streams when TTL expires.
"""
import json
import boto3

lambda_client = boto3.client("lambda")


def invoke_lambda(function_name: str, payload: dict) -> dict:
    """
    Invoke another Lambda function synchronously.
    """
    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload)
        )
        return json.loads(response['Payload'].read())
    except Exception as e:
        raise RuntimeError(f"Failed to invoke Lambda '{function_name}': {e}") from e


def process_expired_record(record: dict):
    """
    Process an expired DynamoDB record and trigger cleanup actions.
    """
    try:
        deployment_id = record["deployment_id"]["S"]
        namespace_name = record["namespace_name"]["S"]
        email = record["email"]["S"]
        ssm_base_path = record["ssm_base_path"]["S"]

        print(f"Processing expired deployment: {deployment_id}")

        # Step 1: Remove User
        user_payload = {
            "ssm_base_path": ssm_base_path,
            "email": email
        }
        user_response = invoke_lambda("RemoveUserLambda", user_payload)

        if user_response.get("statusCode") != 200:
            raise RuntimeError(f"Failed to remove user: {user_response.get('body')}")

        print(f"User removed: {user_response.get('body')}")

        # Step 2: Remove Namespace
        namespace_payload = {
            "ssm_base_path": ssm_base_path,
            "namespace_name": namespace_name
        }
        namespace_response = invoke_lambda("RemoveNamespaceLambda", namespace_payload)

        if namespace_response.get("statusCode") != 200:
            raise RuntimeError(f"Failed to remove namespace: {namespace_response.get('body')}")

        print(f"Namespace removed: {namespace_response.get('body')}")

        return {"statusCode": 200, "body": f"Cleanup completed for deployment {deployment_id}"}

    except Exception as e:
        err = {
            "statusCode": 500,
            "body": f"Error: {e}"
        }
        print(err)
        return err


def lambda_handler(event, context):
    """
    AWS Lambda entry point.
    """
    try:
        for record in event.get("Records", []):
            if record["eventName"] == "REMOVE":  # Only process expired records
                old_image = record["dynamodb"]["OldImage"]
                return process_expired_record(old_image)

        return {"statusCode": 200, "body": "No expired records to process"}

    except Exception as e:
        err = {
            "statusCode": 500,
            "body": f"Error: {e}"
        }
        print(err)
        return err