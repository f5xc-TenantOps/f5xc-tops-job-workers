"""
UDF Lab Worker & Cleanup - Handles both record INSERT and REMOVE events from DynamoDB Streams.
- On INSERT: Creates a namespace and user in an F5 XC tenant, updating the state.
- On REMOVE: Removes the user and namespace when the TTL expires, updating the state.
"""
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
LAB_SETTINGS_TABLE = os.getenv("LAB_SETTINGS_TABLE")
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
        expiration_timestamp = int(time.time()) + 300  # Extend TTL by 5 minutes

        update_expression = "SET #s = :status, ttl = :ttl, updated_at = :timestamp"
        expression_values = {
            ":status": {"S": status},
            ":timestamp": {"N": str(int(time.time()))},
            ":ttl": {"N": str(expiration_timestamp)}
        }

        if details:
            update_expression += ", details = :details"
            expression_values[":details"] = {"S": details}

        dynamodb.update_item(
            TableName=DEPLOYMENT_STATE_TABLE,
            Key={"depID": {"S": depID}},  # ✅ Updated key name
            UpdateExpression=update_expression,
            ExpressionAttributeNames={"#s": step},
            ExpressionAttributeValues=expression_values
        )
    except Exception as e:
        raise RuntimeError(f"Failed to update deployment state in DynamoDB: {e}") from e


def get_lab_info(lab_id: str, table_name: str) -> dict:
    """Fetch lab information from DynamoDB using the lab ID."""
    try:
        response = dynamodb.get_item(
            TableName=table_name,
            Key={"labID": {"S": lab_id}}
        )
        if "Item" not in response:
            raise RuntimeError(f"Lab ID '{lab_id}' not found in DynamoDB.")

        item = response["Item"]

        required_fields = ["ssm_base_path", "group_names", "namespace_roles", "user_ns"]
        missing_fields = [field for field in required_fields if field not in item]
        if missing_fields:
            raise RuntimeError(f"Missing required fields in lab info: {', '.join(missing_fields)}")

        lab_info = {
            "ssm_base_path": item["ssm_base_path"]["S"],
            "group_names": [g["S"] for g in item["group_names"]["L"]],
            "namespace_roles": [{"namespace": role["M"]["namespace"]["S"], "role": role["M"]["role"]["S"]} for role in item["namespace_roles"]["L"]],
            "user_ns": item["user_ns"]["BOOL"]
        }

        lab_info["pre_lambda"] = item.get("pre_lambda", {}).get("S", None)

        return lab_info
    except Exception as e:
        raise RuntimeError(f"Failed to fetch lab info from DynamoDB: {e}") from e


def process_insert(record: dict):
    """Handle a new record INSERT event from the DynamoDB stream."""
    try:
        new_image = record["dynamodb"]["NewImage"]

        depID = new_image["depID"]["S"]
        labID = new_image["labID"]["S"]
        email = new_image["email"]["S"]
        petname = new_image["petname"]["S"]

        update_deployment_state(depID, "deployment_status", "IN_PROGRESS", "Starting deployment")

        if not CREATE_NAMESPACE_LAMBDA or not CREATE_USER_LAMBDA or not LAB_SETTINGS_TABLE:
            raise RuntimeError("Missing required environment variables.")

        lab_info = get_lab_info(labID, LAB_SETTINGS_TABLE)

        ssm_base_path = lab_info["ssm_base_path"]
        group_names = lab_info["group_names"]
        namespace_roles = lab_info["namespace_roles"]
        user_ns = lab_info["user_ns"]
        pre_lambda = lab_info.get("pre_lambda")

        if user_ns:
            namespace_payload = {
                "ssm_base_path": ssm_base_path,
                "namespace_name": petname,
                "description": f"Namespace for {depID}"
            }

            update_deployment_state(depID, "create_namespace", "IN_PROGRESS", "Creating namespace")
            namespace_response = invoke_lambda(CREATE_NAMESPACE_LAMBDA, namespace_payload)
            if namespace_response.get("statusCode") != 200:
                update_deployment_state(depID, "create_namespace", "FAILED", namespace_response.get("body"))
                raise RuntimeError(f"Failed to create namespace: {namespace_response.get('body')}")

            update_deployment_state(depID, "create_namespace", "SUCCESS", namespace_response.get("body"))
            namespace_roles.append({"namespace": petname, "role": "ves-io-admin"})

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
        if user_response.get("statusCode") != 200:
            update_deployment_state(depID, "create_user", "FAILED", user_response.get("body"))
            raise RuntimeError(f"Failed to create user: {user_response.get('body')}")

        update_deployment_state(depID, "create_user", "SUCCESS", user_response.get("body"))

        if pre_lambda:
            update_deployment_state(depID, "pre_lambda", "IN_PROGRESS", "Executing pre-lambda")
            pre_lambda_payload = {"ssm_base_path": ssm_base_path, "namespace_name": petname}
            invoke_lambda(pre_lambda, pre_lambda_payload)
            update_deployment_state(depID, "pre_lambda", "SUCCESS", "Pre-lambda executed successfully")

    except Exception as e:
        update_deployment_state(depID, "deployment_status", "FAILED", str(e))
        print(f"Error processing INSERT record: {e}")
        raise


def process_remove(record: dict):
    """Handle a record REMOVAL event from the DynamoDB stream (TTL expiration)."""
    try:
        depID = record["dynamodb"]["Keys"]["depID"]["S"]    
        update_deployment_state(depID, "cleanup_status", "IN_PROGRESS", "Starting cleanup")

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