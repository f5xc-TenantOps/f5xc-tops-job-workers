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


def _update_deployment_record(dep_id: str, status: str, job_state, logger) -> None:
    """Update the deployment state record with final status and resource manifest.

    Writes deployment_status (COMPLETED or FAILED) and a unified resource
    manifest built from both job_state.steps and job_state.resources.
    Only SUCCESS items are included — failed resources have nothing to clean up.

    Non-fatal: if the write fails (e.g., record already TTL-deleted),
    we log a warning and continue — provisioning still succeeded.
    """
    step = logger.with_step("update_deployment_record")
    table_name = os.environ.get("DEPLOYMENT_STATE_TABLE")
    if not table_name:
        step.warn("DEPLOYMENT_STATE_TABLE not set, skipping deployment record update")
        return

    # Map finalize status to deployment_status
    deployment_status = "FAILED" if status == "FAILED" else "COMPLETED"

    # Build unified manifest from steps + resources (SUCCESS only)
    manifest = {}

    for step_name, step_data in job_state.steps.items():
        if step_data.get("status") == "SUCCESS":
            entry_name = step_data.get("name", step_name)
            manifest[entry_name] = {"type": step_name}

    for res_name, res_data in job_state.resources.items():
        if res_data.get("status") == "SUCCESS":
            manifest[res_name] = {"type": res_data.get("type", "unknown")}

    try:
        table = boto3.resource("dynamodb").Table(table_name)
        table.update_item(
            Key={"dep_id": dep_id},
            UpdateExpression="SET deployment_status = :s, resources = :r",
            ExpressionAttributeValues={
                ":s": deployment_status,
                ":r": manifest,
            },
        )
        step.info("Deployment record updated",
                   dep_id=dep_id,
                   deployment_status=deployment_status,
                   resource_count=len(manifest))
    except Exception as e:
        step.warn("Failed to update deployment record, continuing",
                   dep_id=dep_id, error=str(e))


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

    # Update deployment record with final status and resource manifest
    if job_state.dep_id:
        _update_deployment_record(job_state.dep_id, status, job_state, logger)

    return {"status": status, "dep_id": job_state.dep_id, "state_written": True}
