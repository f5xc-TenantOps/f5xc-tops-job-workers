"""
Create an Origin Pool and HTTP Load Balancer in an F5 XC tenant.
"""
import os
import time
import boto3
from f5xc_tops_py_client import session, origin_pool, http_loadbalancer


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


def validate_payload(payload: dict):
    """
    Validate the payload for required fields.
    """
    required_fields = ["ssm_base_path", "petname"]
    missing_fields = [field for field in required_fields if field not in payload]

    if missing_fields:
        raise RuntimeError(f"Missing required fields in payload: {', '.join(missing_fields)}")


def create_origin_pool(_api, namespace: str, origin_name: str) -> str:
    """
    Create an Origin Pool in the tenant.
    """
    try:
        payload = {
            "metadata": {
                "name": origin_name,
                "namespace": namespace,
                "disable": False
            },
            "spec": {
                "origin_servers": [
                    {
                        "public_name": {
                            "dns_name": "bankapi.lab-sec.f5demos.com",
                            "refresh_interval": 300
                        },
                        "labels": {}
                    }
                ],
                "port": 80,
                "same_as_endpoint_port": {},
                "healthcheck": [],
                "loadbalancer_algorithm": "LB_OVERRIDE",
                "endpoint_selection": "LOCAL_PREFERRED"
            }
        }

        _api.create(payload=payload, namespace=namespace)
        return f"Origin Pool '{origin_name}' created successfully."

    except Exception as e:
        raise RuntimeError(f"Failed to create origin pool: {e}") from e


def wait_for_origin_pool(_api, namespace: str, origin_name: str, retries: int = 20, delay: int = 5) -> None:
    """
    Wait for the Origin Pool to be available using _api.get(namespace, name).
    """
    for attempt in range(retries):
        try:
            response = _api.get(namespace=namespace, name=origin_name)
            if response:
                return 
        except Exception as e:
            error_msg = str(e)
            if "API ResponseCode 404" in error_msg:
                print(f"Attempt {attempt + 1}/{retries}: Origin Pool '{origin_name}' not found. Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                raise RuntimeError(f"Unexpected error checking Origin Pool: {e}") from e

    raise RuntimeError(f"Timeout waiting for Origin Pool '{origin_name}' to be available.")


def create_http_load_balancer(_api, namespace: str, lb_name: str, domain: str, cert_name: str, origin_name: str) -> str:
    """
    Create an HTTP Load Balancer in the tenant.
    """
    try:
        payload = {
            "metadata": {
                "name": lb_name,
                "namespace": namespace,
                "disable": False
            },
            "spec": {
                "domains": [domain],
                "https": {
                    "http_redirect": True,
                    "add_hsts": True,
                    "port": 443,
                    "tls_cert_params": {
                        "tls_config": {
                            "default_security": {}
                        },
                        "certificates": [
                            {
                                "tenant": "f5-xc-lab-sec-lpuwkdtb",
                                "namespace": "shared",
                                "name": cert_name,
                                "kind": "certificate"
                            }
                        ],
                        "no_mtls": {}
                    }
                },
                "default_route_pools": [
                    {
                        "pool": {
                            "tenant": "f5-xc-lab-sec-lpuwkdtb",
                            "namespace": namespace,
                            "name": origin_name,
                            "kind": "origin_pool"
                        },
                        "weight": 1,
                        "priority": 1
                    }
                ]
            }
        }
        print(payload)
        _api.create(payload=payload, namespace=namespace)
        return f"HTTP Load Balancer '{lb_name}' created successfully."

    except Exception as e:
        raise RuntimeError(f"Failed to create HTTP load balancer: {e}") from e


def main(payload: dict):
    """
    Main function to process the payload and create the origin pool and HTTP load balancer.
    """
    try:
        validate_payload(payload)

        env = os.getenv("ENV")
        if not env:
            raise RuntimeError("Missing required environment variable: ENV")

        # Set domain and certificate based on ENV
        base_domain = f"sec-lab{'-dev' if env.lower() == 'dev' else ''}.f5demos.com"
        cert_name = f"sec-lab-wildcard{'-dev' if env.lower() == 'dev' else ''}"

        ssm_base_path = payload["ssm_base_path"]
        petname = payload["petname"]
        namespace = petname
        origin_name = f"{petname}-origin"
        lb_name = f"{petname}-lb"
        domain = f"{petname}.{base_domain}"

        region = boto3.session.Session().region_name
        params = get_parameters(
            [
                f"{ssm_base_path}/tenant-url",
                f"{ssm_base_path}/token-value"
            ],
            region_name=region,
        )

        auth = session(tenant_url=params["tenant-url"], api_token=params["token-value"])
        origin_api = origin_pool(auth)
        lb_api = http_loadbalancer(auth)

        # Create Origin Pool
        result_message = create_origin_pool(origin_api, namespace, origin_name)

        # Wait for Origin Pool to be available
        wait_for_origin_pool(origin_api, namespace, origin_name)

        # Create HTTP Load Balancer
        lb_result_message = create_http_load_balancer(lb_api, namespace, lb_name, domain, cert_name, origin_name)

        res = {
            "statusCode": 200,
            "body": f"{result_message} {lb_result_message}"
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
    # Simulated direct payload for local testing
    test_payload = {
        "ssm_base_path": "/tenantOps/sec-lab",
        "petname": "snarky-petname"
    }
    main(test_payload)