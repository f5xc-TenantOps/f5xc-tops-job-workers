"""Create an Origin Pool and TCP Load Balancer in an F5 XC tenant for CaaS lab."""

import os
import time

import boto3
from f5xc_tops_py_client import origin_pool, session, tcp_loadbalancer

from shared.decorators import lambda_handler, with_retry
from shared.errors import PermanentError, TransientError
from shared.logging import StructuredLogger


def get_parameters(parameters: list, region_name: str = "us-east-1") -> dict:
    """Fetch parameters from AWS Parameter Store."""
    try:
        aws = boto3.session.Session()
        ssm = aws.client("ssm", region_name=region_name)
        response = ssm.get_parameters(Names=parameters, WithDecryption=True)
        return {
            param["Name"].split("/")[-1]: param["Value"]
            for param in response["Parameters"]
        }
    except Exception as e:
        raise TransientError(f"Failed to fetch parameters: {e}") from e


def validate_payload(payload: dict):
    """Validate the payload for required fields."""
    required_fields = ["ssm_base_path", "petname"]
    missing_fields = [field for field in required_fields if field not in payload]

    if missing_fields:
        raise PermanentError(
            f"Missing required fields in payload: {', '.join(missing_fields)}"
        )


@with_retry(max_attempts=3)
def create_origin_pool(
    _api, namespace: str, origin_name: str, logger: StructuredLogger
) -> str:
    """Create an Origin Pool in the tenant."""
    step_logger = logger.with_step("create_origin_pool")
    try:
        payload = {
            "metadata": {
                "name": origin_name,
                "labels": {},
                "annotations": {},
                "disable": False,
            },
            "spec": {
                "origin_servers": [
                    {
                        "k8s_service": {
                            "service_name": f"mosquitto.{namespace}",
                            "site_locator": {
                                "virtual_site": {
                                    "namespace": "shared",
                                    "name": "appworld2025-k8s-vsite",
                                    "kind": "virtual_site",
                                }
                            },
                            "vk8s_networks": {},
                        },
                        "labels": {},
                    }
                ],
                "no_tls": {},
                "port": 1883,
                "same_as_endpoint_port": {},
                "healthcheck": [],
                "loadbalancer_algorithm": "LB_OVERRIDE",
                "endpoint_selection": "LOCAL_ONLY",
            },
        }

        _api.create(payload=payload, namespace=namespace)
        step_logger.info("Origin pool created", name=origin_name, namespace=namespace)
        return f"Origin Pool '{origin_name}' created successfully."

    except Exception as e:
        step_logger.error("Failed to create origin pool", error=str(e))
        raise TransientError(f"Failed to create origin pool: {e}") from e


def wait_for_origin_pool(
    _api,
    namespace: str,
    origin_name: str,
    logger: StructuredLogger,
    retries: int = 20,
    delay: int = 5,
) -> None:
    """Wait for the Origin Pool to be available."""
    step_logger = logger.with_step("wait_for_origin_pool")
    for attempt in range(retries):
        try:
            response = _api.get(namespace=namespace, name=origin_name)
            if response:
                step_logger.info("Origin pool available", name=origin_name)
                return
        except Exception as e:
            error_msg = str(e)
            if "API ResponseCode 404" in error_msg:
                step_logger.info(
                    "Origin pool not found, retrying",
                    attempt=attempt + 1,
                    max_retries=retries,
                )
                time.sleep(delay)
            else:
                step_logger.error("Unexpected error checking origin pool", error=error_msg)
                raise TransientError(f"Unexpected error checking Origin Pool: {e}") from e

    raise TransientError(
        f"Timeout waiting for Origin Pool '{origin_name}' to be available."
    )


