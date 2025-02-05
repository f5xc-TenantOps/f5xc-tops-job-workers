"""
UDF Lab Worker - Processes a new DynamoDB record to create a namespace and a user in an F5 XC tenant,
tracking the state of the deployment with expiration handling.
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
LAB_SETTINGS_TABLE = os.getenv("LAB_SETTINGS_TABLE")


def validate_record(record: dict):
    """
    Validate that the record contains the required fields.
    """
    required_fields = ["deployment_id", "lab_id", "email", "namespace_name"]
    missing_fields = [field for field in required_fields if field not in record]

    if missing_fields:
        raise RuntimeError(f"Missing required fields in record: {', '.join(missing_fields)}")


def get_lab_info(lab_id: str, table_name: str) -> dict:
    """
    Fetch lab information from DynamoDB using the lab ID.
    """
    try:
        response = dynamodb.get_item(
            TableName=table_name,
            Key={"lab_id": {"S": lab_id}}
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
        raise RuntimeError(f"Failed to fetch tenant info from DynamoDB: {e}") from e


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


def process_record(record: dict):
    """
    Process a single record from the DynamoDB stream.
    """
    try:
        # Extract the new image from the record
        new_image = record["dynamodb"]["NewImage"]

        # Convert DynamoDB JSON to standard JSON
        deployment_id = new_image["deployment_id"]["S"]
        lab_id = new_image["lab_id"]["S"]
        email = new_image["email"]["S"]
        adjective_animal = new_image["namespace_name"]["S"]

        # Validate environment variables
        if not CREATE_NAMESPACE_LAMBDA or not CREATE_USER_LAMBDA or not LAB_SETTINGS_TABLE:
            raise RuntimeError("Missing required environment variables: CREATE_NAMESPACE_LAMBDA_ARN, CREATE_USER_LAMBDA_ARN, or LAB_SETTINGS_TABLE.")

        # Fetch lab settings from DynamoDB
        lab_info = get_lab_info(lab_id, LAB_SETTINGS_TABLE)

        ssm_base_path = lab_info["ssm_base_path"]
        group_names = lab_info["group_names"]
        namespace_roles = lab_info["namespace_roles"]
        user_ns = lab_info["user_ns"]
        pre_lambda = lab_info.get("pre_lambda")

        # Step 1: Conditionally Create Namespace
        if user_ns:
            namespace_payload = {
                "ssm_base_path": ssm_base_path,
                "namespace_name": adjective_animal,
                "description": f"Namespace for {deployment_id}"
            }

            namespace_response = invoke_lambda(CREATE_NAMESPACE_LAMBDA, namespace_payload)
            if namespace_response.get("statusCode") != 200:
                raise RuntimeError(f"Failed to create namespace: {namespace_response.get('body')}")

            # Add the new namespace to namespace_roles
            namespace_roles.append({"namespace": adjective_animal, "role": "admin"})

        # Step 2: Create User
        user_payload = {
            "ssm_base_path": ssm_base_path,
            "first_name": email.split("@")[0],
            "last_name": "User",
            "email": email,
            "group_names": group_names,
            "namespace_roles": namespace_roles
        }

        user_response = invoke_lambda(CREATE_USER_LAMBDA, user_payload)
        if user_response.get("statusCode") != 200:
            raise RuntimeError(f"Failed to create user: {user_response.get('body')}")

        # Step 3: Execute Pre-Lambda
        if pre_lambda:
            pre_lambda_payload = {
                "ssm_base_path": ssm_base_path,
                "namespace_name": adjective_animal
            }
            invoke_lambda(pre_lambda, pre_lambda_payload)

    except Exception as e:
        print(f"Error processing record: {e}")
        raise


def lambda_handler(event, context):
    """
    AWS Lambda entry point for handling DynamoDB stream events.
    """
    for record in event["Records"]:
        # Only process new INSERT records
        if record["eventName"] == "INSERT":
            process_record(record)