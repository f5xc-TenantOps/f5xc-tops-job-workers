import boto3
import json
from f5xc_tops_py_client.cred import APIcred

def get_parameters(parameter_names, region_name="us-east-1"):
    """
    Fetch parameters from AWS Parameter Store.

    Args:
        parameter_names (list): List of parameter names to fetch from the Parameter Store.
        region_name (str): AWS region where the Parameter Store is located. Default is 'us-west-2'.

    Returns:
        dict: A dictionary containing parameter names and their corresponding values.
    """
    session = boto3.session.Session()
    ssm = session.client("ssm", region_name=region_name)
    parameters = ssm.get_parameters(Names=parameter_names, WithDecryption=True)
    return {param['Name']: param['Value'] for param in parameters['Parameters']}

def refresh_token(tenant_url, token, expiration_days=7):
    """
    Refresh the F5 XC tenant token by building a payload and renewing it.

    Args:
        tenant_url (str): The URL of the F5 XC tenant.
        token (str): The current token for the tenant.
        expiration_days (int): The number of days before the token expires. Default is 7.

    Returns:
        str: The new refreshed token.
    """
    creds = APIcred(tenant_url, token)
    payload = creds.build_payload(expiration_days=expiration_days)
    return creds.renew(payload)

def main():
    """
    Main function to fetch parameters, refresh the token, and return a structured response.

    Returns:
        dict: A response dictionary containing statusCode, status, message, and the new token.
    """
    try:
        parameter_names = ["TenantURL", "Token"]
        region = boto3.session.Session().region_name or "us-west-2"
        params = get_parameters(parameter_names, region)
        tenant_url = params["TenantURL"]
        token = params["Token"]
        new_token = refresh_token(tenant_url, token, expiration_days=7)
        response = {
            "statusCode": 200,
            "status": "success",
            "message": "Token refreshed successfully",
            "new_token": new_token
        }
    except Exception as e:
        response = {
            "statusCode": 500,
            "status": "error",
            "message": str(e)
        }
    print(json.dumps(response))
    return response

def lambda_handler(event, context):
    """
    AWS Lambda entry point. Calls the main function.
    """
    return main()

if __name__ == "__main__":
    res = main()
    print(res)