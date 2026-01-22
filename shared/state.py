"""State persistence for deployment workflows.

Manages state updates to S3 (for UDF polling) and DynamoDB (for portal visibility).
S3 writes only occur for UDF-triggered jobs; DynamoDB writes occur for all jobs.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3

from shared.job_state import JobState, JobStatus, StepStatus


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
        steps[step_name] = step_entry

    status = job_state.status
    if isinstance(status, JobStatus):
        status = status.value

    return {
        "dep_id": job_state.dep_id,
        "lab_id": lab_id,
        "petname": job_state.petname,
        "email": job_state.email,
        "status": status,
        "updated_at": now,
        "steps": steps,
        "outputs": outputs or {},
        "errors": errors or [],
    }


def _build_dynamodb_item(job_state: JobState) -> Dict[str, Any]:
    """Build DynamoDB item from JobState.

    Uses native Python types (boto3 resource handles serialization).
    """
    import time

    item = {
        "job_execution_id": job_state.job_execution_id,
        "job_id": job_state.job_id,
        "trigger_source": job_state.trigger_source,
        "email": job_state.email,
        "petname": job_state.petname,
        "status": job_state.status.value if isinstance(job_state.status, JobStatus) else job_state.status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "ttl": int(time.time()) + (7 * 24 * 60 * 60),  # 7 days
    }

    if job_state.dep_id:
        item["dep_id"] = job_state.dep_id
    if job_state.tenant_url:
        item["tenant_url"] = job_state.tenant_url
    if job_state.step_function_execution_arn:
        item["step_function_execution_arn"] = job_state.step_function_execution_arn
    if job_state.error:
        item["error"] = job_state.error

    # Convert steps
    if job_state.steps:
        steps = {}
        for step_name, step_data in job_state.steps.items():
            step_entry = {}
            for k, v in step_data.items():
                if isinstance(v, StepStatus):
                    step_entry[k] = v.value
                else:
                    step_entry[k] = v
            steps[step_name] = step_entry
        item["steps"] = steps

    # Convert resources
    if job_state.resources:
        resources = {}
        for res_name, res_data in job_state.resources.items():
            res_entry = {}
            for k, v in res_data.items():
                if isinstance(v, StepStatus):
                    res_entry[k] = v.value
                else:
                    res_entry[k] = v
            resources[res_name] = res_entry
        item["resources"] = resources

    return item


class StateManager:
    """Manages state persistence to S3 and DynamoDB.

    Usage:
        manager = StateManager(
            s3_bucket=os.environ["DEPLOYMENT_STATE_BUCKET"],
            dynamodb_table=os.environ["JOB_STATE_TABLE"]
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
        dynamodb_table: Optional[str] = None,
    ):
        """Initialize StateManager.

        Args:
            s3_bucket: S3 bucket for deployment state files.
            dynamodb_table: DynamoDB table for job state.
        """
        self.s3_bucket = s3_bucket or os.environ.get("DEPLOYMENT_STATE_BUCKET", "")
        self.dynamodb_table = dynamodb_table or os.environ.get("JOB_STATE_TABLE", "")

        self._s3 = boto3.client("s3")
        self._dynamodb = boto3.resource("dynamodb")
        self._outputs: Dict[str, Dict[str, Any]] = {}  # job_execution_id -> outputs
        self._errors: Dict[str, list] = {}  # job_execution_id -> errors

    def update_state(
        self,
        job_state: JobState,
        lab_id: Optional[str] = None,
    ) -> None:
        """Write current state to persistence stores.

        Args:
            job_state: Current job state to persist.
            lab_id: UDF lab identifier (required for S3 writes).
        """
        # Always write to DynamoDB
        self._write_to_dynamodb(job_state)

        # Only write to S3 for UDF-triggered jobs
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

    def _write_to_dynamodb(self, job_state: JobState) -> None:
        """Write state to DynamoDB."""
        if not self.dynamodb_table:
            return

        table = self._dynamodb.Table(self.dynamodb_table)
        item = _build_dynamodb_item(job_state)
        table.put_item(Item=item)

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


def add_output(
    job_state: JobState, key: str, value: Any, lab_id: Optional[str] = None
) -> None:
    """Add output using the default manager."""
    get_state_manager().add_output(job_state, key, value, lab_id=lab_id)
