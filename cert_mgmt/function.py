"""
Manage wildcard cert in a tenant
Use certmanager to generate cert, write to S3, and upload to F5 Distributed Cloud tenant.
"""
# pylint: disable=import-error
import os
import boto3
from f5xc_tops_py_client import session, cert


def get_parameters(parameters: list, region_name: str = "us-west-2") -> dict:
    """
    Fetch parameters from AWS Parameter Store.

    Args:
        parameters (list): List of parameter names to fetch.
        region_name (str): AWS region name.

    Returns:
        dict: A dictionary containing parameter names and their values.
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
    Determine if a certificate already exists in the tenant.

    Args:
        _api (cert): F5 Distributed Cloud cert API instance.
        name (str): Name of the certificate.
        namespace (str): Namespace to check for the certificate.

    Returns:
        bool: True if the certificate exists, False otherwise.
    """
    try:
        certs = _api.list(namespace)["items"]
        return any(c["name"] == name for c in certs)
    except Exception as e:
        raise RuntimeError(f"Unable to check if certificate exists: {e}") from e


def upload_cert_to_tenant(
        _api: cert,
        name: str,
        cert_data: str,
        key_data: str,
        namespace: str = "shared") -> str:
    """
    Upload or update a certificate in the tenant.

    Args:
        _api (cert): F5 Distributed Cloud cert API instance.
        name (str): Name of the certificate.
        cert_data (str): Base64-encoded certificate data.
        key_data (str): Base64-encoded private key data.
        namespace (str): Namespace for the certificate.
    """
    try:
        payload = _api.create_payload(name=name, namespace=namespace, cert=cert_data, key=key_data)
        if cert_exists(_api, name, namespace):
            _api.replace(payload=payload, name=name, namespace=namespace)
            r = f"Certificate '{name}' replaced in namespace '{namespace}'."
        else:
            _api.create(payload=payload, namespace=namespace)
            r = f"Certificate '{name}' created in namespace '{namespace}'."
    except Exception as e:
        raise RuntimeError(f"Failed to upload or update certificate: {e}") from e
    return r


def main():
    """
    Main function to manage wildcard cert in a tenant.

    Returns:
        dict: A response dictionary containing statusCode and message.
    """
    try:
        # Load environment variables and fetch required parameters
        try:
            base_path = os.environ.get("SSM_BASE_PATH")
            if not base_path:
                raise RuntimeError("Environment variable 'SSM_BASE_PATH' is not set.")

            region = boto3.session.Session().region_name or "us-west-2"
            param_names = [
                f"{base_path}/wildcard-cert-name",
                f"{base_path}/wildcard-cert-ns",
                f"{base_path}/tenant-url",
                f"{base_path}/token-value"
            ]
            params = get_parameters(param_names, region_name=region)
        except Exception as e:
            raise RuntimeError(f"Error fetching parameters from AWS Parameter Store: {e}") from e

        # Authenticate with the tenant
        try:
            auth = session(tenant_url=params["tenant-url"], api_token=params["token-value"])
            _api = cert(auth)
        except KeyError as e:
            raise RuntimeError(f"Missing required parameter for tenant authentication: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Error creating API session: {e}") from e

        # Retrieve the certificate and key from S3
        try:
            s3_client = boto3.client("s3")
            bucket_name = os.environ.get("S3_BUCKET")
            if not bucket_name:
                raise RuntimeError("Environment variable 'S3_BUCKET' is not set.")

            cert_path = f"{params[f'{base_path}/wildcard-cert-name']}/fullchain.pem"
            key_path = f"{params[f'{base_path}/wildcard-cert-name']}/privkey.pem"

            cert_data = s3_client.get_object(Bucket=bucket_name, Key=cert_path)["Body"].read().decode("utf-8")
            key_data = s3_client.get_object(Bucket=bucket_name, Key=key_path)["Body"].read().decode("utf-8")
        except boto3.exceptions.Boto3Error as e:
            raise RuntimeError(f"Error accessing S3 bucket '{bucket_name}': {e}") from e
        except KeyError as e:
            raise RuntimeError(f"Missing required certificate paths: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Error fetching certificate data from S3: {e}") from e

        # Upload or update the certificate in the tenant
        try:
            job = upload_cert_to_tenant(
                _api=_api,
                name=params[f"{base_path}/wildcard-cert-name"],
                cert_data=cert_data,
                key_data=key_data,
                namespace=params.get(f"{base_path}/wildcard-cert-ns", "shared")
            )
        except Exception as e:
            raise RuntimeError(f"Error uploading certificate to tenant: {e}") from e

        res = {
            "statusCode": 200,
            "body": job
        }

    except Exception as e:
        # Catch all exceptions with detailed messages
        res = {
            "statusCode": 500,
            "body": f"An error occurred: {e}"
        }

    print(res)
    return res


def lambda_handler(event, context):
    """
    AWS Lambda entry point.
    """
    return main()

if __name__ == "__main__":
    print(main())
