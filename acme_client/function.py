"""
Generates a wildcard DNS certificate and uploads it to S3, renewing if necessary.
"""
import os
import time
from datetime import datetime, timedelta
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from certbot.main import main as certbot_main

from shared.logging import StructuredLogger
from shared.errors import PermanentError, TransientError
from shared.decorators import lambda_handler, with_retry


def check_cert_expiry(cert_path: str, logger: StructuredLogger = None) -> bool:
    """
    Checks the expiry date of an existing certificate.
    Returns True if certificate needs renewal (expires within 30 days).
    """
    try:
        with open(cert_path, "rb") as cert_file:
            cert_data = cert_file.read()
            cert = x509.load_pem_x509_certificate(cert_data, default_backend())
            expiry_date = cert.not_valid_after
            needs_renewal = expiry_date <= datetime.utcnow() + timedelta(days=30)
            if logger:
                logger.info("Certificate expiry checked",
                           expiry_date=expiry_date.isoformat(),
                           needs_renewal=needs_renewal)
            return needs_renewal
    except Exception as e:
        raise PermanentError(f"Failed to check certificate expiry: {str(e)}") from e


@with_retry(max_attempts=3, backoff_base=2)
def update_dns_record(action: str, record_name: str, zone_id: str, validation_value: str, logger: StructuredLogger = None):
    """
    Updates or deletes a TXT record in Route 53 for Certbot DNS validation.
    """
    client = boto3.client("route53")
    change_batch = {
        "Changes": [
            {
                "Action": action,
                "ResourceRecordSet": {
                    "Name": record_name,
                    "Type": "TXT",
                    "TTL": 30,
                    "ResourceRecords": [{"Value": f'"{validation_value}"'}]
                }
            }
        ]
    }

    try:
        if logger:
            logger.info("Updating DNS record",
                       action=action,
                       record_name=record_name,
                       zone_id=zone_id)
        response = client.change_resource_record_sets(
            HostedZoneId=zone_id,
            ChangeBatch=change_batch
        )
        if logger:
            logger.info("DNS update completed", change_id=response.get("ChangeInfo", {}).get("Id"))
        return response
    except (BotoCoreError, ClientError) as e:
        if logger:
            logger.error("Failed to update DNS record", error=str(e))
        raise TransientError(f"Error updating DNS record: {str(e)}") from e


def certbot_auth_hook():
    """
    Certbot manual authentication hook - creates the DNS TXT record.
    """
    validation_value = os.environ.get("CERTBOT_VALIDATION")
    zone_id = os.environ.get("CHALLENGE_ZONE_ID")
    record_name = os.environ.get("CHALLENGE_RECORD")
    if not validation_value or not zone_id or not record_name:
        raise PermanentError("Missing required environment variables for DNS challenge.")

    update_dns_record("UPSERT", record_name, zone_id, validation_value)
    time.sleep(30)


def certbot_cleanup_hook():
    """
    Certbot manual cleanup hook - removes the DNS TXT record.
    """
    validation_value = os.environ.get("CERTBOT_VALIDATION")
    zone_id = os.environ.get("CHALLENGE_ZONE_ID")
    record_name = os.environ.get("CHALLENGE_RECORD")
    if not validation_value or not zone_id or not record_name:
        raise PermanentError("Missing required environment variables for DNS challenge.")

    update_dns_record("DELETE", record_name, zone_id, validation_value)


def run_certbot(domain: str, email: str, logger: StructuredLogger = None):
    """
    Runs Certbot to obtain a certificate.
    """
    try:
        if logger:
            logger.info("Running Certbot", domain=domain, email=email)
        certbot_main([
            "certonly",
            "--non-interactive",
            "--agree-tos",
            "--email", email,
            "--manual",
            "--preferred-challenges", "dns",
            "--manual-auth-hook", "python -c 'import function; function.certbot_auth_hook()'",
            "--manual-cleanup-hook", "python -c 'import function; function.certbot_cleanup_hook()'",
            "--domains", f"*.{domain}",
            "--cert-name", domain,
            "--config-dir", "/tmp/certbot/config",
            "--work-dir", "/tmp/certbot/work",
            "--logs-dir", "/tmp/certbot/logs",
        ])
        if logger:
            logger.info("Certbot succeeded")

    except SystemExit as e:
        with open("/tmp/certbot/logs/letsencrypt.log", "r", encoding="utf-8") as log_file:
            certbot_logs = log_file.read()
            if logger:
                logger.error("Certbot failed", logs=certbot_logs[:2000])  # Truncate long logs
        raise TransientError(f"Certbot failed: {e}") from e


