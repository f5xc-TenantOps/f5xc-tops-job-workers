"""
Manage wildcard certificate in a tenant.
"""
import os
import base64
import boto3
from f5xc_tops_py_client import session, cert

from shared.logging import StructuredLogger
from shared.errors import PermanentError, TransientError
from shared.decorators import lambda_handler, with_retry


@with_retry(max_attempts=3, backoff_base=2)
def get_parameters(parameters: list, region_name: str = "us-east-1") -> dict:
    """
    Fetch parameters from AWS Parameter Store.
    """
    aws = boto3.session.Session()
    ssm = aws.client("ssm", region_name=region_name)
    response = ssm.get_parameters(Names=parameters, WithDecryption=True)
    return {param["Name"].split("/")[-1]: param["Value"] for param in response["Parameters"]}


@with_retry(max_attempts=3, backoff_base=2)
def cert_exists(_api, name: str, namespace: str = "shared") -> bool:
    """
    Check if a certificate exists in the tenant.
    """
    certs = _api.list(namespace)
    if not certs:
        raise TransientError(f"Failed to retrieve certificate list for namespace '{namespace}'.")
    return any(c["name"] == name for c in certs)


@with_retry(max_attempts=3, backoff_base=2)
def upload_cert_to_tenant(_api, name: str, cert_data: str, key_data: str, namespace: str = "shared", logger: StructuredLogger = None) -> str:
    """
    Upload or update a certificate in the tenant.
    """
    # Base64 encode the cert and key
    cert_b64 = base64.b64encode(cert_data).decode("utf-8")
    key_b64 = base64.b64encode(key_data).decode("utf-8")

    payload = _api.create_payload(name=name, namespace=namespace, cert=cert_b64, key=key_b64)

    if cert_exists(_api, name, namespace):
        if logger:
            logger.info("Replacing existing certificate", name=name, namespace=namespace)
        _api.replace(payload=payload, name=name, namespace=namespace)
        return f"Certificate '{name}' replaced in namespace '{namespace}'."

    if logger:
        logger.info("Creating new certificate", name=name, namespace=namespace)
    _api.create(payload=payload, namespace=namespace)
    return f"Certificate '{name}' created in namespace '{namespace}'."


@with_retry(max_attempts=3, backoff_base=2)
def fetch_cert_from_s3(s3_client, bucket_name: str, cert_path: str, key_path: str):
    """
    Fetch certificate and key from S3.
    """
    cert_data = s3_client.get_object(Bucket=bucket_name, Key=cert_path)["Body"].read()
    key_data = s3_client.get_object(Bucket=bucket_name, Key=key_path)["Body"].read()
    return cert_data, key_data


@lambda_handler
def handler(event, context, logger: StructuredLogger):
    """
    AWS Lambda entry point for certificate management.
    """
    step_logger = logger.with_step("init")

    base_path = os.environ.get("SSM_BASE_PATH")
    bucket_name = os.environ.get("S3_BUCKET")
    cert_name = os.environ.get("CERT_NAME")

    if not base_path or not bucket_name:
        raise PermanentError("Missing required environment variables: SSM_BASE_PATH or S3_BUCKET.")

    if not cert_name:
        raise PermanentError("Missing required environment variable: CERT_NAME.")

    step_logger.info("Fetching parameters from SSM", base_path=base_path)

    region = boto3.session.Session().region_name
    params = get_parameters(
        [
            f"{base_path}/tenant-url",
            f"{base_path}/token-value"
        ],
        region_name=region,
    )

    step_logger = logger.with_step("auth")
    step_logger.info("Creating API session")

    auth = session(tenant_url=params["tenant-url"], api_token=params["token-value"])
    _api = cert(auth)

    step_logger = logger.with_step("fetch_cert")
    step_logger.info("Fetching certificate from S3", bucket=bucket_name, cert_name=cert_name)

    s3_client = boto3.client("s3")
    cert_path = f"{cert_name}/fullchain.pem"
    key_path = f"{cert_name}/privkey.pem"

    cert_data, key_data = fetch_cert_from_s3(s3_client, bucket_name, cert_path, key_path)

    step_logger = logger.with_step("upload_cert")
    step_logger.info("Uploading certificate to tenant", cert_name=cert_name)

    result = upload_cert_to_tenant(
        _api=_api,
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
