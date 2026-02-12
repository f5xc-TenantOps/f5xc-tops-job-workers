# tests/test_shared/test_state.py
"""Tests for state persistence module."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from shared.job_state import JobState, JobStatus, StepStatus
from shared.state import (
    StateManager,
    _build_s3_state,
)


class TestBuildS3State:
    """Tests for S3 state file building."""

    def test_build_s3_state_minimal(self):
        """Build S3 state with minimal job state."""
        job_state = JobState(
            job_execution_id="exec-123",
            job_id="job-456",
            trigger_source="udf",
            email="user@example.com",
            petname="fuzzy-cat",
            dep_id="dep-789",
            status=JobStatus.IN_PROGRESS,
        )

        result = _build_s3_state(job_state, lab_id="lab-001")

        assert result["dep_id"] == "dep-789"
        assert result["lab_id"] == "lab-001"
        assert result["petname"] == "fuzzy-cat"
        assert result["email"] == "user@example.com"
        assert result["status"] == "IN_PROGRESS"
        assert result["steps"] == {}
        assert result["outputs"] == {}
        assert result["errors"] == []
        assert "updated_at" in result

    def test_build_s3_state_with_steps(self):
        """Build S3 state with step data."""
        job_state = JobState(
            job_execution_id="exec-123",
            job_id="job-456",
            trigger_source="udf",
            email="user@example.com",
            petname="fuzzy-cat",
            dep_id="dep-789",
            status=JobStatus.IN_PROGRESS,
        )
        job_state.update_step("namespace", StepStatus.SUCCESS, name="fuzzy-cat")
        job_state.update_step("user", StepStatus.IN_PROGRESS)

        result = _build_s3_state(job_state, lab_id="lab-001")

        assert result["steps"]["namespace"]["status"] == "SUCCESS"
        assert result["steps"]["user"]["status"] == "IN_PROGRESS"


class TestStateManager:
    """Tests for StateManager class."""

    def test_init_creates_clients(self):
        """StateManager initializes boto3 clients."""
        with patch("shared.state.boto3") as mock_boto:
            manager = StateManager(
                s3_bucket="test-bucket",
            )
            assert manager.s3_bucket == "test-bucket"

    def test_update_state_udf_writes_s3(self):
        """UDF trigger writes to S3."""
        with patch("shared.state.boto3") as mock_boto:
            mock_s3 = MagicMock()
            mock_boto.client.return_value = mock_s3

            manager = StateManager(
                s3_bucket="test-bucket",
            )

            job_state = JobState(
                job_execution_id="exec-123",
                job_id="job-456",
                trigger_source="udf",
                email="user@example.com",
                petname="fuzzy-cat",
                dep_id="dep-789",
                status=JobStatus.IN_PROGRESS,
            )

            manager.update_state(job_state, lab_id="lab-001")

            # Verify S3 write
            mock_s3.put_object.assert_called_once()
            call_args = mock_s3.put_object.call_args
            assert call_args.kwargs["Bucket"] == "test-bucket"
            assert call_args.kwargs["Key"] == "dep-789.json"

    def test_update_state_non_udf_skips_s3(self):
        """Non-UDF trigger does not write to S3."""
        with patch("shared.state.boto3") as mock_boto:
            mock_s3 = MagicMock()
            mock_boto.client.return_value = mock_s3

            manager = StateManager(
                s3_bucket="test-bucket",
            )

            job_state = JobState(
                job_execution_id="exec-123",
                job_id="aad-sync-default",
                trigger_source="aad_sync",
                email="user@example.com",
                petname="fuzzy-cat",
                status=JobStatus.IN_PROGRESS,
            )

            manager.update_state(job_state)

            # Verify NO S3 write
            mock_s3.put_object.assert_not_called()


class TestStateManagerHelpers:
    """Tests for StateManager helper methods."""

    def test_mark_step_started(self):
        """mark_step_started updates step status to IN_PROGRESS."""
        with patch("shared.state.boto3"):
            manager = StateManager(
                s3_bucket="test-bucket",
            )

            job_state = JobState(
                job_execution_id="exec-123",
                job_id="job-456",
                trigger_source="udf",
                email="user@example.com",
                petname="fuzzy-cat",
                dep_id="dep-789",
                status=JobStatus.IN_PROGRESS,
            )

            with patch.object(manager, "update_state") as mock_update:
                manager.mark_step_started(job_state, "namespace")

                assert job_state.steps["namespace"]["status"] == StepStatus.IN_PROGRESS
                mock_update.assert_called_once()

    def test_mark_step_complete(self):
        """mark_step_complete updates step status to SUCCESS."""
        with patch("shared.state.boto3"):
            manager = StateManager(
                s3_bucket="test-bucket",
            )

            job_state = JobState(
                job_execution_id="exec-123",
                job_id="job-456",
                trigger_source="udf",
                email="user@example.com",
                petname="fuzzy-cat",
                dep_id="dep-789",
                status=JobStatus.IN_PROGRESS,
            )

            with patch.object(manager, "update_state") as mock_update:
                manager.mark_step_complete(job_state, "namespace", name="fuzzy-cat")

                assert job_state.steps["namespace"]["status"] == StepStatus.SUCCESS
                assert job_state.steps["namespace"]["name"] == "fuzzy-cat"
                mock_update.assert_called_once()

    def test_add_output(self):
        """add_output stores output value in S3 state."""
        with patch("shared.state.boto3") as mock_boto:
            mock_s3 = MagicMock()
            mock_boto.client.return_value = mock_s3

            manager = StateManager(
                s3_bucket="test-bucket",
            )

            job_state = JobState(
                job_execution_id="exec-123",
                job_id="job-456",
                trigger_source="udf",
                email="user@example.com",
                petname="fuzzy-cat",
                dep_id="dep-789",
                status=JobStatus.IN_PROGRESS,
            )

            manager.add_output(job_state, "site_token", "abc123xyz", lab_id="lab-001")

            # Verify S3 write includes output
            mock_s3.put_object.assert_called_once()
            call_args = mock_s3.put_object.call_args
            body = json.loads(call_args.kwargs["Body"])
            assert body["outputs"]["site_token"] == "abc123xyz"

    def test_mark_step_failed_tracks_errors(self):
        """mark_step_failed updates status and tracks error."""
        with patch("shared.state.boto3"):
            manager = StateManager(
                s3_bucket="test-bucket",
            )

            job_state = JobState(
                job_execution_id="exec-123",
                job_id="job-456",
                trigger_source="udf",
                email="user@example.com",
                petname="fuzzy-cat",
                dep_id="dep-789",
                status=JobStatus.IN_PROGRESS,
            )

            with patch.object(manager, "update_state") as mock_update:
                manager.mark_step_failed(job_state, "namespace", "Connection timeout")

                assert job_state.steps["namespace"]["status"] == StepStatus.FAILED
                assert job_state.steps["namespace"]["error"] == "Connection timeout"
                assert "exec-123" in manager._errors
                assert "Connection timeout" in manager._errors["exec-123"]
                mock_update.assert_called()

    def test_mark_job_complete(self):
        """mark_job_complete updates job status to COMPLETED."""
        with patch("shared.state.boto3"):
            manager = StateManager(
                s3_bucket="test-bucket",
            )

            job_state = JobState(
                job_execution_id="exec-123",
                job_id="job-456",
                trigger_source="udf",
                email="user@example.com",
                petname="fuzzy-cat",
                dep_id="dep-789",
                status=JobStatus.IN_PROGRESS,
            )

            with patch.object(manager, "update_state") as mock_update:
                manager.mark_job_complete(job_state)

                assert job_state.status == JobStatus.COMPLETED
                mock_update.assert_called_once()

    def test_mark_job_failed(self):
        """mark_job_failed updates job status to FAILED with error."""
        with patch("shared.state.boto3"):
            manager = StateManager(
                s3_bucket="test-bucket",
            )

            job_state = JobState(
                job_execution_id="exec-123",
                job_id="job-456",
                trigger_source="udf",
                email="user@example.com",
                petname="fuzzy-cat",
                dep_id="dep-789",
                status=JobStatus.IN_PROGRESS,
            )

            with patch.object(manager, "update_state") as mock_update:
                manager.mark_job_failed(job_state, "Fatal error occurred")

                assert job_state.status == JobStatus.FAILED
                assert job_state.error == "Fatal error occurred"
                mock_update.assert_called_once()
