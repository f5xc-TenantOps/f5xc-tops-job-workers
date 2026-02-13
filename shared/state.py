"""State persistence for deployment workflows.

Manages state updates to S3 for UDF polling.
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3

from shared.job_state import JobState, JobStatus, StepStatus


# Status code → clean message for API errors
_API_STATUS_MESSAGES = {
    401: "Authentication failed — API credentials may be expired",
    403: "Permission denied",
    429: "Rate limited — too many API requests",
}


def _sanitize_error(msg: str) -> str:
    """Clean raw error messages for end-user display.

    Strips Python exception noise, internal service names,
    and raw API response bodies. Raw errors remain in Lambda
    logs (Loki) for debugging.
    """
    if not msg:
        return msg

    # Python tracebacks from Step Function Cause — check first since
    # tracebacks can contain API error messages on the last line
    if "Traceback" in msg or 'File "/' in msg:
        return "Internal error"

    # Step Function state machine errors (States.TaskFailed, States.Timeout, etc.)
    if re.search(r"States\.\w+", msg):
        return "Workflow error"

    # API errors — map status codes to clean messages
    api_match = re.search(r"API error (\d{3}):", msg)
    if api_match:
        status = int(api_match.group(1))
        if status in _API_STATUS_MESSAGES:
            return _API_STATUS_MESSAGES[status]
        if 400 <= status < 500:
            return "Configuration error"
        if status >= 500:
            return "Service temporarily unavailable"

    # Network connectivity
    if re.search(r"Network error:", msg):
        return "Service unreachable"

    # SSM parameter store
    if "Failed to fetch parameters" in msg:
        return "Configuration unavailable"

    # Lambda invocation failures — strip internal function names
    if re.match(r"Failed to invoke ", msg):
        return "Internal service error"

    # Resource creation wrapper — unwrap and re-sanitize the inner message
    creation_match = re.match(r"Resource creation failed:\s*(.*)", msg, re.DOTALL)
    if creation_match:
        return _sanitize_error(creation_match.group(1).strip())

    # General noise stripping for anything else
    cleaned = msg
    cleaned = re.sub(r"HTTPS?Connection(?:Pool)?\([^)]*\):\s*", "", cleaned)
    cleaned = re.sub(r"Max retries exceeded with url:\s*\S+\s*", "", cleaned)
    cleaned = re.sub(r"\(?Caused by\s*", "", cleaned)
    cleaned = re.sub(r"\w+Error\(['\"]?", "", cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    # Strip internal Lambda function names (tops-xxx-v2)
    cleaned = re.sub(r"tops-[\w-]+-v\d+", "service", cleaned)
    # Strip raw JSON blobs (50+ chars between braces)
    cleaned = re.sub(r"\{[^}]{50,}\}", "", cleaned)
    # Clean up stray punctuation
    cleaned = cleaned.strip("'\"() \n")
    cleaned = re.sub(r"^[,:]\s*", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = cleaned.strip()

    if not cleaned:
        return "Internal error"

    if len(cleaned) > 200:
        cleaned = cleaned[:200] + "..."

    return cleaned


def get_job_state_from_event(event: dict) -> Optional[JobState]:
    """Extract JobState from event if present.

    Args:
        event: Lambda event dict that may contain a job_state key.

    Returns:
        JobState instance if job_state data is present, None otherwise.
    """
    job_state_data = event.get("job_state")
    if not job_state_data:
        return None

    return JobState(
        job_execution_id=job_state_data["job_execution_id"],
        job_id=job_state_data["job_id"],
        trigger_source=job_state_data["trigger_source"],
        email=job_state_data["email"],
        petname=job_state_data["petname"],
        status=JobStatus(job_state_data.get("status", "IN_PROGRESS")),
        dep_id=job_state_data.get("dep_id"),
        steps=job_state_data.get("steps", {}),
        resources=job_state_data.get("resources", {}),
    )


def _build_s3_state(
    job_state: JobState,
    lab_id: Optional[str] = None,
    outputs: Optional[Dict[str, Any]] = None,
    errors: Optional[list] = None,
) -> Dict[str, Any]:
    """Build S3 state file content from JobState.

    Args:
        job_state: Current job state.
        lab_id: UDF lab identifier.
        outputs: Optional outputs dict (site_token, lb_hostname, etc.).
        errors: Optional list of error messages.

    Returns:
        Dict ready for JSON serialization to S3.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Convert steps to S3 format
    steps = {}
    for step_name, step_data in job_state.steps.items():
        step_entry = {"status": step_data.get("status", StepStatus.PENDING)}
        if isinstance(step_entry["status"], StepStatus):
            step_entry["status"] = step_entry["status"].value
        # Copy other fields (started_at, completed_at, name, etc.)
        for k, v in step_data.items():
            if k != "status":
                step_entry[k] = v
        # Sanitize error fields for end-user display
        if "error" in step_entry and isinstance(step_entry["error"], str):
            step_entry["error"] = _sanitize_error(step_entry["error"])
        steps[step_name] = step_entry

    # Convert resources to S3 format (same pattern as steps)
    resources = {}
    for res_name, res_data in job_state.resources.items():
        res_entry = {}
        for k, v in res_data.items():
            if isinstance(v, StepStatus):
                res_entry[k] = v.value
            else:
                res_entry[k] = v
        # Sanitize error fields for end-user display
        if "error" in res_entry and isinstance(res_entry["error"], str):
            res_entry["error"] = _sanitize_error(res_entry["error"])
        resources[res_name] = res_entry

    # Sanitize the errors list for end-user display
    sanitized_errors = [
        _sanitize_error(e) if isinstance(e, str) else e
        for e in (errors or [])
    ]

    status = job_state.status
    if isinstance(status, JobStatus):
        status = status.value

    state = {
        "dep_id": job_state.dep_id,
        "lab_id": lab_id,
        "petname": job_state.petname,
        "email": job_state.email,
        "status": status,
        "updated_at": now,
        "steps": steps,
        "resources": resources,
        "outputs": outputs or {},
        "errors": sanitized_errors,
    }

    if job_state.tenant_url:
        state["tenant_url"] = job_state.tenant_url

    return state