@with_retry(max_attempts=3)
def create_tcp_load_balancer(
    _api,
    namespace: str,
    lb_name: str,
    domain: list,
    cert_name: str,
    origin_name: str,
    logger: StructuredLogger,
) -> str:
    """Create a TCP Load Balancer in the tenant."""
    step_logger = logger.with_step("create_tcp_load_balancer")
    try:
        payload = {
            "metadata": {
                "name": lb_name,
                "labels": {},
                "annotations": {},
                "disable": False,
            },
            "spec": {
                "domains": domain,
                "listen_port": 8883,
                "sni": {},
                "dns_volterra_managed": False,
                "origin_pools": [],
                "origin_pools_weights": [
                    {
                        "pool": {
                            "namespace": namespace,
                            "name": origin_name,
                            "kind": "origin_pool",
                        },
                        "weight": 1,
                        "priority": 1,
                        "endpoint_subsets": {},
                    }
                ],
                "advertise_custom": {
                    "advertise_where": [
                        {
                            "virtual_site": {
                                "network": "SITE_NETWORK_INSIDE_AND_OUTSIDE",
                                "virtual_site": {
                                    "namespace": "shared",
                                    "name": "appworld2025-k8s-vsite",
                                    "kind": "virtual_site",
                                },
                            },
                            "use_default_port": {},
                        }
                    ]
                },
                "tls_tcp": {
                    "tls_cert_params": {
                        "tls_config": {"default_security": {}},
                        "certificates": [
                            {
                                "namespace": "shared",
                                "name": cert_name,
                                "kind": "certificate",
                            }
                        ],
                        "no_mtls": {},
                    }
                },
                "service_policies_from_namespace": {},
            },
        }
        _api.create(payload=payload, namespace=namespace)
        step_logger.info("TCP load balancer created", name=lb_name, domains=domain)
        return f"TCP Load Balancer '{lb_name}' created successfully."

    except Exception as e:
        step_logger.error("Failed to create TCP load balancer", error=str(e))
        raise TransientError(f"Failed to create TCP load balancer: {e}") from e


def main(payload: dict, logger: StructuredLogger):
    """Process the payload and create the origin pool and TCP load balancer."""
    step_logger = logger.with_step("main")

    validate_payload(payload)

    env = os.getenv("ENV")
    if not env:
        raise PermanentError("Missing required environment variable: ENV")

    base_domain = "lab-app.f5demos.com"
    cert_name = "caas-lab-certificate"

    ssm_base_path = payload["ssm_base_path"]
    petname = payload["petname"]
    namespace = petname
    origin_name = f"{petname}-mosquitto"
    lb_name = f"{petname}-mqtt"
    domain = [
        f"{petname}.useast.{base_domain}",
        f"{petname}.uswest.{base_domain}",
        f"{petname}.europe.{base_domain}",
    ]

    step_logger.info(
        "Processing request",
        petname=petname,
        namespace=namespace,
        domains=domain,
    )

    region = boto3.session.Session().region_name
    params = get_parameters(
        [f"{ssm_base_path}/tenant-url", f"{ssm_base_path}/token-value"],
        region_name=region,
    )

    auth = session(tenant_url=params["tenant-url"], api_token=params["token-value"])
    origin_api = origin_pool(auth)
    lb_api = tcp_loadbalancer(auth)

    # Create Origin Pool
    result_message = create_origin_pool(origin_api, namespace, origin_name, logger)

    # Wait for Origin Pool to be available
    wait_for_origin_pool(origin_api, namespace, origin_name, logger)

    # Create TCP Load Balancer
    lb_result_message = create_tcp_load_balancer(
        lb_api, namespace, lb_name, domain, cert_name, origin_name, logger
    )

    return f"{result_message} {lb_result_message}"


@lambda_handler
def handler(event, context, logger: StructuredLogger):
    """AWS Lambda entry point."""
    return main(event, logger)


if __name__ == "__main__":
    # Local testing
    class MockContext:
        function_name = "caaslab-pre"

    test_payload = {
        "ssm_base_path": "/tenantOps/sec-lab",
        "petname": "snarky-petname",
    }
    handler(test_payload, MockContext())
