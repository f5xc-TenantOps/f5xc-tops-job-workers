"""
Generates a wildcard DNS certificate and uploads it to S3, renewing if necessary.
"""
# pylint: disable=broad-except
import os
import subprocess
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from datetime import datetime, timedelta


def check_cert_expiry(cert_path: str) -> bool:
    """
    Checks the expiry date of an existing certificate.

    Args:
        cert_path (str): Path to the certificate file.

    Returns:
        bool: True if the certificate expires in less than 30 days, False otherwise.
    """
    try:
        with open(cert_path, "rb") as cert_file:
            cert_data = cert_file.read()
            cert = x509.load_pem_x509_certificate(cert_data, default_backend())
            expiry_date = cert.not_valid_after
            return expiry_date <= datetime.utcnow() + timedelta(days=30)
    except Exception as e:
        raise RuntimeError(f"Failed to check certificate expiry: {str(e)}") from e


def certbot(domain: str, email: str, bucket_name: str):
    """
    Generates a wildcard DNS certificate via Route 53 and uploads it to S3.

    Args:
        domain (str): The domain for the certificate.
        email (str): The email for certbot registration.
        bucket_name (str): The S3 bucket to upload the certificate.
    """
    try:
        # Run certbot to generate the certificate
        subprocess.run(
            [
                "certbot", "certonly",
                "--non-interactive",
                "--agree-tos",
                "--email", email,
                "--dns-route53",
                "--dns-route53-propagation-seconds", "30",
                "--domains", f"*.{domain}",
                "--work-dir", "/tmp/certbot/work",
                "--logs-dir", "/tmp/certbot/logs",
                "--config-dir", "/tmp/certbot/config"
            ],
            check=True
        )

        # Define certificate paths
        cert_path = f"/tmp/certbot/config/live/{domain}/fullchain.pem"
        key_path = f"/tmp/certbot/config/live/{domain}/privkey.pem"

        # Upload certificate files to S3
        s3_client = boto3.client("s3")
        s3_client.upload_file(cert_path, bucket_name, f"{domain}/fullchain.pem")
        s3_client.upload_file(key_path, bucket_name, f"{domain}/privkey.pem")

        # Return success response
        return {
            "statusCode": 200,
            "body": f"Certificate for {domain} generated and uploaded to S3 successfully."
        }

    except subprocess.CalledProcessError as e:
        # Handle Certbot failure
        raise RuntimeError(f"Certbot process failed: {str(e)}") from e

    except (BotoCoreError, ClientError) as e:
        # Handle S3 upload failure
        raise RuntimeError(f"Error uploading to S3: {str(e)}") from e

    except Exception as e:
        # Handle general errors
        raise RuntimeError(f"Unexpected error: {str(e)}") from e


def main() -> dict:
    """
    Main function for Lambda handler.
    """
    try:
        domain = os.environ.get("DOMAIN")
        email = os.environ.get("EMAIL")
        bucket_name = os.environ.get("S3_BUCKET")

        missing_vars = [var for var in ("DOMAIN", "EMAIL", "S3_BUCKET") if os.environ.get(var) is None]
        if missing_vars:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing_vars)}")

        # Check if certificate exists in S3
        s3_client = boto3.client("s3")
        cert_key = f"{domain}/fullchain.pem"
        local_cert_path = "/tmp/fullchain.pem"

        try:
            s3_client.download_file(bucket_name, cert_key, local_cert_path)
            # Check expiry
            if not check_cert_expiry(local_cert_path):
                return {
                    "statusCode": 200,
                    "body": f"Certificate for {domain} is valid and does not need renewal."
                }
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                # Certificate does not exist in S3
                pass
            else:
                raise RuntimeError(f"Failed to check S3 for existing certificate: {str(e)}") from e

        # Generate or renew the certificate
        res = certbot(domain, email, bucket_name)

    except RuntimeError as e:
        res = {
            "statusCode": 500,
            "status": "error",
            "body": str(e)
        }
    print(res)
    return res


def lambda_handler(event, context):
    """
    AWS Lambda entry point.
    """
    return main()


if __name__ == "__main__":
    main()
