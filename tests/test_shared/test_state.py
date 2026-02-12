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
    _sanitize_error,
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


class TestSanitizeError:
    """Tests for _sanitize_error — cleans raw errors for end-user display."""

    # -- API errors --

    def test_api_401_returns_auth_message(self):
        assert _sanitize_error("API error 401: Unauthorized") == (
            "Authentication failed — API credentials may be expired"
        )

    def test_api_403_returns_permission_denied(self):
        assert _sanitize_error("API error 403: Forbidden") == "Permission denied"

    def test_api_403_nested_in_resource_creation(self):
        msg = 'Resource creation failed: API error 403: {"message":"forbidden","code":403}'
        assert _sanitize_error(msg) == "Permission denied"

    def test_api_429_returns_rate_limited(self):
        assert _sanitize_error("API error 429: Too Many Requests") == (
            "Rate limited — too many API requests"
        )

    def test_api_400_returns_config_error(self):
        msg = 'API error 400: {"message":"invalid namespace name","code":400}'
        assert _sanitize_error(msg) == "Configuration error"

    def test_api_500_returns_service_unavailable(self):
        assert _sanitize_error("API error 500: Internal Server Error") == (
            "Service temporarily unavailable"
        )

    def test_api_502_returns_service_unavailable(self):
        assert _sanitize_error("API error 502: Bad Gateway") == (
            "Service temporarily unavailable"
        )

    # -- Network errors --

    def test_network_error(self):
        msg = (
            "Network error: HTTPSConnectionPool(host='tenant.console.ves.volterra.io', "
            "port=443): Max retries exceeded with url: /api/web/namespaces "
            "(Caused by NewConnectionError('<urllib3...>: Failed to connect'))"
        )
        assert _sanitize_error(msg) == "Service unreachable"

    # -- SSM errors --

    def test_ssm_parameter_error(self):
        msg = (
            "Failed to fetch parameters: An error occurred (ParameterNotFound) "
            "when calling the GetParameters operation"
        )
        assert _sanitize_error(msg) == "Configuration unavailable"

    # -- Lambda invocation errors --

    def test_lambda_invocation_failure(self):
        msg = "Failed to invoke tops-ns-create-v2: ConnectionError('refused')"
        assert _sanitize_error(msg) == "Internal service error"

    # -- Resource creation wrapper --

    def test_resource_creation_unwraps_inner_error(self):
        msg = "Resource creation failed: API error 500: Internal Server Error"
        assert _sanitize_error(msg) == "Service temporarily unavailable"

    def test_resource_creation_with_network_error(self):
        msg = "Resource creation failed: Network error: connection refused"
        assert _sanitize_error(msg) == "Service unreachable"

    # -- Tracebacks --

    def test_traceback_returns_internal_error(self):
        msg = (
            'Traceback (most recent call last):\n'
            '  File "/var/task/function.py", line 42, in handler\n'
            '    result = create_namespace(name)\n'
            'PermanentError: API error 400: invalid name'
        )
        assert _sanitize_error(msg) == "Internal error"

    # -- Step Function errors --

    def test_step_function_state_error(self):
        msg = "States.TaskFailed: Lambda function returned error"
        assert _sanitize_error(msg) == "Workflow error"

    # -- Connection pool noise --

    def test_strips_connection_pool_prefix(self):
        msg = (
            "HTTPSConnectionPool(host='10.1.1.5', port=65500): "
            "Max retries exceeded with url: /api/test "
            "Caused by NewConnectionError('<urllib3...>: "
            "Failed to establish a new connection: [Errno 61] Connection refused')"
        )
        result = _sanitize_error(msg)
        assert "HTTPSConnectionPool" not in result
        assert "urllib3" not in result
        assert "Connection refused" in result

    def test_strips_bare_https_connection(self):
        msg = (
            "HTTPSConnection(host='10.1.1.5', port=65500): "
            "Failed to establish a new connection: [Errno 113] No route to host"
        )
        result = _sanitize_error(msg)
        assert "HTTPSConnection" not in result
        assert "No route to host" in result

    # -- Clean messages pass through --

    def test_clean_timeout_message_passes_through(self):
        msg = "Namespace 'fuzzy-cat' was not available within 120 seconds."
        assert _sanitize_error(msg) == msg

    def test_clean_resource_count_passes_through(self):
        assert _sanitize_error("2 resources failed") == "2 resources failed"

    def test_dependency_failed_passes_through(self):
        assert _sanitize_error("dependency failed") == "dependency failed"

    # -- Edge cases --

    def test_empty_string_passes_through(self):
        assert _sanitize_error("") == ""

    def test_none_passes_through(self):
        assert _sanitize_error(None) is None

    def test_truncates_long_messages(self):
        msg = "x" * 300
        result = _sanitize_error(msg)
        assert len(result) == 203
        assert result.endswith("...")

    def test_strips_internal_lambda_names(self):
        msg = "Error in tops-resource-orchestrator-v2 processing"
        result = _sanitize_error(msg)
        assert "tops-resource-orchestrator-v2" not in result
        assert "service" in result

    def test_strips_large_json_blobs(self):
        blob = '{"message":"error","details":"' + "x" * 100 + '"}'
        msg = f"Something failed: {blob}"
        result = _sanitize_error(msg)
        assert len(result) < len(msg)


class TestBuildS3StateSanitization:
    """Tests that _build_s3_state sanitizes error fields."""

    def _make_job_state(self):
        return JobState(
            job_execution_id="exec-123",
            job_id="job-456",
            trigger_source="udf",
            email="user@example.com",
            petname="fuzzy-cat",
            dep_id="dep-789",
            status=JobStatus.FAILED,
        )

    def test_sanitizes_step_errors(self):
        job_state = self._make_job_state()
        job_state.update_step(
            "namespace",
            StepStatus.FAILED,
            error="API error 403: Forbidden",
        )

        result = _build_s3_state(job_state)

        assert result["steps"]["namespace"]["error"] == "Permission denied"

    def test_sanitizes_resource_errors(self):
        job_state = self._make_job_state()
        job_state.update_resource(
            "my-origin-pool",
            StepStatus.FAILED,
            error="Resource creation failed: API error 500: Internal Server Error",
        )

        result = _build_s3_state(job_state)

        assert result["resources"]["my-origin-pool"]["error"] == "Service temporarily unavailable"

    def test_sanitizes_errors_list(self):
        job_state = self._make_job_state()

        result = _build_s3_state(
            job_state,
            errors=[
                "API error 403: Forbidden",
                "Failed to invoke tops-ns-create-v2: timeout",
            ],
        )

        assert result["errors"][0] == "Permission denied"
        assert result["errors"][1] == "Internal service error"

    def test_clean_errors_pass_through(self):
        job_state = self._make_job_state()
        job_state.update_step(
            "namespace",
            StepStatus.FAILED,
            error="Namespace 'fuzzy-cat' was not available within 120 seconds.",
        )

        result = _build_s3_state(job_state)

        assert result["steps"]["namespace"]["error"] == (
            "Namespace 'fuzzy-cat' was not available within 120 seconds."
        )
