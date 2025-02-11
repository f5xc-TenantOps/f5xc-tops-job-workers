import json
import os
import time
from datetime import datetime
import boto3

lambda_client = boto3.client("lambda")
dynamodb = boto3.client("dynamodb")

# ✅ Updated to match Terraform-provided environment variables
DEPLOYMENT_STATE_TABLE = os.getenv("DEPLOYMENT_STATE_TABLE")
LAB_CONFIGURATION_TABLE = os.getenv("LAB_CONFIGURATION_TABLE")
USER_CREATE_LAMBDA = os.getenv("USER_CREATE_LAMBDA_FUNCTION")
USER_REMOVE_LAMBDA = os.getenv("USER_REMOVE_LAMBDA_FUNCTION")
NS_CREATE_LAMBDA = os.getenv("NS_CREATE_LAMBDA_FUNCTION")
NS_REMOVE_LAMBDA = os.getenv("NS_REMOVE_LAMBDA_FUNCTION")


def invoke_lambda(function_name: str, payload: dict) -> dict:
    """Invoke another Lambda function synchronously."""
    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload)
        )
        return json.loads(response["Payload"].read())
    except Exception as e:
        raise RuntimeError(f"Failed to invoke Lambda '{function_name}': {e}") from e


def get_lab_info(labID: str) -> dict:
    """Fetch lab information from DynamoDB using the lab ID."""
    try:
        response = dynamodb.get_item(
            TableName=LAB_CONFIGURATION_TABLE,
            Key={"lab_id": {"S": labID}}
        )

        if "Item" not in response:
            raise RuntimeError(f"Lab ID '{labID}' not found in DynamoDB.")

        item = response["Item"]

        required_fields = ["ssm_base_path", "group_names", "namespace_roles", "user_ns"]
        missing_fields = [field for field in required_fields if field not in item]
        if missing_fields:
            raise RuntimeError(f"Missing required fields in lab info: {', '.join(missing_fields)}")

        lab_info = {
            "ssm_base_path": item["ssm_base_path"]["S"],
            "group_names": [g["S"] for g in item["group_names"]["L"]],
            "namespace_roles": [{"namespace": role["M"]["namespace"]["S"], "role": role["M"]["role"]["S"]} for role in item["namespace_roles"]["L"]],
            "user_ns": item["user_ns"]["BOOL"],
            "pre_lambda": item.get("pre_lambda", {}).get("S", None),
            "post_lambda": item.get("post_lambda", {}).get("S", None)
        }

        return lab_info
    except Exception as e:
        raise RuntimeError(f"Failed to fetch lab info from DynamoDB: {e}") from e


def update_deployment_state(depID: str, updates: dict):
    """Update multiple fields in the deployment state in DynamoDB."""
    try:
        update_expression = "SET " + ", ".join([f"#{k} = :{k}" for k in updates.keys()])
        expression_values = {f":{k}": {"S" if isinstance(v, str) else "BOOL": v} for k, v in updates.items()}
        expression_names = {f"#{k}": k for k in updates.keys()}

        dynamodb.update_item(
            TableName=DEPLOYMENT_STATE_TABLE,
            Key={"depID": {"S": depID}},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_names,
            ExpressionAttributeValues=expression_values
        )
    except Exception as e:
        raise RuntimeError(f"Failed to update deployment state in DynamoDB: {e}") from e


def process_insert(record: dict):
    """Handle a new record INSERT event from the DynamoDB stream."""
    try:
        new_image = record["dynamodb"]["NewImage"]

        depID = new_image["depID"]["S"]
        labID = new_image["labID"]["S"]
        email = new_image["email"]["S"]
        petname = new_image["petname"]["S"]

        created_namespace = False
        created_user = False

        update_deployment_state(depID, {"deployment_status": "IN_PROGRESS"})

        if not NS_CREATE_LAMBDA or not USER_CREATE_LAMBDA or not LAB_CONFIGURATION_TABLE:
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

            update_deployment_state(depID, {"create_namespace": "IN_PROGRESS"})
            namespace_response = invoke_lambda(NS_CREATE_LAMBDA, namespace_payload)
            if namespace_response.get("statusCode") == 200:
                update_deployment_state(depID, {"create_namespace": "SUCCESS"})
                namespace_roles.append({"namespace": petname, "role": "ves-io-admin"})
                created_namespace = True
            else:
                update_deployment_state(depID, {"create_namespace": "FAILED"})

        # Step 2: Create User
        user_payload = {
            "ssm_base_path": ssm_base_path,
            "first_name": email.split("@")[0],
            "last_name": "User",
            "email": email,
            "group_names": group_names,
            "namespace_roles": namespace_roles
        }

        update_deployment_state(depID, {"create_user": "IN_PROGRESS"})
        user_response = invoke_lambda(USER_CREATE_LAMBDA, user_payload)
        if user_response.get("statusCode") == 200:
            update_deployment_state(depID, {"create_user": "SUCCESS"})
            created_user = True
        else:
            update_deployment_state(depID, {"create_user": "FAILED"})

        # ✅ Step 3: Execute Pre-Lambda (if defined)
        if pre_lambda:
            update_deployment_state(depID, {"pre_lambda": "IN_PROGRESS"})
            pre_lambda_payload = {
                "ssm_base_path": ssm_base_path,
                "petname": petname,
                "email": email
            }
            pre_lambda_response = invoke_lambda(pre_lambda, pre_lambda_payload)

            if pre_lambda_response.get("statusCode") == 200:
                update_deployment_state(depID, {"pre_lambda": "SUCCESS"})
            else:
                update_deployment_state(depID, {"pre_lambda": "FAILED"})

        # ✅ Store created flags in DynamoDB
        update_deployment_state(depID, {
            "created_namespace": created_namespace,
            "created_user": created_user
        })

    except Exception as e:
        update_deployment_state(depID, {"deployment_status": "FAILED"})
        print(f"Error processing INSERT record: {e}")
        raise


def lambda_handler(event, context):
    """AWS Lambda entry point for handling DynamoDB stream events."""
    for record in event["Records"]:
        if record["eventName"] == "INSERT":
            process_insert(record)