"""
Remove a user from an F5 XC tenant based on an SQS message.
"""
import json
import boto3
from f5xc_tops_py_client import session, user


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


def validate_sqs_message(message: dict):
    """
    Validate the SQS message for required fields.
    """
    required_fields = ["ssm_base_path", "email"]
    missing_fields = [field for field in required_fields if field not in message]

    if missing_fields:
        raise RuntimeError(f"Missing required fields in SQS message: {', '.join(missing_fields)}")


def remove_user_from_tenant(_api, email: str) -> str:
    """
    Remove a user from the tenant.
    """
    try:
        _api.delete(email=email)
        return f"User with email '{email}' removed successfully."
    except Exception as e:
        raise RuntimeError(f"Failed to remove user: {e}") from e


def main(event: dict):
    """
    Main function to process SQS message and remove user.
    """
    try:
        message = json.loads(event["Records"][0]["body"])  # Assuming one message per event
        validate_sqs_message(message)

        ssm_base_path = message["ssm_base_path"]
        email = message["email"]

        region = boto3.session.Session().region_name or "us-west-2"
        params = get_parameters(
            [
                f"{ssm_base_path}/tenant-url",
                f"{ssm_base_path}/token-value"
            ],
            region_name=region,
        )

        auth = session(tenant_url=params["tenant-url"], api_token=params["token-value"])
        _api = user(auth)

        job = remove_user_from_tenant(_api=_api, email=email)

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
                    "ssm_base_path": "/tenantOps/app-lab",
                    "email": "john.doe@example.com"
                })
            }
        ]
    }
    main(test_event)