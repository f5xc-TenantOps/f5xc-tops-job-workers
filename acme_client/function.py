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

def write_dns_hook_scripts(challenge_record: str, zone_id: str):
    """
    Creates the DNS auth and cleanup hook scripts in /tmp/ for Certbot, using provided parameters.
    """
    auth_hook_path = "/tmp/auth-hook.sh"
    cleanup_hook_path = "/tmp/cleanup-hook.sh"
   
    auth_script_content = f"""#!/bin/bash
ZONE_ID="{zone_id}"
RECORD_NAME="{challenge_record}"
aws route53 change-resource-record-sets --hosted-zone-id "$ZONE_ID" --change-batch "{{\"Changes\":[{{\"Action\":\"UPSERT\",\"ResourceRecordSet\":{{\"Name\":\"$RECORD_NAME\",\"Type\":\"TXT\",\"TTL\":30,\"ResourceRecords\":[{{\"Value\":\"\"$CERTBOT_VALIDATION\"\"}}]}}}}]}}"
sleep 30
"""
    with open(auth_hook_path, "w", encoding="utf-8") as auth_file:
        auth_file.write(auth_script_content)
 
    cleanup_script_content = f"""#!/bin/bash
ZONE_ID="{zone_id}"
RECORD_NAME="{challenge_record}"
aws route53 change-resource-record-sets --hosted-zone-id "$ZONE_ID" --change-batch "{{\"Changes\":[{{\"Action\":\"DELETE\",\"ResourceRecordSet\":{{\"Name\":\"$RECORD_NAME\",\"Type\":\"TXT\",\"TTL\":30,\"ResourceRecords\":[{{\"Value\":\"\"$CERTBOT_VALIDATION\"\"}}]}}}}]}}"
"""
    with open(cleanup_hook_path, "w", encoding="utf-8") as cleanup_file:
        cleanup_file.write(cleanup_script_content)
    
    os.chmod(auth_hook_path, 0o755)
    os.chmod(cleanup_hook_path, 0o755)
    return auth_hook_path, cleanup_hook_path

def run_certbot(domain: str, email: str, auth_hook: str = "/tmp/auth-hook.sh", cleanup_hook: str = "/tmp/cleanup-hook.sh"):
    """
    Runs Certbot
    """
    try:
        print("Running Certbot...")
        certbot_main([
            "certonly",
            "--non-interactive",
            "--agree-tos",
            "--email", email,
            "--manual",
            "--preferred-challenges", "dns",
            "--manual-auth-hook", auth_hook,
            "--manual-cleanup-hook", cleanup_hook,
            "--domains", f"*.{domain}",
            "--cert-name", domain,
            "--config-dir", "/tmp/certbot/config",
            "--work-dir", "/tmp/certbot/work",
            "--logs-dir", "/tmp/certbot/logs",
        ])
        print("Certbot succeeded.")

    except SystemExit as e:
        with open("/tmp/certbot/logs/letsencrypt.log", "r", encoding="utf-8") as log_file:
            certbot_logs = log_file.read()
            print("===== CERTBOT LOG =====")
            print(certbot_logs)
            print("===== END LOG =====")
        raise RuntimeError(f"Certbot failed: {e}") from e



def upload_cert_to_s3(cert_name: str, domain: str, bucket_name: str):
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

        print(f"Certificate uploaded to S3 bucket {bucket_name} in path {cert_name}/")
        return {
            "statusCode": 200,
            "body": f"Certificate for {domain} generated and uploaded to S3 successfully in {cert_name}."
        }

    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"Error uploading to S3: {str(e)}") from e


def main():
    """
    Main function for Lambda handler.
    """
    try:
        cert_name = os.environ.get("CERT_NAME")
        domain = os.environ.get("DOMAIN")
        email = os.environ.get("EMAIL")
        bucket_name = os.environ.get("S3_BUCKET")
        challenge_record = os.environ.get("CHALLENGE_RECORD", f"_acme-challenge.{domain}")
        zone_id = os.environ.get("CHALLENGE_ZONE_ID")

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
                raise RuntimeError(f"Access denied to S3 object {cert_key}: {e}. Check permissions.") from e
            else:
                raise RuntimeError(f"Failed to check S3 for existing certificate: {e}") from e

        auth_hook, cleanup_hook = write_dns_hook_scripts(challenge_record, zone_id)
        run_certbot(domain, email, auth_hook, cleanup_hook)

        res = upload_cert_to_s3(cert_name, domain, bucket_name)

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
