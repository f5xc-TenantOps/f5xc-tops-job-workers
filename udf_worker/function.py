import json
import os
import time
from datetime import datetime
import boto3

from shared.logging import StructuredLogger
from shared.errors import PermanentError, TransientError
from shared.decorators import lambda_handler, extract_correlation_id

lambda_client = boto3.client("lambda")
dynamodb = boto3.client("dynamodb")

DEPLOYMENT_STATE_TABLE = os.getenv("DEPLOYMENT_STATE_TABLE")
LAB_CONFIGURATION_TABLE = os.getenv("LAB_CONFIGURATION_TABLE")
USER_CREATE_LAMBDA = os.getenv("USER_CREATE_LAMBDA_FUNCTION")
USER_REMOVE_LAMBDA = os.getenv("USER_REMOVE_LAMBDA_FUNCTION")
NS_CREATE_LAMBDA = os.getenv("NS_CREATE_LAMBDA_FUNCTION")
NS_REMOVE_LAMBDA = os.getenv("NS_REMOVE_LAMBDA_FUNCTION")


def invoke_lambda(function_name: str, payload: dict, logger: StructuredLogger) -> dict:
    """Invoke another Lambda function synchronously."""
    step_logger = logger.with_step("invoke_lambda")
    try:
        step_logger.info("Invoking lambda", function_name=function_name)
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload)
        )
        result = json.loads(response["Payload"].read())
        step_logger.info("Lambda invocation complete", function_name=function_name, status_code=result.get("statusCode"))
        return result
    except Exception as e:
        step_logger.error("Lambda invocation failed", function_name=function_name, error=str(e))
        raise TransientError(f"Failed to invoke Lambda '{function_name}': {e}") from e


def get_lab_info(lab_id: str, logger: StructuredLogger) -> dict:
    """Fetch lab information from DynamoDB using the lab ID."""
    step_logger = logger.with_step("get_lab_info")
    try:
        step_logger.info("Fetching lab info", lab_id=lab_id)
        response = dynamodb.get_item(
            TableName=LAB_CONFIGURATION_TABLE,
            Key={"lab_id": {"S": lab_id}}
        )

        if "Item" not in response:
            step_logger.error("Lab not found", lab_id=lab_id)
            raise PermanentError(f"Lab ID '{lab_id}' not found in DynamoDB.")

        item = response["Item"]

        required_fields = ["ssm_base_path", "group_names", "namespace_roles", "user_ns"]
        missing_fields = [field for field in required_fields if field not in item]
        if missing_fields:
            step_logger.error("Missing required fields in lab info", lab_id=lab_id, missing_fields=missing_fields)
            raise PermanentError(f"Missing required fields in lab info: {', '.join(missing_fields)}")

        lab_info = {
            "ssm_base_path": item["ssm_base_path"]["S"],
            "group_names": [g["S"] for g in item["group_names"]["L"]],
            "namespace_roles": [{"namespace": role["M"]["namespace"]["S"], "role": role["M"]["role"]["S"]} for role in item["namespace_roles"]["L"]],
            "user_ns": item["user_ns"]["BOOL"],
            "pre_lambda": item.get("pre_lambda", {}).get("S", None),
            "post_lambda": item.get("post_lambda", {}).get("S", None)
        }

        step_logger.info("Lab info retrieved successfully", lab_id=lab_id)
        return lab_info
    except (PermanentError, TransientError):
        raise
    except Exception as e:
        step_logger.error("Failed to fetch lab info", lab_id=lab_id, error=str(e))
        raise TransientError(f"Failed to fetch lab info from DynamoDB: {e}") from e


def get_parameters(parameters: list, logger: StructuredLogger, region_name: str = "us-east-1") -> dict:
    """
    Fetch parameters from AWS Parameter Store.
    """
    step_logger = logger.with_step("get_parameters")
    try:
        step_logger.info("Fetching SSM parameters", parameters=parameters)
        aws = boto3.session.Session()
        ssm = aws.client("ssm", region_name=region_name)
        response = ssm.get_parameters(Names=parameters, WithDecryption=True)
        result = {param["Name"].split("/")[-1]: param["Value"] for param in response["Parameters"]}
        step_logger.info("SSM parameters retrieved", count=len(result))
        return result
    except Exception as e:
        step_logger.error("Failed to fetch SSM parameters", error=str(e))
        raise TransientError(f"Failed to fetch parameters: {e}") from e