class StateManager:
    """Manages state persistence to S3.

    Usage:
        manager = StateManager(
            s3_bucket=os.environ["DEPLOYMENT_STATE_BUCKET"],
        )

        # After each step:
        manager.mark_step_started(job_state, "namespace")
        # ... do work ...
        manager.mark_step_complete(job_state, "namespace", name="fuzzy-cat")

        # Add outputs (for UDF polling):
        manager.add_output(job_state, "site_token", token_value, lab_id="648ecc3e")
    """

    def __init__(
        self,
        s3_bucket: Optional[str] = None,
    ):
        """Initialize StateManager.

        Args:
            s3_bucket: S3 bucket for deployment state files.
        """
        self.s3_bucket = s3_bucket or os.environ.get("DEPLOYMENT_STATE_BUCKET", "")

        self._s3 = boto3.client("s3")
        self._outputs: Dict[str, Dict[str, Any]] = {}  # job_execution_id -> outputs
        self._errors: Dict[str, list] = {}  # job_execution_id -> errors

    def update_state(
        self,
        job_state: JobState,
        lab_id: Optional[str] = None,
    ) -> None:
        """Write current state to S3.

        Args:
            job_state: Current job state to persist.
            lab_id: UDF lab identifier (required for S3 writes).
        """
        if job_state.trigger_source == "udf" and job_state.dep_id:
            self._write_to_s3(job_state, lab_id)

    def _write_to_s3(self, job_state: JobState, lab_id: Optional[str]) -> None:
        """Write state to S3 for UDF polling."""
        if not self.s3_bucket:
            return

        outputs = self._outputs.get(job_state.job_execution_id, {})
        errors = self._errors.get(job_state.job_execution_id, [])

        state = _build_s3_state(job_state, lab_id=lab_id, outputs=outputs, errors=errors)

        self._s3.put_object(
            Bucket=self.s3_bucket,
            Key=f"{job_state.dep_id}.json",
            Body=json.dumps(state, indent=2),
            ContentType="application/json",
        )

    def mark_step_started(
        self,
        job_state: JobState,
        step_name: str,
        lab_id: Optional[str] = None,
    ) -> None:
        """Mark a step as started (IN_PROGRESS).

        Args:
            job_state: Job state to update.
            step_name: Name of the step (e.g., "namespace", "user").
            lab_id: UDF lab identifier.
        """
        job_state.update_step(
            step_name,
            StepStatus.IN_PROGRESS,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self.update_state(job_state, lab_id=lab_id)

    def mark_step_complete(
        self,
        job_state: JobState,
        step_name: str,
        status: StepStatus = StepStatus.SUCCESS,
        lab_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Mark a step as complete.

        Args:
            job_state: Job state to update.
            step_name: Name of the step.
            status: Final status (SUCCESS, FAILED, SKIPPED).
            lab_id: UDF lab identifier.
            **kwargs: Additional metadata (name, error, etc.).
        """
        job_state.update_step(
            step_name,
            status,
            completed_at=datetime.now(timezone.utc).isoformat(),
            **kwargs,
        )
        self.update_state(job_state, lab_id=lab_id)

    def mark_step_failed(
        self,
        job_state: JobState,
        step_name: str,
        error: str,
        lab_id: Optional[str] = None,
    ) -> None:
        """Mark a step as failed.

        Args:
            job_state: Job state to update.
            step_name: Name of the step.
            error: Error message.
            lab_id: UDF lab identifier.
        """
        self.mark_step_complete(
            job_state, step_name, StepStatus.FAILED, lab_id=lab_id, error=error
        )

        # Track errors for S3 state
        if job_state.job_execution_id not in self._errors:
            self._errors[job_state.job_execution_id] = []
        self._errors[job_state.job_execution_id].append(error)

    def add_output(
        self,
        job_state: JobState,
        key: str,
        value: Any,
        lab_id: Optional[str] = None,
    ) -> None:
        """Add an output value (e.g., site_token, lb_hostname).

        Args:
            job_state: Job state to update.
            key: Output key name.
            value: Output value.
            lab_id: UDF lab identifier.
        """
        if job_state.job_execution_id not in self._outputs:
            self._outputs[job_state.job_execution_id] = {}
        self._outputs[job_state.job_execution_id][key] = value

        # Write immediately so UDF can poll for outputs
        self.update_state(job_state, lab_id=lab_id)

    def mark_job_complete(
        self,
        job_state: JobState,
        lab_id: Optional[str] = None,
    ) -> None:
        """Mark the entire job as COMPLETED.

        Args:
            job_state: Job state to update.
            lab_id: UDF lab identifier.
        """
        job_state.mark_completed()
        self.update_state(job_state, lab_id=lab_id)

    def mark_job_partial(
        self,
        job_state: JobState,
        lab_id: Optional[str] = None,
    ) -> None:
        """Mark the entire job as PARTIAL.

        Args:
            job_state: Job state to update.
            lab_id: UDF lab identifier.
        """
        job_state.mark_partial()
        self.update_state(job_state, lab_id=lab_id)

    def mark_job_failed(
        self,
        job_state: JobState,
        error: str,
        lab_id: Optional[str] = None,
    ) -> None:
        """Mark the entire job as FAILED.

        Args:
            job_state: Job state to update.
            error: Error message.
            lab_id: UDF lab identifier.
        """
        job_state.mark_failed(error)
        self.update_state(job_state, lab_id=lab_id)


# Module-level convenience functions for simpler usage
_default_manager: Optional[StateManager] = None


def get_state_manager() -> StateManager:
    """Get or create the default StateManager instance."""
    global _default_manager
    if _default_manager is None:
        _default_manager = StateManager()
    return _default_manager


def update_state(job_state: JobState, lab_id: Optional[str] = None) -> None:
    """Update state using the default manager."""
    get_state_manager().update_state(job_state, lab_id=lab_id)


def mark_step_started(
    job_state: JobState, step_name: str, lab_id: Optional[str] = None
) -> None:
    """Mark step started using the default manager."""
    get_state_manager().mark_step_started(job_state, step_name, lab_id=lab_id)


def mark_step_complete(
    job_state: JobState,
    step_name: str,
    status: StepStatus = StepStatus.SUCCESS,
    lab_id: Optional[str] = None,
    **kwargs,
) -> None:
    """Mark step complete using the default manager."""
    get_state_manager().mark_step_complete(
        job_state, step_name, status, lab_id=lab_id, **kwargs
    )


def mark_step_failed(
    job_state: JobState, step_name: str, error: str, lab_id: Optional[str] = None
) -> None:
    """Mark step failed using the default manager."""
    get_state_manager().mark_step_failed(job_state, step_name, error, lab_id=lab_id)


def add_output(
    job_state: JobState, key: str, value: Any, lab_id: Optional[str] = None
) -> None:
    """Add output using the default manager."""
    get_state_manager().add_output(job_state, key, value, lab_id=lab_id)


def serialize_job_state(job_state: JobState) -> Dict[str, Any]:
    """Serialize JobState to a dict for passing through Step Functions.

    Lambdas should include this in their return value so the workflow
    can forward the accumulated state to subsequent steps.
    """
    return {
        "job_execution_id": job_state.job_execution_id,
        "job_id": job_state.job_id,
        "trigger_source": job_state.trigger_source,
        "email": job_state.email,
        "petname": job_state.petname,
        "dep_id": job_state.dep_id,
        "status": job_state.status.value if isinstance(job_state.status, JobStatus) else job_state.status,
        "steps": {
            name: {k: v.value if isinstance(v, StepStatus) else v for k, v in data.items()}
            for name, data in job_state.steps.items()
        },
        "resources": {
            name: {k: v.value if isinstance(v, StepStatus) else v for k, v in data.items()}
            for name, data in job_state.resources.items()
        },
    }
