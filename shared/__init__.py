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
    is_already_exists_error,
)
from .job_config import (
    JobConfig,
    UserConfig,
    NamespaceConfig,
    ResourceDefinition,
    validate_job_config,
    substitute_variables,
)
from .job_state import JobState, JobStatus, StepStatus
from .dependency_graph import (
    build_execution_order,
    DependencyCycleError,
    MissingDependencyError,
    DuplicateResourceError,
    InvalidResourceError,
)
from .logging import StructuredLogger
from .ssm import get_ssm_parameters
from .xc_client import XCClient
from .xc_operations import create_resource, delete_resource
from .state import (
    StateManager,
    get_state_manager,
    get_job_state_from_event,
    update_state,
    mark_step_started,
    mark_step_complete,
    add_output,
)

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
    "is_already_exists_error",
    # Decorators
    "with_retry",
    "lambda_handler",
    "extract_correlation_id",
    # Operations
    "create_resource",
    "delete_resource",
    # SSM
    "get_ssm_parameters",
    # XC Client
    "XCClient",
    # Job Config
    "JobConfig",
    "UserConfig",
    "NamespaceConfig",
    "ResourceDefinition",
    "validate_job_config",
    "substitute_variables",
    # Job State
    "JobState",
    "JobStatus",
    "StepStatus",
    # Dependency Graph
    "build_execution_order",
    "DependencyCycleError",
    "MissingDependencyError",
    "DuplicateResourceError",
    "InvalidResourceError",
    # State Management
    "StateManager",
    "get_state_manager",
    "get_job_state_from_event",
    "update_state",
    "mark_step_started",
    "mark_step_complete",
    "add_output",
]
