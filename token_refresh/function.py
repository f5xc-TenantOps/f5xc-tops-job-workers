"""
This module refreshes an F5 XC tenant token.
"""
import os
import boto3
from f5xc_tops_py_client import session, apicred


def get_parameters(parameters: list, region_name: str = "us-west-2") -> dict:
    """
    Fetch parameters from AWS Parameter Store.
    """
    aws = boto3.session.Session()
    ssm = aws.client("ssm", region_name=region_name)
    response = ssm.get_parameters(Names=parameters, WithDecryption=True)
    return {param["Name"].split("/")[-1]: param["Value"] for param in response["Parameters"]}


def refresh_token(_api, token_name: str, expiration_days: int = 7):
    """
    Refresh the F5 XC tenant token.
    """
    try:
        payload = _api.renew_payload(name=token_name, expiration_days=expiration_days)
        _api.renew(payload)
    except (KeyError, ValueError) as e:
        raise RuntimeError(f"Failed to renew token: {e}") from e


def main():
    """
    Main function to handle token refresh.
    """
    try:
        base_path = os.environ.get("SSM_BASE_PATH")
        if not base_path:
            raise RuntimeError("Environment variable SSM_BASE_PATH is not set.")

        region = boto3.session.Session().region_name or "us-west-2"
        params = get_parameters(
            [
                f"{base_path}/tenant-url",
                f"{base_path}/token-value",
                f"{base_path}/token-name",
            ],
            region_name=region,
        )

        auth = session(tenant_url=params["tenant-url"], api_token=params["token-value"])
        _api = apicred(auth)

        refresh_token(_api, params["token-name"], expiration_days=7)

        res = {
            "statusCode": 200,
            "body": f"Token {params['token-name']} refreshed successfully.",
        }
    except Exception as e:
        err = {
            "statusCode": 500,
            "body": f"Error: {e}",
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
