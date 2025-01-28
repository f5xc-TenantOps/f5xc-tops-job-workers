"""
Create a namespace in an F5 XC tenant from an SQS message.
"""
import json
import boto3
from f5xc_tops_py_client import session, ns


def get_parameters(parameters: list, region_name: str = "us-west-2") -> dict:
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


def validate_sqs_message_create_ns(message: dict):
    """
    Validate the SQS message for creating a namespace.
    """
    required_fields = ["ssm_base_path", "namespace_name", "description"]
    missing_fields = [field for field in required_fields if field not in message]

    if missing_fields:
        raise RuntimeError(f"Missing required fields in SQS message: {', '.join(missing_fields)}")


def create_namespace_in_tenant(_api, namespace_name: str, description: str) -> str:
    """
    Create a namespace in the tenant.
    """
    try:
        payload = _api.create_payload(name=namespace_name, description=description)
        _api.create(payload)
        return f"Namespace '{namespace_name}' created successfully."
    except Exception as e:
        raise RuntimeError(f"Failed to create namespace: {e}") from e


def main_create_ns(event: dict):
    """
    Main function to process SQS message and create namespace.
    """
    try:
        message = json.loads(event["Records"][0]["body"])  # Assuming one message per event
        validate_sqs_message_create_ns(message)

        ssm_base_path = message["ssm_base_path"]
        namespace_name = message["namespace_name"]
        description = message["description"]

        region = boto3.session.Session().region_name or "us-west-2"
        params = get_parameters(
            [
                f"{ssm_base_path}/tenant-url",
                f"{ssm_base_path}/token-value"
            ],
            region_name=region,
        )

        auth = session(tenant_url=params["tenant-url"], api_token=params["token-value"])
        _api = ns(auth)

        job = create_namespace_in_tenant(
            _api=_api,
            namespace_name=namespace_name,
            description=description
        )

        res = {
            "statusCode": 200,
            "body": job
        }

    except Exception as e:
        err = {
            "statusCode": 500,
            "body": f"Error: {e}"
        }
        print(err)
        raise RuntimeError(err) from e

    print(res)
    return res


def lambda_handler_create_ns(event, context):
    """
    AWS Lambda entry point for creating a namespace.
    """
    return main_create_ns(event)


if __name__ == "__main__":
    test_event_create_ns = {
        "Records": [
            {
                "body": json.dumps({
                    "ssm_base_path": "/tenantOps/app-lab",
                    "namespace_name": "app-namespace",
                    "description": "Namespace for application workloads"
                })
            }
        ]
    }
    main_create_ns(test_event_create_ns)