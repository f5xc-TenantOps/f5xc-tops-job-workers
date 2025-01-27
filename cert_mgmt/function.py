"""
Manage wildcard certificate in a tenant.
"""
import os
import base64
import boto3
from f5xc_tops_py_client import session, cert


def get_parameters(parameters: list, region_name: str = "us-west-2") -> dict:
    """
    Fetch parameters from AWS Parameter Store.
    """
    try:
        aws = boto3.session.Session()
        ssm = aws.client("ssm", region_name=region_name)
        response = ssm.get_parameters(Names=parameters, WithDecryption=True)
        return {param["Name"].split("/")[-1]: param["Value"] for param in response["Parameters"]}
    except Exception as e:
        raise RuntimeError(f"Failed to fetch parameters: {e}") from e


def cert_exists(_api, name: str, namespace: str = "shared") -> bool:
    """
    Check if a certificate exists in the tenant.
    """
    certs = _api.list(namespace)
    if not certs:
        raise RuntimeError(f"Failed to retrieve certificate list for namespace '{namespace}'.")
    return any(c["name"] == name for c in certs)


def upload_cert_to_tenant(_api, name: str, cert_data: str, key_data: str, namespace: str = "shared") -> str:
    """
    Upload or update a certificate in the tenant.
    """
    try:
        # Base64 encode the cert and key
        cert_b64 = base64.b64encode(cert_data).decode("utf-8")
        key_b64 = base64.b64encode(key_data).decode("utf-8")

        payload = _api.create_payload(name=name, namespace=namespace, cert=cert_b64, key=key_b64)

        if cert_exists(_api, name, namespace):
            _api.replace(payload=payload, name=name, namespace=namespace)
            return f"Certificate '{name}' replaced in namespace '{namespace}'."
        _api.create(payload=payload, namespace=namespace)
        return f"Certificate '{name}' created in namespace '{namespace}'."
    except Exception as e:
        raise RuntimeError(f"Failed to upload or update certificate: {e}") from e


def main():
    """
    Main function to manage wildcard certificate.
    """
    try:
        base_path = os.environ.get("SSM_BASE_PATH")
        bucket_name = os.environ.get("S3_BUCKET")
        cert_name = os.environ.get("CERT_NAME")
        if not base_path or not bucket_name:
            raise RuntimeError("Missing required environment variables: SSM_BASE_PATH or S3_BUCKET.")

        region = boto3.session.Session().region_name or "us-west-2"
        params = get_parameters(
            [
                f"{base_path}/tenant-url",
                f"{base_path}/token-value"
            ],
            region_name=region,
        )

        auth = session(tenant_url=params["tenant-url"], api_token=params["token-value"])
        _api = cert(auth)

        s3_client = boto3.client("s3")
        cert_path = f"{cert_name}/fullchain.pem"
        key_path = f"{cert_name}/privkey.pem"

        # Fetch the raw cert and key data from S3
        cert_data = s3_client.get_object(Bucket=bucket_name, Key=cert_path)["Body"].read()
        key_data = s3_client.get_object(Bucket=bucket_name, Key=key_path)["Body"].read()

        job = upload_cert_to_tenant(
            _api=_api,
            name=cert_name,
            cert_data=cert_data,
            key_data=key_data,
            namespace="shared"
        )

        res = {
            "statusCode": 200,
            "body": job
        }

    except Exception as e:
        err = {
            "statusCode": 500,
            "body": f"Error: {e}"
        }
        print(err)
        raise RuntimeError(err)

    print(res)
    return res


def lambda_handler(event, context):
    """
    AWS Lambda entry point.
    """
    return main()


if __name__ == "__main__":
    main()