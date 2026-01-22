"""Shared module for lambda normalization.

This module provides common utilities for all lambda functions:
- Structured logging with correlation IDs
- Error types for retry classification
- Decorators for standard handler patterns
- Idempotent operation wrappers for XC API calls
"""

from .decorators import extract_correlation_id, lambda_handler, with_retry
from .errors import (
    AmbiguousError,
    PermanentError,
    RateLimitError,
    ResourceExistsError,
    ResourceNotFoundError,
    TransientError,
)
from .logging import StructuredLogger
from .xc_operations import create_resource, delete_resource

__all__ = [
    # Logging
    "StructuredLogger",
    # Errors
    "RateLimitError",
    "TransientError",
    "PermanentError",
    "AmbiguousError",
    "ResourceNotFoundError",
    "ResourceExistsError",
    # Decorators
    "with_retry",
    "lambda_handler",
    "extract_correlation_id",
    # Operations
    "create_resource",
    "delete_resource",
]
