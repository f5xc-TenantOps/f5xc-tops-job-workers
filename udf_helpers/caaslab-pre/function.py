"""Create an Origin Pool and TCP Load Balancer in an F5 XC tenant for CaaS lab."""

import os
import time

from shared.decorators import lambda_handler
from shared.errors import PermanentError, ResourceExistsError, ResourceNotFoundError
from shared.logging import StructuredLogger
from shared.ssm import get_ssm_parameters
from shared.xc_client import XCClient


def validate_payload(payload: dict):
    """Validate the payload for required fields."""
    required_fields = ["ssm_base_path", "petname"]
    missing_fields = [field for field in required_fields if field not in payload]

    if missing_fields:
        raise PermanentError(
            f"Missing required fields in payload: {', '.join(missing_fields)}"
        )


def create_origin_pool(
    client: XCClient, namespace: str, origin_name: str, logger: StructuredLogger
) -> str:
    """Create an Origin Pool in the tenant."""
    step_logger = logger.with_step("create_origin_pool")
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

    try:
        client.create_origin_pool(namespace, payload)
        step_logger.info("Origin pool created", name=origin_name, namespace=namespace)
    except ResourceExistsError:
        step_logger.info("Origin pool already exists", name=origin_name, namespace=namespace)

    return f"Origin Pool '{origin_name}' created successfully."


def wait_for_origin_pool(
    client: XCClient,
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
            response = client.get_origin_pool(namespace, origin_name)
            if response:
                step_logger.info("Origin pool available", name=origin_name)
                return
        except ResourceNotFoundError:
            step_logger.info(
                "Origin pool not found, retrying",
                attempt=attempt + 1,
                max_retries=retries,
            )
            time.sleep(delay)

    raise PermanentError(
        f"Timeout waiting for Origin Pool '{origin_name}' to be available."
    )


def create_tcp_load_balancer(
    client: XCClient,
    namespace: str,
    lb_name: str,
    domain: list,
    cert_name: str,
    origin_name: str,
    logger: StructuredLogger,
) -> str:
    """Create a TCP Load Balancer in the tenant."""
    step_logger = logger.with_step("create_tcp_load_balancer")
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

    try:
        client.create_tcp_loadbalancer(namespace, payload)
        step_logger.info("TCP load balancer created", name=lb_name, domains=domain)
    except ResourceExistsError:
        step_logger.info("TCP load balancer already exists", name=lb_name, domains=domain)

    return f"TCP Load Balancer '{lb_name}' created successfully."


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

    params = get_ssm_parameters(
        [f"{ssm_base_path}/tenant-url", f"{ssm_base_path}/token-value"]
    )

    client = XCClient(
        tenant_url=params["tenant-url"],
        api_token=params["token-value"],
        validate=False
    )

    # Create Origin Pool
    result_message = create_origin_pool(client, namespace, origin_name, logger)

    # Wait for Origin Pool to be available
    wait_for_origin_pool(client, namespace, origin_name, logger)

    # Create TCP Load Balancer
    lb_result_message = create_tcp_load_balancer(
        client, namespace, lb_name, domain, cert_name, origin_name, logger
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
