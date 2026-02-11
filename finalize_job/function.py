"""Write final job status to S3 and DynamoDB.

Called as the last step in the provisioning Step Functions workflow.
Converts the terminal Pass state (MarkComplete/MarkPartial/MarkFailed)
into an actual S3+DynamoDB write so the UDF service sees the final status.
"""

from typing import Any, Dict

from shared.decorators import lambda_handler
from shared.logging import StructuredLogger
from shared.state import StateManager, get_job_state_from_event


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

    return {"status": status, "dep_id": job_state.dep_id, "state_written": True}
