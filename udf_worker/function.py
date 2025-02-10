import json
import os
import time
from datetime import datetime
import boto3

lambda_client = boto3.client("lambda")
dynamodb = boto3.client("dynamodb")

# Retrieve Lambda function names from environment variables
CREATE_NAMESPACE_LAMBDA = os.getenv("CREATE_NAMESPACE_LAMBDA_ARN")
CREATE_USER_LAMBDA = os.getenv("CREATE_USER_LAMBDA_ARN")
REMOVE_NAMESPACE_LAMBDA = os.getenv("REMOVE_NAMESPACE_LAMBDA_ARN")
REMOVE_USER_LAMBDA = os.getenv("REMOVE_USER_LAMBDA_ARN")
LAB_CONFIGURATION_TABLE = os.getenv("LAB_CONFIGURATION_TABLE")
DEPLOYMENT_STATE_TABLE = os.getenv("DEPLOYMENT_STATE_TABLE")


def invoke_lambda(function_name: str, payload: dict) -> dict:
    """Invoke another Lambda function synchronously."""
    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload)
        )
        return json.loads(response['Payload'].read())
    except Exception as e:
        raise RuntimeError(f"Failed to invoke Lambda '{function_name}': {e}") from e


def update_deployment_state(depID: str, step: str, status: str, details: str = None):
    """Update the state of the deployment in DynamoDB."""
    try:
        update_expression = "SET #s = :status, updated_at = :timestamp"
        expression_values = {
            ":status": {"S": status},
            ":timestamp": {"N": str(int(time.time()))}
        }

        if details:
            update_expression += ", details = :details"
            expression_values[":details"] = {"S": details}

        dynamodb.update_item(
            TableName=DEPLOYMENT_STATE_TABLE,
            Key={"depID": {"S": depID}},
            UpdateExpression=update_expression,
            ExpressionAttributeNames={"#s": step},
            ExpressionAttributeValues=expression_values
        )
    except Exception as e:
        raise RuntimeError(f"Failed to update deployment state in DynamoDB: {e}") from e


def process_insert(record: dict):
    """Handle a new record INSERT event from the DynamoDB stream."""
    try:
        new_image = record["dynamodb"]["NewImage"]

        depID = new_image["depID"]["S"]  # ✅ Updated key name
        labID = new_image["labID"]["S"]
        email = new_image["email"]["S"]
        petname = new_image["petname"]["S"]

        created_namespace = False
        created_user = False

        update_deployment_state(depID, "deployment_status", "IN_PROGRESS", "Starting deployment")

        # Check for required environment variables
        if not CREATE_NAMESPACE_LAMBDA or not CREATE_USER_LAMBDA or not LAB_CONFIGURATION_TABLE:
            raise RuntimeError("Missing required environment variables.")

        # Fetch lab settings
        lab_info = get_lab_info(labID)

        ssm_base_path = lab_info["ssm_base_path"]
        group_names = lab_info["group_names"]
        namespace_roles = lab_info["namespace_roles"]
        user_ns = lab_info["user_ns"]
        pre_lambda = lab_info.get("pre_lambda")

        # Step 1: Create Namespace (if applicable)
        if user_ns:
            namespace_payload = {
                "ssm_base_path": ssm_base_path,
                "namespace_name": petname,
                "description": f"Namespace for {depID}"
            }

            update_deployment_state(depID, "create_namespace", "IN_PROGRESS", "Creating namespace")
            namespace_response = invoke_lambda(CREATE_NAMESPACE_LAMBDA, namespace_payload)
            if namespace_response.get("statusCode") == 200:
                update_deployment_state(depID, "create_namespace", "SUCCESS", namespace_response.get("body"))
                namespace_roles.append({"namespace": petname, "role": "ves-io-admin"})
                created_namespace = True
            else:
                update_deployment_state(depID, "create_namespace", "FAILED", namespace_response.get("body"))
                print(f"Namespace already exists or failed: {namespace_response.get('body')}")

        # Step 2: Create User
        user_payload = {
            "ssm_base_path": ssm_base_path,
            "first_name": email.split("@")[0],
            "last_name": "User",
            "email": email,
            "group_names": group_names,
            "namespace_roles": namespace_roles
        }

        update_deployment_state(depID, "create_user", "IN_PROGRESS", "Creating user")
        user_response = invoke_lambda(CREATE_USER_LAMBDA, user_payload)
        if user_response.get("statusCode") == 200:
            update_deployment_state(depID, "create_user", "SUCCESS", user_response.get("body"))
            created_user = True
        else:
            update_deployment_state(depID, "create_user", "FAILED", user_response.get("body"))
            print(f"User already exists or failed: {user_response.get('body')}")

        # Store flags in deployment state
        update_deployment_state(depID, "created_namespace", str(created_namespace))
        update_deployment_state(depID, "created_user", str(created_user))

    except Exception as e:
        update_deployment_state(depID, "deployment_status", "FAILED", str(e))
        print(f"Error processing INSERT record: {e}")
        raise


def process_remove(record: dict):
    """Handle a record REMOVAL event from the DynamoDB stream (TTL expiration)."""
    try:
        depID = record["dynamodb"]["Keys"]["depID"]["S"]  # ✅ Updated key name
        item = dynamodb.get_item(
            TableName=DEPLOYMENT_STATE_TABLE,
            Key={"depID": {"S": depID}}
        ).get("Item", {})

        created_namespace = item.get("created_namespace", {}).get("S") == "True"
        created_user = item.get("created_user", {}).get("S") == "True"

        if created_user:
            update_deployment_state(depID, "cleanup_status", "IN_PROGRESS", "Removing user")
            user_payload = {"ssm_base_path": item["ssm_base_path"]["S"], "email": item["email"]["S"]}
            invoke_lambda(REMOVE_USER_LAMBDA, user_payload)

        if created_namespace:
            update_deployment_state(depID, "cleanup_status", "IN_PROGRESS", "Removing namespace")
            namespace_payload = {"ssm_base_path": item["ssm_base_path"]["S"], "namespace_name": item["petname"]["S"]}
            invoke_lambda(REMOVE_NAMESPACE_LAMBDA, namespace_payload)

        update_deployment_state(depID, "cleanup_status", "COMPLETED", "Cleanup completed successfully")

    except Exception as e:
        update_deployment_state(depID, "cleanup_status", "FAILED", str(e))
        print(f"Error processing REMOVE record: {e}")
        raise


def lambda_handler(event, context):
    """AWS Lambda entry point for handling DynamoDB stream events."""
    for record in event["Records"]:
        if record["eventName"] == "INSERT":
            process_insert(record)
        elif record["eventName"] == "REMOVE":
            process_remove(record)