def update_deployment_state(dep_id: str, updates: dict, logger: StructuredLogger):
    """Update multiple fields in the deployment state in DynamoDB."""
    step_logger = logger.with_step("update_deployment_state")
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
        step_logger.info("Deployment state updated", dep_id=dep_id, updates=list(updates.keys()))
    except Exception as e:
        step_logger.error("Failed to update deployment state", dep_id=dep_id, error=str(e))
        raise TransientError(f"Failed to update deployment state in DynamoDB: {e}") from e


def check_existing_user_in_tenant(email: str, tenant_url: str, logger: StructuredLogger) -> bool:
    """
    Check if another active deployment exists for the same user in the same tenant.
    Returns True if another active record is found.
    """
    step_logger = logger.with_step("check_existing_user")
    try:
        step_logger.info("Checking for existing user in tenant", email=email, tenant_url=tenant_url)
        response = dynamodb.scan(
            TableName=DEPLOYMENT_STATE_TABLE,
            FilterExpression="email = :email AND tenant_url = :tenant",
            ExpressionAttributeValues={
                ":email": {"S": email},
                ":tenant": {"S": tenant_url}
            }
        )
        exists = bool(response.get("Items"))
        step_logger.info("User check complete", email=email, exists=exists)
        return exists
    except Exception as e:
        step_logger.error("Error checking existing deployments", email=email, error=str(e))
        raise TransientError(f"Error checking existing deployments: {e}") from e


def process_insert(record: dict, logger: StructuredLogger):
    """Handle a new record INSERT event from the DynamoDB stream."""
    step_logger = logger.with_step("process_insert")
    dep_id = None
    try:
        new_image = record["dynamodb"]["NewImage"]
        step_logger.info("Processing new record", new_image=str(new_image))

        dep_id = new_image["dep_id"]["S"]
        lab_id = new_image["lab_id"]["S"]
        email = new_image["email"]["S"]
        petname = new_image["petname"]["S"]

        update_deployment_state(dep_id, {"deployment_status": "IN_PROGRESS"}, logger)

        if not NS_CREATE_LAMBDA or not USER_CREATE_LAMBDA or not LAB_CONFIGURATION_TABLE:
            raise PermanentError("Missing required environment variables.")

        # Fetch lab settings
        lab_info = get_lab_info(lab_id, logger)

        ssm_base_path = lab_info["ssm_base_path"]
        group_names = lab_info["group_names"]
        namespace_roles = lab_info["namespace_roles"]
        user_ns = lab_info["user_ns"]
        pre_lambda = lab_info.get("pre_lambda")

        # Step 1: Fetch tenant URL from SSM, update deployment state
        try:
            region = boto3.session.Session().region_name
            params = get_parameters([f"{ssm_base_path}/tenant-url"], logger, region_name=region)
            tenant_url = params.get("tenant-url")
        except Exception as e:
            raise TransientError(f"Failed to fetch tenant URL: {e}") from e

        update_deployment_state(dep_id, {"tenant_url": tenant_url}, logger)

        # Step 2: Create Namespace (if applicable)
        if user_ns:
            namespace_payload = {
                "ssm_base_path": ssm_base_path,
                "namespace_name": petname,
                "description": f"Namespace for {dep_id}"
            }

            update_deployment_state(dep_id, {"create_namespace": "IN_PROGRESS"}, logger)
            namespace_response = invoke_lambda(NS_CREATE_LAMBDA, namespace_payload, logger)
            if namespace_response.get("statusCode") == 200:
                update_deployment_state(dep_id, {"create_namespace": "SUCCESS"}, logger)
                namespace_roles.append({"namespace": petname, "role": "ves-io-admin-role"})
            else:
                update_deployment_state(dep_id, {"create_namespace": "FAILED"}, logger)
        else:
            update_deployment_state(dep_id, {"create_namespace": "NA"}, logger)

        # Step 3: Create User
        user_payload = {
            "ssm_base_path": ssm_base_path,
            "first_name": "Lab User",
            "last_name": dep_id.split("-")[0],
            "email": email,
            "group_names": group_names,
            "namespace_roles": namespace_roles
        }

        update_deployment_state(dep_id, {"create_user": "IN_PROGRESS"}, logger)
        user_response = invoke_lambda(USER_CREATE_LAMBDA, user_payload, logger)
        if user_response.get("statusCode") == 200:
            update_deployment_state(dep_id, {"create_user": "SUCCESS"}, logger)
        else:
            update_deployment_state(dep_id, {"create_user": "FAILED"}, logger)

        # Step 4: Execute Pre-Lambda (if defined)
        if pre_lambda:
            update_deployment_state(dep_id, {"pre_lambda": "IN_PROGRESS"}, logger)
            pre_lambda_payload = {
                "ssm_base_path": ssm_base_path,
                "petname": petname,
                "email": email
            }
            pre_lambda_response = invoke_lambda(pre_lambda, pre_lambda_payload, logger)

            if pre_lambda_response.get("statusCode") == 200:
                update_deployment_state(dep_id, {"pre_lambda": "SUCCESS"}, logger)
            else:
                update_deployment_state(dep_id, {"pre_lambda": "FAILED"}, logger)
        else:
            update_deployment_state(dep_id, {"pre_lambda": "NA"}, logger)

        update_deployment_state(dep_id, {"deployment_status": "COMPLETED"}, logger)
        step_logger.info("INSERT processing completed", dep_id=dep_id)

    except (PermanentError, TransientError):
        if dep_id:
            update_deployment_state(dep_id, {"deployment_status": "FAILED"}, logger)
        raise
    except Exception as e:
        if dep_id:
            update_deployment_state(dep_id, {"deployment_status": "FAILED"}, logger)
        step_logger.error("Error processing INSERT record", error=str(e))
        raise TransientError(f"Error processing INSERT record: {e}") from e


