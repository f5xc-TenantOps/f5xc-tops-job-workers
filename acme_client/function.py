"""
Generates a wildcard DNS certificate and uploads it to S3, renewing if necessary.
"""
import os
from datetime import datetime, timedelta
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from certbot.main import main as certbot_main


def check_cert_expiry(cert_path: str) -> bool:
    """
    Checks the expiry date of an existing certificate.
    """
    try:
        with open(cert_path, "rb") as cert_file:
            cert_data = cert_file.read()
            cert = x509.load_pem_x509_certificate(cert_data, default_backend())
            expiry_date = cert.not_valid_after
            return expiry_date <= datetime.utcnow() + timedelta(days=30)
    except Exception as e:
        raise RuntimeError(f"Failed to check certificate expiry: {str(e)}") from e


def certbot(domain: str, email: str, bucket_name: str, cert_name: str):
    """
    Generates a wildcard DNS certificate via the Certbot Python API and uploads it to S3.
    """
    try:
        certbot_main([
            "certonly",
            "--non-interactive",
            "--agree-tos",
            "--email", email,
            "--dns-route53",
            "--domains", f"*.{domain}",
            "--config-dir", "/tmp/certbot/config",
            "--work-dir", "/tmp/certbot/work",
            "--logs-dir", "/tmp/certbot/logs",
        ])

        cert_path = f"/tmp/certbot/config/live/{domain}/fullchain.pem"
        key_path = f"/tmp/certbot/config/live/{domain}/privkey.pem"

        s3_cert_path = f"{cert_name}/fullchain.pem"
        s3_key_path = f"{cert_name}/privkey.pem"

        s3_client = boto3.client("s3")
        s3_client.upload_file(cert_path, bucket_name, s3_cert_path)
        s3_client.upload_file(key_path, bucket_name, s3_key_path)

        return {
            "statusCode": 200,
            "body": f"Certificate for {domain} generated and uploaded to S3 successfully in {cert_name}."
        }

    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"Error uploading to S3: {str(e)}") from e
    except SystemExit as e:
        raise RuntimeError(f"Certbot failed with exit code {e.code}") from e
    except Exception as e:
        raise RuntimeError(f"Unexpected error during certbot execution: {str(e)}") from e


def main():
    """
    Main function for Lambda handler.
    """
    try:
        cert_name = os.environ.get("CERT_NAME")
        domain = os.environ.get("DOMAIN")
        email = os.environ.get("EMAIL")
        bucket_name = os.environ.get("S3_BUCKET")

        missing_vars = [var for var in ("CERT_NAME", "DOMAIN", "EMAIL", "S3_BUCKET") if os.environ.get(var) is None]
        if missing_vars:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing_vars)}")

        s3_client = boto3.client("s3")
        cert_key = f"{cert_name}/fullchain.pem"
        local_cert_path = "/tmp/fullchain.pem"

        try:
            s3_client.download_file(bucket_name, cert_key, local_cert_path)
            if not check_cert_expiry(local_cert_path):
                return {"statusCode": 200, "body": f"Certificate for {domain} is valid and does not need renewal."}
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "404":
                print(f"Certificate for {domain} not found in S3. Proceeding to issue a new one.")
            elif error_code == "403":
                raise RuntimeError(f"Access denied to S3 object: {cert_key}. Check permissions.") from e
            else:
                raise RuntimeError(f"Failed to check S3 for existing certificate: {e}") from e

        res = certbot(domain, email, bucket_name, cert_name)
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
    return main()


if __name__ == "__main__":
    main()