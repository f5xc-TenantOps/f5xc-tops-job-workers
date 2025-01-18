"""
This module refreshes an F5 XC tenant token.
"""
# pylint: disable=import-error
import os
import boto3
from f5xc_tops_py_client import session, apicred

def get_parameters(parameters: list, region_name: str="us-west-2"):
    """
    Fetch parameters from AWS Parameter Store.

    Returns:
        dict: A dictionary containing $parameters.
    """
    aws = boto3.session.Session()
    ssm = aws.client("ssm", region_name=region_name)
    parameters = ssm.get_parameters(Names=parameters, WithDecryption=True)
    return {param['Name'].split('/')[-1]: param['Value'] for param in parameters['Parameters']}

def refresh_token(_api, token_name: str, expiration_days: int=7):
    """
    Refresh the F5 XC tenant token by building a payload and renewing it.
    """
    try:
        payload = _api.renew_payload(name=token_name, expiration_days=expiration_days)
        _api.renew(payload)
    except (KeyError, ValueError) as e:
        raise RuntimeError(f"Failed renew cred: {e}") from e

def main():
    """
    Main function to refresh the token.

    Returns:
        dict: A response dictionary containing statusCode, status, and message.
    """
    try:
        try:
            base_path = os.environ.get("SSM_BASE_PATH")
            region = boto3.session.Session().region_name or "us-west-2"
            params = get_parameters(
                [f"{base_path}/tenant-url",
                 f"{base_path}/token-value",
                 f"{base_path}/token-name"],
                 region_name=region)
        except boto3.exceptions.Boto3Error as e:
            raise RuntimeError(f"Failed to get parameters: {e}") from e

        try:
            auth = session(tenant_url=params['tenant-url'], api_token=params['token-value'])
            _api = apicred(auth)
        except (KeyError, ValueError) as e:
            raise RuntimeError(f"Failed to create API session: {e}") from e

        try:
            refresh_token(_api, params['token-name'], expiration_days=7)
        except (KeyError, ValueError) as e:
            raise RuntimeError(f"Failed to refresh token: {e}") from e

        res = {
            "statusCode": 200,
            "status": "success",
            "message": "Token refreshed successfully"
        }
    except (boto3.exceptions.Boto3Error, KeyError, ValueError) as e:
        res = {
            "statusCode": 500,
            "status": "error",
            "message": str(e)
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
