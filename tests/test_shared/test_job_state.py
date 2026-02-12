# tests/test_shared/test_job_state.py
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


