"""Create an Origin Pool and HTTP Load Balancer in an F5 XC tenant for example lab."""

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
            "namespace": namespace,
            "disable": False,
        },
        "spec": {
            "origin_servers": [
                {
                    "public_name": {
                        "dns_name": "appedge.one",
                        "refresh_interval": 300,
                    },
                    "labels": {},
                }
            ],
            "use_tls": {
                "use_host_header_as_sni": {},
                "tls_config": {"default_security": {}},
                "volterra_trusted_ca": {},
                "no_mtls": {},
                "default_session_key_caching": {},
            },
            "port": 443,
            "same_as_endpoint_port": {},
            "healthcheck": [],
            "loadbalancer_algorithm": "LB_OVERRIDE",
            "endpoint_selection": "LOCAL_PREFERRED",
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


def create_http_load_balancer(
    client: XCClient,
    namespace: str,
    lb_name: str,
    domain: str,
    cert_name: str,
    origin_name: str,
    logger: StructuredLogger,
) -> str:
    """Create an HTTP Load Balancer in the tenant."""
    step_logger = logger.with_step("create_http_load_balancer")
    payload = {
        "metadata": {
            "name": lb_name,
            "namespace": namespace,
            "disable": False,
        },
        "spec": {
            "domains": [domain],
            "https": {
                "http_redirect": True,
                "add_hsts": True,
                "port": 443,
                "tls_cert_params": {
                    "tls_config": {"default_security": {}},
                    "certificates": [
                        {
                            "tenant": "f5-xc-lab-sec-lpuwkdtb",
                            "namespace": "shared",
                            "name": cert_name,
                            "kind": "certificate",
                        }
                    ],
                    "no_mtls": {},
                },
            },
            "default_route_pools": [
                {
                    "pool": {
                        "tenant": "f5-xc-lab-sec-lpuwkdtb",
                        "namespace": namespace,
                        "name": origin_name,
                        "kind": "origin_pool",
                    },
                    "weight": 1,
                    "priority": 1,
                }
            ],
        },
    }
    step_logger.debug("Creating HTTP load balancer", payload=payload)

    try:
        client.create_http_loadbalancer(namespace, payload)
        step_logger.info("HTTP load balancer created", name=lb_name, domain=domain)
    except ResourceExistsError:
        step_logger.info("HTTP load balancer already exists", name=lb_name, domain=domain)

    return f"HTTP Load Balancer '{lb_name}' created successfully."


def main(payload: dict, logger: StructuredLogger):
    """Process the payload and create the origin pool and HTTP load balancer."""
    step_logger = logger.with_step("main")

    validate_payload(payload)

    env = os.getenv("ENV")
    if not env:
        raise PermanentError("Missing required environment variable: ENV")

    # Set domain and certificate based on ENV
    base_domain = f"lab-sec{'-dev' if env.lower() == 'dev' else ''}.f5demos.com"
    cert_name = f"lab-sec-wildcard{'-dev' if env.lower() == 'dev' else ''}"

    ssm_base_path = payload["ssm_base_path"]
    petname = payload["petname"]
    namespace = petname
    origin_name = f"{petname}-origin"
    lb_name = f"{petname}-lb"
    domain = f"{petname}.{base_domain}"

    step_logger.info(
        "Processing request",
        petname=petname,
        namespace=namespace,
        domain=domain,
    )

    params = get_ssm_parameters(
        [f"{ssm_base_path}/tenant-url", f"{ssm_base_path}/token-value"]
    )

    client = XCClient(
        tenant_url=params["tenant-url"],
        api_token=params["token-value"]
    )

    # Create Origin Pool
    result_message = create_origin_pool(client, namespace, origin_name, logger)

    # Wait for Origin Pool to be available
    wait_for_origin_pool(client, namespace, origin_name, logger)

    # Create HTTP Load Balancer
    lb_result_message = create_http_load_balancer(
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
        function_name = "example-pre"

    test_payload = {
        "ssm_base_path": "/tenantOps/sec-lab",
        "petname": "snarky-petname",
    }
    handler(test_payload, MockContext())
