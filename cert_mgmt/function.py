"""
Manage wildcard certificate in a tenant.
"""
import os
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


def cert_exists(_api: cert, name: str, namespace: str = "shared") -> bool:
    """
    Check if a certificate exists in the tenant.
    """
    try:
        certs = _api.list(namespace)["items"]
        return any(c["name"] == name for c in certs)
    except Exception as e:
        raise RuntimeError(f"Unable to check certificate existence: {e}") from e


def upload_cert_to_tenant(_api: cert, name: str, cert_data: str, key_data: str, namespace: str = "shared") -> str:
    """
    Upload or update a certificate in the tenant.
    """
    try:
        payload = _api.create_payload(name=name, namespace=namespace, cert=cert_data, key=key_data)
        if cert_exists(_api, name, namespace):
            _api.replace(payload=payload, name=name, namespace=namespace)
            return f"Certificate '{name}' replaced in namespace '{namespace}'."
        else:
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
        if not base_path or not bucket_name:
            raise RuntimeError("Missing required environment variables: SSM_BASE_PATH or S3_BUCKET.")

        region = boto3.session.Session().region_name or "us-west-2"
        params = get_parameters(
            [
                f"{base_path}/wildcard-cert-name",
                f"{base_path}/tenant-url",
                f"{base_path}/token-value"
            ],
            region_name=region,
        )

        auth = session(tenant_url=params["tenant-url"], api_token=params["token-value"])
        _api = cert(auth)

        s3_client = boto3.client("s3")
        cert_path = f"{params[f'{base_path}/wildcard-cert-name']}/fullchain.pem"
        key_path = f"{params[f'{base_path}/wildcard-cert-name']}/privkey.pem"

        cert_data = s3_client.get_object(Bucket=bucket_name, Key=cert_path)["Body"].read().decode("utf-8")
        key_data = s3_client.get_object(Bucket=bucket_name, Key=key_path)["Body"].read().decode("utf-8")

        job = upload_cert_to_tenant(
            _api=_api,
            name=params[f"{base_path}/wildcard-cert-name"],
            cert_data=cert_data,
            key_data=key_data,
            namespace=params.get(f"{base_path}/wildcard-cert-ns", "shared")
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