"""Job state tracking for provisioning workflows."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class JobStatus(str, Enum):
    """Overall job status."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class StepStatus(str, Enum):
    """Individual step/resource status."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass
class JobState:
    """Tracks the state of a provisioning job execution."""
    job_execution_id: str
    job_id: str
    trigger_source: str
    email: str
    petname: str
    status: JobStatus = JobStatus.PENDING
    dep_id: Optional[str] = None
    tenant_url: Optional[str] = None
    step_function_execution_arn: Optional[str] = None
    steps: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    resources: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    error: Optional[str] = None

    def update_step(self, step_name: str, status: StepStatus, **kwargs) -> None:
        """Update a step's status and metadata."""
        self.steps[step_name] = {"status": status, **kwargs}

    def update_resource(self, resource_name: str, status: StepStatus, **kwargs) -> None:
        """Update a resource's status and metadata."""
        self.resources[resource_name] = {"status": status, **kwargs}

    def mark_in_progress(self) -> None:
        """Mark job as in progress."""
        self.status = JobStatus.IN_PROGRESS

    def mark_completed(self) -> None:
        """Mark job as completed."""
        self.status = JobStatus.COMPLETED

    def mark_failed(self, error: str) -> None:
        """Mark job as failed with error message."""
        self.status = JobStatus.FAILED
        self.error = error
