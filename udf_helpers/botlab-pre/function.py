"""Create an Origin Pool and HTTP Load Balancer in an F5 XC tenant for Bot lab."""

import os
import time

from shared.decorators import lambda_handler
from shared.errors import PermanentError, ResourceExistsError, TransientError
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
    try:
        payload = {
            "metadata": {
                "name": origin_name,
                "namespace": namespace,
                "labels": {},
                "annotations": {},
                "disable": False,
            },
            "spec": {
                "origin_servers": [
                    {
                        "public_name": {
                            "dns_name": "airline-backend.f5se.com",
                            "refresh_interval": 300,
                        },
                        "labels": {},
                    }
                ],
                "port": 80,
            },
        }

        client.create_origin_pool(namespace, payload)
        step_logger.info("Origin pool created", name=origin_name, namespace=namespace)
        return f"Origin Pool '{origin_name}' created successfully."

    except ResourceExistsError:
        step_logger.info("Origin pool already exists", name=origin_name, namespace=namespace)
        return f"Origin Pool '{origin_name}' already exists."

    except Exception as e:
        step_logger.error("Failed to create origin pool", error=str(e))
        raise TransientError(f"Failed to create origin pool: {e}") from e


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
        except Exception as e:
            error_msg = str(e)
            if "404" in error_msg or "not found" in error_msg.lower():
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


def create_http_load_balancer(
    client: XCClient,
    namespace: str,
    lb_name: str,
    domain: str,
    origin_name: str,
    logger: StructuredLogger,
) -> str:
    """Create an HTTP Load Balancer in the tenant."""
    step_logger = logger.with_step("create_http_load_balancer")
    try:
        payload = {
            "metadata": {
                "name": lb_name,
                "namespace": namespace,
                "disable": False,
            },
            "spec": {
                "domains": [domain],
                "http": {"port": 80},
                "default_route_pools": [
                    {
                        "pool": {
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
        client.create_http_loadbalancer(namespace, payload)
        step_logger.info("HTTP load balancer created", name=lb_name, domain=domain)
        return f"HTTP Load Balancer '{lb_name}' created successfully."

    except ResourceExistsError:
        step_logger.info("HTTP load balancer already exists", name=lb_name, domain=domain)
        return f"HTTP Load Balancer '{lb_name}' already exists."

    except Exception as e:
        step_logger.error("Failed to create HTTP load balancer", error=str(e))
        raise TransientError(f"Failed to create HTTP load balancer: {e}") from e


def main(payload: dict, logger: StructuredLogger):
    """Process the payload and create the origin pool and HTTP load balancer."""
    step_logger = logger.with_step("main")

    validate_payload(payload)

    env = os.getenv("ENV")
    if not env:
        raise PermanentError("Missing required environment variable: ENV")

    # Set domain and certificate based on ENV
    base_domain = f"lab-sec{'-dev' if env.lower() == 'dev' else ''}.f5demos.com"

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
        api_token=params["token-value"],
        validate=False
    )

    # Create Origin Pool
    result_message = create_origin_pool(client, namespace, origin_name, logger)

    # Wait for Origin Pool to be available
    wait_for_origin_pool(client, namespace, origin_name, logger)

    # Create HTTP Load Balancer
    lb_result_message = create_http_load_balancer(
        client, namespace, lb_name, domain, origin_name, logger
    )

    return f"{result_message} {lb_result_message}"


@lambda_handler
def handler(event, context, logger: StructuredLogger):
    """AWS Lambda entry point."""
    return main(event, logger)


if __name__ == "__main__":
    # Local testing
    class MockContext:
        function_name = "botlab-pre"

    test_payload = {
        "ssm_base_path": "/tenantOps/sec-lab",
        "petname": "snarky-petname",
    }
    handler(test_payload, MockContext())
