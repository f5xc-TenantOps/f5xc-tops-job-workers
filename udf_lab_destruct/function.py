import json
import os
import time
from datetime import datetime
import boto3

lambda_client = boto3.client("lambda")
dynamodb = boto3.client("dynamodb")

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


def get_lab_info(lab_id: str) -> dict:
    """Fetch lab information from DynamoDB using the lab ID."""
    try:
        response = dynamodb.get_item(
            TableName=LAB_CONFIGURATION_TABLE,
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
            "user_ns": item["user_ns"]["BOOL"],
            "pre_lambda": item.get("pre_lambda", {}).get("S", None),
            "post_lambda": item.get("post_lambda", {}).get("S", None)
        }

        return lab_info
    except Exception as e:
        raise RuntimeError(f"Failed to fetch lab info from DynamoDB: {e}") from e

def get_parameters(parameters: list, region_name: str = "us-east-1") -> dict:
    """
    Fetch parameters from AWS Parameter Store.
    """
    try:
        aws = boto3.session.Session()
        ssm = aws.client("ssm", region_name=region_name)
        response = ssm.get_parameters(Names=parameters, WithDecryption=True)
        return {param["Name"].split("/")[-1]: param["Value"] for param in response["Parameters"]}
    except Exception as e:
        raise RuntimeError(f"Failed to fetch parameters: {e}") from e
    
def update_deployment_state(dep_id: str, updates: dict):
    """Update multiple fields in the deployment state in DynamoDB."""
    try:
        update_expression = "SET " + ", ".join([f"#{k} = :{k}" for k in updates.keys()])
        expression_values = {
            f":{k}": {("S" if isinstance(v, str) else "BOOL" if isinstance(v, bool) else "N"): str(v)}
            for k, v in updates.items()
        }
        expression_names = {f"#{k}": k for k in updates.keys()}

        dynamodb.update_item(
            TableName=DEPLOYMENT_STATE_TABLE,
            Key={"dep_id": {"S": dep_id}},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_names,
            ExpressionAttributeValues=expression_values
        )
    except Exception as e:
        raise RuntimeError(f"Failed to update deployment state in DynamoDB: {e}") from e

def check_existing_user_in_tenant(email: str, tenant_url: str) -> bool:
    """
    Check if another active deployment exists for the same user in the same tenant.
    Returns True if another active record is found.
    """
    try:
        response = dynamodb.scan(
            TableName=DEPLOYMENT_STATE_TABLE,
            FilterExpression="email = :email AND tenant_url = :tenant",
            ExpressionAttributeValues={
                ":email": {"S": email},
                ":tenant": {"S": tenant_url}
            }
        )
        return bool(response.get("Items")) 
    except Exception as e:
        raise RuntimeError(f"Error checking existing deployments: {e}") from e

def process_remove(record: dict):
    """Handle a record REMOVE event from the DynamoDB stream."""
    try:
        old_image = record["dynamodb"]["OldImage"]

        dep_id = old_image["dep_id"]["S"]
        lab_id = old_image["lab_id"]["S"]
        petname = old_image["petname"]["S"]
        email = old_image["email"]["S"]
        tenant_url = old_image.get("tenant_url", {}).get("S")
        create_namespace = old_image.get("create_namespace", {}).get("S")
        create_user = old_image.get("create_user", {}).get("S")

        # Fetch lab settings
        lab_info = get_lab_info(lab_id)
        ssm_base_path = lab_info["ssm_base_path"]
        post_lambda = lab_info.get("post_lambda")

        # ✅ Check if another deployment exists for this user in the same tenant
        if check_existing_user_in_tenant(email, tenant_url):
            print(f"Skipping user removal: Another active deployment exists for {email} in {tenant_url}")
        else:
            # Step 1: Remove User if it was successfully created
            if create_user == "SUCCESS":
                if not USER_REMOVE_LAMBDA:
                    raise RuntimeError("USER_REMOVE_LAMBDA environment variable is missing.")

                user_payload = {
                    "ssm_base_path": ssm_base_path,
                    "email": email
                }

                user_remove_response = invoke_lambda(USER_REMOVE_LAMBDA, user_payload)
                if user_remove_response.get("statusCode") != 200:
                    print(f"Warning: User removal failed for {email}")

        # Step 2: Remove Namespace if it was successfully created
        if create_namespace == "SUCCESS":
            if not NS_REMOVE_LAMBDA:
                raise RuntimeError("NS_REMOVE_LAMBDA environment variable is missing.")

            namespace_payload = {
                "ssm_base_path": ssm_base_path,
                "namespace_name": petname
            }

            ns_remove_response = invoke_lambda(NS_REMOVE_LAMBDA, namespace_payload)
            if ns_remove_response.get("statusCode") != 200:
                print(f"Warning: Namespace removal failed for {petname}")

        # Step 3: Execute Post-Lambda (if defined)
        if post_lambda:
            post_lambda_payload = {
                "ssm_base_path": ssm_base_path,
                "petname": petname,
                "email": email
            }

            post_lambda_response = invoke_lambda(post_lambda, post_lambda_payload)
            if post_lambda_response.get("statusCode") != 200:
                print(f"Warning: Post-Lambda execution failed for {dep_id}")

    except Exception as e:
        print(f"Error processing REMOVE record: {e}")
        raise

def lambda_handler(event, context):
    """AWS Lambda entry point for handling DynamoDB stream events."""
    for record in event["Records"]:
        if record["eventName"] == "REMOVE":
            process_remove(record)