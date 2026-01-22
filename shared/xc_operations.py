"""Idempotent operation wrappers for XC API calls.

These are template functions that demonstrate the check-before-create
and succeed-on-not-found patterns. Lambda functions will customize
these patterns for their specific resource types.
"""

from typing import Any, Dict

from .decorators import with_retry
from .errors import (
    AmbiguousError,
    ResourceExistsError,
    ResourceNotFoundError,
    TransientError,
)
from .logging import StructuredLogger


@with_retry(max_attempts=3)
def create_resource(
    xc_client: Any,
    resource_type: str,
    metadata: Dict[str, Any],
    spec: Dict[str, Any],
    logger: StructuredLogger,
) -> Dict[str, Any]:
    """Idempotent resource creation.

    Implements check-before-create pattern to ensure idempotency.
    Handles 409 conflicts and 500 ambiguous errors by checking
    if the resource exists.

    Args:
        xc_client: XC API client with get(), create() methods.
        resource_type: Type of resource to create.
        metadata: Resource metadata including name and namespace.
        spec: Resource specification.
        logger: Structured logger for the operation.

    Returns:
        Dict with status, name, and whether resource was created or already existed.

    Raises:
        TransientError: If create fails and resource doesn't exist.
        PermanentError: If create fails with a permanent error.
    """
    name = metadata["name"]
    namespace = metadata["namespace"]
    step = logger.with_step(f"create_{resource_type}")

    # 1. Check if resource already exists
    try:
        existing = xc_client.get(resource_type, name, namespace)
        step.info(
            "Resource already exists, treating as success",
            name=name,
            already_existed=True,
        )
        return {"status": "success", "already_existed": True, "name": name}
    except ResourceNotFoundError:
        pass  # Expected - proceed with create

    # 2. Create resource
    try:
        response = xc_client.create(
            resource_type, {"metadata": metadata, "spec": spec}
        )
        step.info("Resource created", name=name)
        return {"status": "success", "created": True, "name": name}

    except ResourceExistsError:
        # Race condition: created between our check and create
        step.info("Resource created by concurrent process", name=name)
        return {"status": "success", "already_existed": True, "name": name}

    except AmbiguousError as e:
        # 500 response - might have been created before error
        step.warn("Ambiguous response, checking if resource exists", error=str(e))
        try:
            existing = xc_client.get(resource_type, name, namespace)
            step.info(
                "Resource exists after ambiguous error, treating as success",
                name=name,
            )
            return {"status": "success", "already_existed": True, "name": name}
        except ResourceNotFoundError:
            # Truly failed
            raise TransientError(f"Create failed with ambiguous error: {e}")


@with_retry(max_attempts=3)
def delete_resource(
    xc_client: Any,
    resource_type: str,
    name: str,
    namespace: str,
    logger: StructuredLogger,
) -> Dict[str, Any]:
    """Idempotent resource deletion.

    Treats 404 (not found) as success since the resource is already gone.
    Handles 500 ambiguous errors by checking if the resource still exists.

    Args:
        xc_client: XC API client with get(), delete() methods.
        resource_type: Type of resource to delete.
        name: Resource name.
        namespace: Resource namespace.
        logger: Structured logger for the operation.

    Returns:
        Dict with status, name, and whether resource was deleted or already gone.

    Raises:
        TransientError: If delete fails and resource still exists.
        PermanentError: If delete fails with a permanent error.
    """
    step = logger.with_step(f"delete_{resource_type}")

    try:
        xc_client.delete(resource_type, name, namespace)
        step.info("Resource deleted", name=name)
        return {"status": "success", "deleted": True, "name": name}

    except ResourceNotFoundError:
        # Already deleted (or never existed) - this is success
        step.info("Resource not found, treating delete as success", name=name)
        return {"status": "success", "already_deleted": True, "name": name}

    except AmbiguousError as e:
        # 500 response - check if actually deleted
        step.warn(
            "Ambiguous response on delete, checking if resource exists",
            error=str(e),
        )
        try:
            xc_client.get(resource_type, name, namespace)
            # Still exists - delete failed
            raise TransientError(f"Delete failed with ambiguous error: {e}")
        except ResourceNotFoundError:
            # Gone - delete succeeded
            step.info(
                "Resource gone after ambiguous error, treating as success",
                name=name,
            )
            return {"status": "success", "deleted": True, "name": name}
