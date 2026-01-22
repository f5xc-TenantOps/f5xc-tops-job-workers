"""
Manage wildcard certificate in a tenant.
"""
import os
import base64
import boto3

from shared.decorators import lambda_handler
from shared.errors import PermanentError, ResourceExistsError
from shared.logging import StructuredLogger
from shared.ssm import get_ssm_parameters
from shared.xc_client import XCClient


def fetch_cert_from_s3(s3_client, bucket_name: str, cert_path: str, key_path: str):
    """Fetch certificate and key from S3."""
    cert_data = s3_client.get_object(Bucket=bucket_name, Key=cert_path)["Body"].read()
    key_data = s3_client.get_object(Bucket=bucket_name, Key=key_path)["Body"].read()
    return cert_data, key_data


def upload_cert_to_tenant(
    client: XCClient,
    name: str,
    cert_data: bytes,
    key_data: bytes,
    namespace: str = "shared",
    logger: StructuredLogger = None
) -> str:
    """Upload or update a certificate in the tenant."""
    cert_b64 = base64.b64encode(cert_data).decode("utf-8")
    key_b64 = base64.b64encode(key_data).decode("utf-8")

    try:
        if logger:
            logger.info("Creating new certificate", name=name, namespace=namespace)
        client.create_certificate(namespace, name, cert_b64, key_b64)
        return f"Certificate '{name}' created in namespace '{namespace}'."
    except ResourceExistsError:
        if logger:
            logger.info("Replacing existing certificate", name=name, namespace=namespace)
        client.replace_certificate(namespace, name, cert_b64, key_b64)
        return f"Certificate '{name}' replaced in namespace '{namespace}'."


@lambda_handler
def handler(event, context, logger: StructuredLogger):
    """AWS Lambda entry point for certificate management."""
    step_logger = logger.with_step("init")

    base_path = os.environ.get("SSM_BASE_PATH")
    bucket_name = os.environ.get("S3_BUCKET")
    cert_name = os.environ.get("CERT_NAME")

    if not base_path or not bucket_name:
        raise PermanentError("Missing required environment variables: SSM_BASE_PATH or S3_BUCKET.")

    if not cert_name:
        raise PermanentError("Missing required environment variable: CERT_NAME.")

    step_logger.info("Fetching parameters from SSM", base_path=base_path)

    params = get_ssm_parameters([
        f"{base_path}/tenant-url",
        f"{base_path}/token-value"
    ])

    step_logger = logger.with_step("auth")
    step_logger.info("Creating API client")

    client = XCClient(
        tenant_url=params["tenant-url"],
        api_token=params["token-value"],
        validate=False
    )

    step_logger = logger.with_step("fetch_cert")
    step_logger.info("Fetching certificate from S3", bucket=bucket_name, cert_name=cert_name)

    s3_client = boto3.client("s3")
    cert_path = f"{cert_name}/fullchain.pem"
    key_path = f"{cert_name}/privkey.pem"

    cert_data, key_data = fetch_cert_from_s3(s3_client, bucket_name, cert_path, key_path)

    step_logger = logger.with_step("upload_cert")
    step_logger.info("Uploading certificate to tenant", cert_name=cert_name)

    result = upload_cert_to_tenant(
        client=client,
        name=cert_name,
        cert_data=cert_data,
        key_data=key_data,
        namespace="shared",
        logger=step_logger
    )

    step_logger.info("Certificate management completed", result=result)
    return result


# Keep lambda_handler name for AWS Lambda
lambda_handler = handler


if __name__ == "__main__":
    # For local testing
    class MockContext:
        function_name = "cert_mgmt"
    handler({}, MockContext())
