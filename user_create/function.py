"""
Create a new user in an F5 XC tenant.
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


def validate_payload(payload: dict):
    """
    Validate the payload for required fields.
    """
    required_fields = ["ssm_base_path", "first_name", "last_name", "idm_type", "email"]
    missing_fields = [field for field in required_fields if field not in payload]

    if missing_fields:
        raise RuntimeError(f"Missing required fields in payload: {', '.join(missing_fields)}")


def create_user_in_tenant(_api, first_name: str, last_name: str, idm_type: str, email: str, groups: list, namespace_roles: list) -> str:
    """
    Create a new user in the tenant.
    """
    try:
        payload = _api.create_payload(
            first_name=first_name,
            last_name=last_name,
            idm_type=idm_type,
            email=email,
            groups=groups,
            namespace_roles=namespace_roles
        )
        _api.create(payload)
        return f"User '{email}' created successfully."
    except Exception as e:
        raise RuntimeError(f"Failed to create user: {e}") from e


def main(payload: dict):
    """
    Main function to process the payload and create a user.
    """
    try:
        validate_payload(payload)

        ssm_base_path = payload["ssm_base_path"]
        first_name = payload["first_name"]
        last_name = payload["last_name"]
        idm_type = payload["idm_type"]
        email = payload["email"]
        groups = payload.get("groups", [])
        namespace_roles = payload.get("namespace_roles", [])

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

        job = create_user_in_tenant(
            _api=_api,
            first_name=first_name,
            last_name=last_name,
            idm_type=idm_type,
            email=email,
            groups=groups,
            namespace_roles=namespace_roles
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


def lambda_handler(event, context):
    """
    AWS Lambda entry point.
    """
    return main(event)  # Directly pass the event (payload) as input


if __name__ == "__main__":
    # Simulated direct payload for local testing
    test_payload = {
        "ssm_base_path": "/tenantOps/app-lab",
        "first_name": "John",
        "last_name": "Doe",
        "idm_type": "local",
        "email": "john.doe@example.com"
    }
    main(test_payload)