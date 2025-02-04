"""
UDF Lab Worker - Processes an SQS message to create a namespace and a user in an F5 XC tenant,
tracking the state of the deployment with expiration handling.
"""
import json
import time
from datetime import datetime, timedelta
import boto3

lambda_client = boto3.client("lambda")
dynamodb = boto3.client("dynamodb")


def validate_payload(payload: dict):
    """
    Validate the payload for required fields.
    """
    required_fields = ["deployment_id", "lab_id", "email", "namespace_name"]
    missing_fields = [field for field in required_fields if field not in payload]

    if missing_fields:
        raise RuntimeError(f"Missing required fields in payload: {', '.join(missing_fields)}")


def get_lab_info(lab_id: str, table_name: str = "TenantInfo") -> dict:
    """
    Fetch tenant information from DynamoDB using the lab ID.
    """
    try:
        response = dynamodb.get_item(
            TableName=table_name,
            Key={"lab_id": {"S": lab_id}}
        )
        if "Item" not in response:
            raise RuntimeError(f"Lab ID '{lab_id}' not found in DynamoDB.")

        return {k: list(v.values())[0] for k, v in response["Item"].items()}
    except Exception as e:
        raise RuntimeError(f"Failed to fetch tenant info from DynamoDB: {e}") from e


def update_deployment_state(deployment_id: str, step: str, status: str, details: str = None, table_name: str = "LabDeploymentState"):
    """
    Update the state of the deployment in DynamoDB and extend expiration time.
    """
    try:
        expiration_timestamp = int(time.time()) + 300  # 5 minutes from now
        human_readable_expiration = datetime.utcfromtimestamp(expiration_timestamp).strftime('%Y-%m-%d %H:%M:%S UTC')

        update_expression = "SET #s = :status, expiration = :expiration, ttl = :ttl, updated_at = :timestamp"
        expression_values = {
            ":status": {"S": status},
            ":timestamp": {"N": str(int(time.time()))},
            ":expiration": {"S": human_readable_expiration},
            ":ttl": {"N": str(expiration_timestamp)}  # TTL field for DynamoDB expiration
        }

        if details:
            update_expression += ", details = :details"
            expression_values[":details"] = {"S": details}

        dynamodb.update_item(
            TableName=table_name,
            Key={"deployment_id": {"S": deployment_id}},
            UpdateExpression=update_expression,
            ExpressionAttributeNames={"#s": step},
            ExpressionAttributeValues=expression_values
        )
    except Exception as e:
        raise RuntimeError(f"Failed to update deployment state in DynamoDB: {e}") from e


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


def main(event: dict):
    """
    Main function to process the SQS message and create a namespace and user.
    """
    try:
        message = json.loads(event["Records"][0]["body"])  # Assuming one message per event
        validate_payload(message)

        deployment_id = message["deployment_id"]
        lab_id = message["lab_id"]
        email = message["email"]
        namespace_name = message["namespace_name"]

        # Initialize deployment state or extend expiration
        update_deployment_state(deployment_id, "deployment_status", "IN_PROGRESS", "Starting deployment")

        # Fetch tenant info from DynamoDB
        tenant_info = get_lab_info(lab_id)
        ssm_base_path = tenant_info.get("ssm_base_path")
        if not ssm_base_path:
            raise RuntimeError(f"Missing 'ssm_base_path' in tenant info for lab ID '{lab_id}'.")

        update_deployment_state(deployment_id, "fetch_lab_info", "SUCCESS", "Lab info retrieved")

        # Step 1: Create Namespace
        namespace_payload = {
            "ssm_base_path": ssm_base_path,
            "namespace_name": namespace_name,
            "description": f"Namespace for {lab_id}"
        }
        update_deployment_state(deployment_id, "create_namespace", "IN_PROGRESS", "Creating namespace")

        namespace_response = invoke_lambda("CreateNamespaceLambda", namespace_payload)

        if namespace_response.get("statusCode") != 200:
            update_deployment_state(deployment_id, "create_namespace", "FAILED", namespace_response.get("body"))
            raise RuntimeError(f"Failed to create namespace: {namespace_response.get('body')}")

        update_deployment_state(deployment_id, "create_namespace", "SUCCESS", namespace_response.get("body"))

        # Step 2: Create User
        user_payload = {
            "ssm_base_path": ssm_base_path,
            "first_name": email.split("@")[0],
            "last_name": "User",
            "idm_type": "local",
            "email": email,
            "groups": [],
            "namespace_roles": [{"namespace": namespace_name, "role": "admin"}]
        }
        update_deployment_state(deployment_id, "create_user", "IN_PROGRESS", "Creating user")

        user_response = invoke_lambda("CreateUserLambda", user_payload)

        if user_response.get("statusCode") != 200:
            update_deployment_state(deployment_id, "create_user", "FAILED", user_response.get("body"))
            raise RuntimeError(f"Failed to create user: {user_response.get('body')}")

        update_deployment_state(deployment_id, "create_user", "SUCCESS", user_response.get("body"))

        update_deployment_state(deployment_id, "deployment_status", "COMPLETED", "Deployment completed successfully")

        res = {
            "statusCode": 200,
            "body": {
                "namespace": namespace_response.get("body"),
                "user": user_response.get("body")
            }
        }

    except Exception as e:
        update_deployment_state(deployment_id, "deployment_status", "FAILED", str(e))
        err = {
            "statusCode": 500,
            "body": f"Error: {e}"
        }
        print(err)
        raise RuntimeError(err) from e

    print(res)
    return res


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