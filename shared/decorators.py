"""Decorators for lambda functions.

Provides retry logic and standard handler wrapping with logging
and error handling.
"""

import json
import time
import uuid
from functools import wraps
from typing import Any, Callable, Optional

from .errors import PermanentError, RateLimitError, TransientError
from .logging import StructuredLogger


def with_retry(max_attempts: int = 3, backoff_base: int = 2) -> Callable:
    """Retry decorator for transient failures.

    Handles RateLimitError by sleeping for retry_after seconds.
    Handles TransientError with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts before giving up.
        backoff_base: Base for exponential backoff (delay = backoff_base ** attempt).

    Returns:
        Decorator function.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except RateLimitError as e:
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(e.retry_after)
                except TransientError:
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(backoff_base**attempt)

        return wrapper

    return decorator


def extract_correlation_id(event: dict) -> str:
    """Extract correlation_id from event or generate a new one.

    Checks for correlation_id in:
    1. Direct invocation payload (event["correlation_id"])
    2. SQS message body
    3. DynamoDB stream NewImage

    Args:
        event: Lambda event dict.

    Returns:
        Correlation ID string.
    """
    # From direct invocation payload
    if "correlation_id" in event:
        return event["correlation_id"]

    # From SQS message
    if "Records" in event and event["Records"]:
        record = event["Records"][0]
        if "body" in record:
            try:
                body = json.loads(record["body"])
                if "correlation_id" in body:
                    return body["correlation_id"]
            except (json.JSONDecodeError, TypeError):
                pass

    # From DynamoDB stream
    if "Records" in event and event["Records"]:
        record = event["Records"][0]
        if "dynamodb" in record:
            new_image = record["dynamodb"].get("NewImage", {})
            if "correlation_id" in new_image:
                return new_image["correlation_id"]["S"]

    # Generate new
    return str(uuid.uuid4())


def lambda_handler(func: Callable) -> Callable:
    """Wrap handler with logging, error handling, and response formatting.

    The wrapped function receives an additional logger argument:
        func(event, context, logger) -> result

    Args:
        func: Lambda handler function.

    Returns:
        Wrapped handler function.
    """

    @wraps(func)
    def wrapper(event: dict, context: Any) -> dict:
        correlation_id = extract_correlation_id(event)
        logger = StructuredLogger(
            service=context.function_name,
            correlation_id=correlation_id,
        )

        try:
            logger.info("Lambda invoked")
            result = func(event, context, logger)
            logger.info("Lambda completed", status="success")
            return {"statusCode": 200, "body": result}

        except PermanentError as e:
            logger.error("Permanent failure", error=str(e), error_type="permanent")
            return {"statusCode": 400, "body": str(e)}

        except (RateLimitError, TransientError) as e:
            logger.error("Transient failure", error=str(e), error_type="transient")
            raise  # Let infrastructure retry

        except Exception as e:
            logger.error("Unexpected error", error=str(e), error_type="unknown")
            raise

    return wrapper
