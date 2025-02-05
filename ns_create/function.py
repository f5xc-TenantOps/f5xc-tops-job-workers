"""
Create a namespace in an F5 XC tenant and verify its availability.
"""
import time
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


def validate_payload_create_ns(payload: dict):
    """
    Validate the payload for required fields.
    """
    required_fields = ["ssm_base_path", "namespace_name"]
    missing_fields = [field for field in required_fields if field not in payload]

    if missing_fields:
        raise RuntimeError(f"Missing required fields in payload: {', '.join(missing_fields)}")


def create_namespace_in_tenant(_api, namespace_name: str, description: str = "") -> str:
    """
    Create a namespace in the tenant.
    """
    try:
        payload = _api.create_payload(name=namespace_name, description=description)
        _api.create(payload)
        return f"Namespace '{namespace_name}' created successfully."
    except Exception as e:
        raise RuntimeError(f"Failed to create namespace: {e}") from e


def wait_for_namespace(_api, namespace_name: str, timeout: int = 20, interval: int = 5):
    """
    Wait for the namespace to be available.
    """
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            response = _api.get(namespace=namespace_name)
            if response:
                return f"Namespace '{namespace_name}' is available."
        except Exception:
            time.sleep(interval)

    raise RuntimeError(f"Namespace '{namespace_name}' was not available within {timeout} seconds.")


def main(payload: dict):
    """
    Main function to process the payload, create a namespace, and verify its availability.
    """
    try:
        validate_payload_create_ns(payload)

        ssm_base_path = payload["ssm_base_path"]
        namespace_name = payload["namespace_name"]
        description = payload.get("description", "") 

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

        job = create_namespace_in_tenant(_api, namespace_name, description)

        # Wait for the namespace to be available
        status = wait_for_namespace(_api, namespace_name)

        res = {
            "statusCode": 200,
            "body": f"{job} | {status}"
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
    AWS Lambda entry point for creating a namespace.
    """
    return main(event)


if __name__ == "__main__":
    # Simulated direct payload for local testing
    test_payload_create_ns = {
        "ssm_base_path": "/tenantOps/app-lab",
        "namespace_name": "snarky-petname",
        "description": "testing namespace creation"
    }
    main(test_payload_create_ns)