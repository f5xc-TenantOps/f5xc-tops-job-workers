"""Job state tracking for provisioning workflows."""

import json
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

    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format."""
        item = {
            "job_execution_id": {"S": self.job_execution_id},
            "job_id": {"S": self.job_id},
            "trigger_source": {"S": self.trigger_source},
            "email": {"S": self.email},
            "petname": {"S": self.petname},
            "status": {"S": self.status.value if isinstance(self.status, JobStatus) else self.status},
            "steps": {"M": self._dict_to_dynamodb_map(self.steps)},
            "resources": {"M": self._dict_to_dynamodb_map(self.resources)},
        }
        if self.dep_id:
            item["dep_id"] = {"S": self.dep_id}
        if self.tenant_url:
            item["tenant_url"] = {"S": self.tenant_url}
        if self.step_function_execution_arn:
            item["step_function_execution_arn"] = {"S": self.step_function_execution_arn}
        if self.error:
            item["error"] = {"S": self.error}
        return item

    @classmethod
    def from_dynamodb_item(cls, item: Dict[str, Any]) -> "JobState":
        """Create JobState from DynamoDB item."""
        return cls(
            job_execution_id=item["job_execution_id"]["S"],
            job_id=item["job_id"]["S"],
            trigger_source=item["trigger_source"]["S"],
            email=item["email"]["S"],
            petname=item["petname"]["S"],
            status=JobStatus(item["status"]["S"]),
            dep_id=item.get("dep_id", {}).get("S"),
            tenant_url=item.get("tenant_url", {}).get("S"),
            step_function_execution_arn=item.get("step_function_execution_arn", {}).get("S"),
            steps=cls._dynamodb_map_to_dict(item.get("steps", {}).get("M", {})),
            resources=cls._dynamodb_map_to_dict(item.get("resources", {}).get("M", {})),
            error=item.get("error", {}).get("S"),
        )

    @staticmethod
    def _dict_to_dynamodb_map(d: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a nested dict to DynamoDB map format."""
        result = {}
        for k, v in d.items():
            if isinstance(v, dict):
                inner = {}
                for ik, iv in v.items():
                    if isinstance(iv, StepStatus):
                        inner[ik] = {"S": iv.value}
                    elif isinstance(iv, str):
                        inner[ik] = {"S": iv}
                    elif isinstance(iv, bool):
                        inner[ik] = {"BOOL": iv}
                    elif isinstance(iv, (int, float)):
                        inner[ik] = {"N": str(iv)}
                result[k] = {"M": inner}
        return result

    @staticmethod
    def _dynamodb_map_to_dict(m: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Convert DynamoDB map to nested dict."""
        result = {}
        for k, v in m.items():
            if "M" in v:
                inner = {}
                for ik, iv in v["M"].items():
                    if "S" in iv:
                        inner[ik] = iv["S"]
                    elif "N" in iv:
                        inner[ik] = float(iv["N"])
                    elif "BOOL" in iv:
                        inner[ik] = iv["BOOL"]
                result[k] = inner
        return result