@with_retry(max_attempts=3, backoff_base=2)
def upload_cert_to_s3(cert_name: str, domain: str, bucket_name: str, logger: StructuredLogger = None) -> str:
    """
    Uploads the generated certificate to S3.
    """
    try:
        cert_path = f"/tmp/certbot/config/live/{domain}/fullchain.pem"
        key_path = f"/tmp/certbot/config/live/{domain}/privkey.pem"

        s3_cert_path = f"{cert_name}/fullchain.pem"
        s3_key_path = f"{cert_name}/privkey.pem"

        s3_client = boto3.client("s3")
        s3_client.upload_file(cert_path, bucket_name, s3_cert_path)
        s3_client.upload_file(key_path, bucket_name, s3_key_path)

        if logger:
            logger.info("Certificate uploaded to S3",
                       bucket=bucket_name,
                       path=f"{cert_name}/")
        return f"Certificate for {domain} generated and uploaded to S3 successfully in {cert_name}."

    except (BotoCoreError, ClientError) as e:
        raise TransientError(f"Error uploading to S3: {str(e)}") from e


@with_retry(max_attempts=3, backoff_base=2)
def download_cert_from_s3(s3_client, bucket_name: str, cert_key: str, local_path: str):
    """
    Download existing certificate from S3 to check expiry.
    """
    s3_client.download_file(bucket_name, cert_key, local_path)


@lambda_handler
def handler(event, context, logger: StructuredLogger):
    """
    AWS Lambda entry point for ACME certificate generation.
    """
    step_logger = logger.with_step("init")

    cert_name = os.environ.get("CERT_NAME")
    domain = os.environ.get("DOMAIN")
    email = os.environ.get("EMAIL")
    bucket_name = os.environ.get("S3_BUCKET")

    missing_vars = [var for var in ("CERT_NAME", "DOMAIN", "EMAIL", "S3_BUCKET", "CHALLENGE_RECORD", "CHALLENGE_ZONE_ID") if os.environ.get(var) is None]
    if missing_vars:
        raise PermanentError(f"Missing required environment variables: {', '.join(missing_vars)}")

    step_logger.info("ACME client initialized",
                    cert_name=cert_name,
                    domain=domain,
                    bucket=bucket_name)

    step_logger = logger.with_step("check_expiry")
    s3_client = boto3.client("s3")
    cert_key = f"{cert_name}/fullchain.pem"
    local_cert_path = "/tmp/fullchain.pem"

    try:
        download_cert_from_s3(s3_client, bucket_name, cert_key, local_cert_path)
        if not check_cert_expiry(local_cert_path, step_logger):
            step_logger.info("Certificate is valid, no renewal needed", domain=domain)
            return f"Certificate for {domain} is valid and does not need renewal."
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "404":
            step_logger.info("Certificate not found in S3, will issue new one", domain=domain)
        elif error_code == "403":
            raise PermanentError(f"Access denied to S3 object {cert_key}: {e}. Check permissions.") from e
        else:
            raise TransientError(f"Failed to check S3 for existing certificate: {e}") from e

    step_logger = logger.with_step("certbot")
    run_certbot(domain, email, step_logger)

    step_logger = logger.with_step("upload")
    result = upload_cert_to_s3(cert_name, domain, bucket_name, step_logger)

    step_logger.info("ACME certificate workflow completed", result=result)
    return result


# Keep lambda_handler name for AWS Lambda
lambda_handler = handler


if __name__ == "__main__":
    # For local testing
    class MockContext:
        function_name = "acme_client"
    handler({}, MockContext())
