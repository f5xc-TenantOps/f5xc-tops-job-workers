"""
Remove a namespace in an F5 XC tenant.
"""
import json
import boto3
from f5xc_tops_py_client import session, ns


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


def validate_payload_remove_ns(payload: dict):
    """
    Validate the payload for required fields.
    """
    required_fields = ["ssm_base_path", "namespace_name"]
    missing_fields = [field for field in required_fields if field not in payload]

    if missing_fields:
        raise RuntimeError(f"Missing required fields in payload: {', '.join(missing_fields)}")


def remove_namespace_from_tenant(_api, namespace_name: str) -> str:
    """
    Remove a namespace from the tenant.
    """
    try:
        _api.delete(name=namespace_name)
        return f"Namespace '{namespace_name}' removed successfully."
    except Exception as e:
        raise RuntimeError(f"Failed to remove namespace: {e}") from e


def main(payload: dict):
    """
    Main function to process the payload and remove the namespace.
    """
    try:
        validate_payload_remove_ns(payload)

        ssm_base_path = payload["ssm_base_path"]
        namespace_name = payload["namespace_name"]

        region = boto3.session.Session().region_name
        params = get_parameters(
            [
                f"{ssm_base_path}/tenant-url",
                f"{ssm_base_path}/token-value"
            ],
            region_name=region,
        )

        auth = session(tenant_url=params["tenant-url"], api_token=params["token-value"])
        _api = ns(auth)

        job = remove_namespace_from_tenant(
            _api=_api,
            namespace_name=namespace_name
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
    AWS Lambda entry point for removing a namespace.
    """
    return main(event)


if __name__ == "__main__":
    # Simulated direct payload for local testing
    test_payload_remove_ns = {
        "ssm_base_path": "/tenantOps/app-lab",
        "namespace_name": "app-namespace"
    }
    main(test_payload_remove_ns)