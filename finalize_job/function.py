"""Write final job status to S3 and DynamoDB.

Called as the last step in the provisioning Step Functions workflow.
Converts the terminal Pass state (MarkComplete/MarkPartial/MarkFailed)
into an actual S3+DynamoDB write so the UDF service sees the final status.
"""

import os
from typing import Any, Dict

import boto3

from shared.decorators import lambda_handler
from shared.logging import StructuredLogger
from shared.state import StateManager, get_job_state_from_event


def _write_cleanup_manifest(dep_id: str, resources: Dict[str, Dict[str, Any]], logger) -> None:
    """Write a simplified resource manifest to the deployment state record.

    The manifest stores only {name: {type: "..."}} so the cleanup workflow
    knows what was provisioned without needing the full job state.

    Non-fatal: if the write fails (e.g., record already TTL-deleted),
    we log a warning and continue — provisioning still succeeded.
    """
    step = logger.with_step("write_cleanup_manifest")
    table_name = os.environ.get("DEPLOYMENT_STATE_TABLE")
    if not table_name:
        step.warn("DEPLOYMENT_STATE_TABLE not set, skipping cleanup manifest write")
        return

    # Build simplified manifest: {name: {type: "..."}}
    manifest = {}
    for name, data in resources.items():
        resource_type = data.get("type", data.get("resource_type", "unknown"))
        manifest[name] = {"type": resource_type}

    if not manifest:
        step.info("No resources to write to cleanup manifest", dep_id=dep_id)
        return

    try:
        table = boto3.resource("dynamodb").Table(table_name)
        table.update_item(
            Key={"dep_id": dep_id},
            UpdateExpression="SET resources = :r",
            ExpressionAttributeValues={":r": manifest},
        )
        step.info("Cleanup manifest written", dep_id=dep_id, resource_count=len(manifest))
    except Exception as e:
        step.warn("Failed to write cleanup manifest, continuing", dep_id=dep_id, error=str(e))


@lambda_handler
def handler(event: Dict[str, Any], context, logger: StructuredLogger) -> Dict[str, Any]:
    """Lambda entry point.

    Expects event with:
        status: "COMPLETED", "PARTIAL", or "FAILED"
        job_state: JobState dict (from workflow)
        lab_id: UDF lab identifier (optional)
        dep_id: deployment ID (optional)
        error: error details (for FAILED status)
    """
    step = logger.with_step("finalize_job")

    status = event.get("status", "COMPLETED")
    lab_id = event.get("lab_id")
    job_state = get_job_state_from_event(event)

    if not job_state:
        step.warn("No job_state in event, skipping state write", status=status)
        return {"status": status, "state_written": False}

    manager = StateManager()

    if status == "FAILED":
        error = event.get("error", {})
        error_msg = error.get("Cause", str(error)) if isinstance(error, dict) else str(error)
        step.info("Marking job failed", dep_id=job_state.dep_id, error=error_msg)
        manager.mark_job_failed(job_state, error=error_msg, lab_id=lab_id)
    else:
        step.info("Marking job complete", dep_id=job_state.dep_id, status=status)
        manager.mark_job_complete(job_state, lab_id=lab_id)

    # Write cleanup manifest to deployment state record
    if job_state.dep_id and job_state.resources:
        _write_cleanup_manifest(job_state.dep_id, job_state.resources, logger)

    return {"status": status, "dep_id": job_state.dep_id, "state_written": True}
