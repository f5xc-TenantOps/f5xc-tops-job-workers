"""Error types for lambda functions.

These error types map to specific HTTP status codes and determine
retry behavior in the lambda handler decorator.
"""


class RateLimitError(Exception):
    """429 - Too Many Requests.

    Raised when the API returns 429. The retry_after value should
    be respected (from Retry-After header, or default 30s).
    """

    def __init__(self, message: str, retry_after: int = 30):
        super().__init__(message)
        self.retry_after = retry_after


class TransientError(Exception):
    """502/503/504 - Transient server errors.

    Raised for gateway errors that are likely to resolve with retry.
    These should be retried with exponential backoff.
    """

    pass


class PermanentError(Exception):
    """400/403 - Permanent client errors.

    Raised for errors that won't be resolved by retrying.
    These should fail fast and go to DLQ.
    """

    pass


class AmbiguousError(Exception):
    """500 - Internal server error.

    Raised when the server returns 500. The operation may or may not
    have succeeded. Callers should check resource state before deciding
    how to handle.
    """

    pass


class ResourceNotFoundError(Exception):
    """404 - Resource does not exist.

    For DELETE operations, this is typically treated as success
    (resource is already gone).
    """

    pass


class ResourceExistsError(Exception):
    """409 - Resource already exists (conflict).

    For CREATE operations, this may indicate a race condition where
    another process created the resource. Typically treated as success.
    """

    pass


def is_already_exists_error(exception: Exception) -> bool:
    """Check if an exception indicates the resource already exists.

    Checks for:
    - Common error message patterns ("already exist", "duplicate", "conflict")
    - HTTP 409 status code via exception.status_code
    - HTTP 409 status code via exception.response.status_code

    Args:
        exception: The exception to check.

    Returns:
        True if the exception indicates the resource already exists.
    """
    error_msg = str(exception).lower()
    patterns = ["already exist", "already exists", "duplicate", "conflict"]
    if any(pattern in error_msg for pattern in patterns):
        return True
    if getattr(exception, 'status_code', None) == 409:
        return True
    response = getattr(exception, 'response', None)
    if response is not None and getattr(response, 'status_code', None) == 409:
        return True
    return False
