"""AWS SSM Parameter Store utilities."""

from .errors import PermanentError, TransientError


def get_ssm_parameters(parameters: list, region_name: str = None) -> dict:
    """Fetch parameters from AWS Parameter Store.

    Args:
        parameters: List of parameter names to fetch.
        region_name: AWS region name. If None, detects from boto3 session
                     and falls back to "us-east-1".

    Returns:
        Dict mapping parameter short names to values.

    Raises:
        PermanentError: If parameters are invalid or missing (config error).
        TransientError: If fetching parameters fails (API error).
    """
    import boto3
    try:
        aws = boto3.session.Session()
        if region_name is None:
            region_name = aws.region_name or "us-east-1"
        ssm = aws.client("ssm", region_name=region_name)
        response = ssm.get_parameters(Names=parameters, WithDecryption=True)

        invalid = response.get("InvalidParameters", [])
        if invalid:
            raise PermanentError(
                f"SSM parameters not found: {', '.join(invalid)}"
            )

        result = {param["Name"].split("/")[-1]: param["Value"] for param in response["Parameters"]}

        missing = [p for p in parameters if p.split("/")[-1] not in result]
        if missing:
            raise PermanentError(
                f"SSM parameters missing from response: {', '.join(missing)}"
            )

        return result
    except PermanentError:
        raise
    except Exception as e:
        raise TransientError(f"Failed to fetch parameters: {e}") from e
