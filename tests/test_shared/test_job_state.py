# tests/test_shared/test_job_state.py
import pytest
from unittest.mock import MagicMock, patch
from shared.job_state import JobState, JobStatus, StepStatus


def test_job_state_creation():
    """Create a new job state."""
    state = JobState(
        job_execution_id="test-123",
        job_id="api-lab",
        trigger_source="udf",
        email="user@test.com",
        petname="fuzzy-cat"
    )
    assert state.status == JobStatus.PENDING
    assert state.steps == {}
    assert state.resources == {}


def test_job_state_update_step():
    """Update a step status."""
    state = JobState(
        job_execution_id="test-123",
        job_id="api-lab",
        trigger_source="udf",
        email="user@test.com",
        petname="fuzzy-cat"
    )
    state.update_step("namespace", StepStatus.SUCCESS, name="fuzzy-cat")
    assert state.steps["namespace"]["status"] == StepStatus.SUCCESS
    assert state.steps["namespace"]["name"] == "fuzzy-cat"


def test_job_state_update_resource():
    """Update a resource status."""
    state = JobState(
        job_execution_id="test-123",
        job_id="api-lab",
        trigger_source="udf",
        email="user@test.com",
        petname="fuzzy-cat"
    )
    state.update_resource(
        "fuzzy-cat-pool",
        StepStatus.SUCCESS,
        resource_type="origin_pool",
        namespace="fuzzy-cat"
    )
    assert state.resources["fuzzy-cat-pool"]["status"] == StepStatus.SUCCESS
    assert state.resources["fuzzy-cat-pool"]["resource_type"] == "origin_pool"


def test_job_state_to_dynamodb_item():
    """Convert job state to DynamoDB item format."""
    state = JobState(
        job_execution_id="test-123",
        job_id="api-lab",
        trigger_source="udf",
        email="user@test.com",
        petname="fuzzy-cat"
    )
    state.update_step("namespace", StepStatus.SUCCESS)
    item = state.to_dynamodb_item()
    assert item["job_execution_id"]["S"] == "test-123"
    assert item["status"]["S"] == "PENDING"


def test_job_state_from_dynamodb_item():
    """Create job state from DynamoDB item."""
    item = {
        "job_execution_id": {"S": "test-123"},
        "job_id": {"S": "api-lab"},
        "trigger_source": {"S": "udf"},
        "email": {"S": "user@test.com"},
        "petname": {"S": "fuzzy-cat"},
        "status": {"S": "IN_PROGRESS"},
        "steps": {"M": {}},
        "resources": {"M": {}}
    }
    state = JobState.from_dynamodb_item(item)
    assert state.job_execution_id == "test-123"
    assert state.status == JobStatus.IN_PROGRESS