def process_remove(record: dict, logger: StructuredLogger):
    """Handle a record REMOVE event from the DynamoDB stream."""
    step_logger = logger.with_step("process_remove")
    try:
        old_image = record["dynamodb"]["OldImage"]

        dep_id = old_image["dep_id"]["S"]
        lab_id = old_image["lab_id"]["S"]
        petname = old_image["petname"]["S"]
        email = old_image["email"]["S"]
        tenant_url = old_image.get("tenant_url", {}).get("S")
        create_namespace = old_image.get("create_namespace", {}).get("S")
        create_user = old_image.get("create_user", {}).get("S")

        step_logger.info("Processing REMOVE event", dep_id=dep_id, email=email)

        # Fetch lab settings
        lab_info = get_lab_info(lab_id, logger)
        ssm_base_path = lab_info["ssm_base_path"]
        post_lambda = lab_info.get("post_lambda")

        # Check if another deployment exists for this user in the same tenant
        skip_user_removal = False
        if tenant_url is None:
            step_logger.warn("tenant_url is missing from removed record, skipping duplicate user check", dep_id=dep_id, email=email)
        elif check_existing_user_in_tenant(email, tenant_url, logger):
            step_logger.info("Skipping user removal: Another active deployment exists", email=email, tenant_url=tenant_url)
            skip_user_removal = True

        if not skip_user_removal:
            # Step 1: Remove User if it was successfully created
            if create_user == "SUCCESS":
                if not USER_REMOVE_LAMBDA:
                    raise PermanentError("USER_REMOVE_LAMBDA environment variable is missing.")

                user_payload = {
                    "ssm_base_path": ssm_base_path,
                    "email": email
                }

                user_remove_response = invoke_lambda(USER_REMOVE_LAMBDA, user_payload, logger)
                if user_remove_response.get("statusCode") != 200:
                    step_logger.warn("User removal failed", email=email)

        # Step 2: Remove Namespace if it was successfully created
        if create_namespace == "SUCCESS":
            if not NS_REMOVE_LAMBDA:
                raise PermanentError("NS_REMOVE_LAMBDA environment variable is missing.")

            namespace_payload = {
                "ssm_base_path": ssm_base_path,
                "namespace_name": petname
            }

            ns_remove_response = invoke_lambda(NS_REMOVE_LAMBDA, namespace_payload, logger)
            if ns_remove_response.get("statusCode") != 200:
                step_logger.warn("Namespace removal failed", petname=petname)

        # Step 3: Execute Post-Lambda (if defined)
        if post_lambda:
            post_lambda_payload = {
                "ssm_base_path": ssm_base_path,
                "petname": petname,
                "email": email
            }

            post_lambda_response = invoke_lambda(post_lambda, post_lambda_payload, logger)
            if post_lambda_response.get("statusCode") != 200:
                step_logger.warn("Post-Lambda execution failed", dep_id=dep_id)

        step_logger.info("REMOVE processing completed", dep_id=dep_id)

    except (PermanentError, TransientError):
        raise
    except Exception as e:
        step_logger.error("Error processing REMOVE record", error=str(e))
        raise TransientError(f"Error processing REMOVE record: {e}") from e


@lambda_handler
def handler(event: dict, context, logger: StructuredLogger) -> dict:
    """AWS Lambda entry point for handling DynamoDB stream events."""
    for record in event["Records"]:
        if record["eventName"] == "INSERT":
            process_insert(record, logger)
        elif record["eventName"] == "REMOVE":
            process_remove(record, logger)

    return "Processed DynamoDB stream events successfully"
