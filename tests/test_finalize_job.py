# tests/test_finalize_job.py
import os
import pytest
from unittest.mock import MagicMock, patch

from shared.job_state import JobState, JobStatus


def _make_job_state(**overrides):
    """Build a JobState with sensible defaults."""
    defaults = dict(
        job_execution_id="exec-1",
        job_id="api-lab",
        trigger_source="udf",
        email="k.reynolds@f5.com",
        petname="needed-badger",
        dep_id="dep-123",
        status=JobStatus.IN_PROGRESS,
        steps={},
        resources={},
    )
    defaults.update(overrides)
    return JobState(**defaults)


class TestUpdateDeploymentRecord:
    """Tests for _update_deployment_record()."""

    @patch("finalize_job.function.boto3")
    @patch.dict(os.environ, {"DEPLOYMENT_STATE_TABLE": "test-table"})
    def test_unified_manifest_includes_steps_and_resources(self, mock_boto3):
        from finalize_job.function import _update_deployment_record
        from shared.logging import StructuredLogger

        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        job_state = _make_job_state(
            steps={
                "namespace": {"status": "SUCCESS", "name": "needed-badger"},
                "user": {"status": "SUCCESS", "name": "k.reynolds@f5.com"},
            },
            resources={
                "needed-badger-origin": {"status": "SUCCESS", "type": "origin_pool"},
                "needed-badger-lb": {"status": "SUCCESS", "type": "http_lb"},
            },
        )

        logger = StructuredLogger("test", "test-id")
        _update_deployment_record("dep-123", "COMPLETED", job_state, logger)

        call_args = mock_table.update_item.call_args
        expr_values = call_args.kwargs["ExpressionAttributeValues"]

        manifest = expr_values[":r"]
        assert manifest == {
            "needed-badger": {"type": "namespace"},
            "k.reynolds@f5.com": {"type": "user"},
            "needed-badger-origin": {"type": "origin_pool"},
            "needed-badger-lb": {"type": "http_lb"},
        }
        assert expr_values[":s"] == "COMPLETED"

    @patch("finalize_job.function.boto3")
    @patch.dict(os.environ, {"DEPLOYMENT_STATE_TABLE": "test-table"})
    def test_failed_items_excluded_from_manifest(self, mock_boto3):
        from finalize_job.function import _update_deployment_record
        from shared.logging import StructuredLogger

        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        job_state = _make_job_state(
            steps={
                "namespace": {"status": "SUCCESS", "name": "needed-badger"},
                "user": {"status": "FAILED", "name": "k.reynolds@f5.com"},
            },
            resources={
                "needed-badger-origin": {"status": "SUCCESS", "type": "origin_pool"},
                "needed-badger-lb": {"status": "FAILED", "type": "http_lb"},
            },
        )

        logger = StructuredLogger("test", "test-id")
        _update_deployment_record("dep-123", "PARTIAL", job_state, logger)

        call_args = mock_table.update_item.call_args
        expr_values = call_args.kwargs["ExpressionAttributeValues"]

        manifest = expr_values[":r"]
        assert "needed-badger" in manifest
        assert "needed-badger-origin" in manifest
        assert "k.reynolds@f5.com" not in manifest
        assert "needed-badger-lb" not in manifest

    @patch("finalize_job.function.boto3")
    @patch.dict(os.environ, {"DEPLOYMENT_STATE_TABLE": "test-table"})
    def test_completed_status_maps_to_completed(self, mock_boto3):
        from finalize_job.function import _update_deployment_record
        from shared.logging import StructuredLogger

        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        job_state = _make_job_state()
        logger = StructuredLogger("test", "test-id")
        _update_deployment_record("dep-123", "COMPLETED", job_state, logger)

        expr_values = mock_table.update_item.call_args.kwargs["ExpressionAttributeValues"]
        assert expr_values[":s"] == "COMPLETED"

    @patch("finalize_job.function.boto3")
    @patch.dict(os.environ, {"DEPLOYMENT_STATE_TABLE": "test-table"})
    def test_partial_status_maps_to_partial(self, mock_boto3):
        from finalize_job.function import _update_deployment_record
        from shared.logging import StructuredLogger

        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        job_state = _make_job_state()
        logger = StructuredLogger("test", "test-id")
        _update_deployment_record("dep-123", "PARTIAL", job_state, logger)

        expr_values = mock_table.update_item.call_args.kwargs["ExpressionAttributeValues"]
        assert expr_values[":s"] == "PARTIAL"

    @patch("finalize_job.function.boto3")
    @patch.dict(os.environ, {"DEPLOYMENT_STATE_TABLE": "test-table"})
    def test_failed_status_maps_to_failed(self, mock_boto3):
        from finalize_job.function import _update_deployment_record
        from shared.logging import StructuredLogger

        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        job_state = _make_job_state()
        logger = StructuredLogger("test", "test-id")
        _update_deployment_record("dep-123", "FAILED", job_state, logger)

        expr_values = mock_table.update_item.call_args.kwargs["ExpressionAttributeValues"]
        assert expr_values[":s"] == "FAILED"

    @patch("finalize_job.function.boto3")
    @patch.dict(os.environ, {"DEPLOYMENT_STATE_TABLE": "test-table"})
    def test_nonfatal_on_dynamodb_error(self, mock_boto3):
        from finalize_job.function import _update_deployment_record
        from shared.logging import StructuredLogger

        mock_table = MagicMock()
        mock_table.update_item.side_effect = Exception("ConditionalCheckFailed")
        mock_boto3.resource.return_value.Table.return_value = mock_table

        job_state = _make_job_state()
        logger = StructuredLogger("test", "test-id")

        # Should not raise
        _update_deployment_record("dep-123", "COMPLETED", job_state, logger)

    @patch("finalize_job.function.boto3")
    @patch.dict(os.environ, {"DEPLOYMENT_STATE_TABLE": "test-table"})
    def test_empty_steps_and_resources_still_updates_status(self, mock_boto3):
        from finalize_job.function import _update_deployment_record
        from shared.logging import StructuredLogger

        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        job_state = _make_job_state(steps={}, resources={})
        logger = StructuredLogger("test", "test-id")
        _update_deployment_record("dep-123", "FAILED", job_state, logger)

        mock_table.update_item.assert_called_once()
        expr_values = mock_table.update_item.call_args.kwargs["ExpressionAttributeValues"]
        assert expr_values[":s"] == "FAILED"
        assert expr_values[":r"] == {}

    def test_skipped_when_no_table_env(self):
        from finalize_job.function import _update_deployment_record
        from shared.logging import StructuredLogger

        job_state = _make_job_state()
        logger = StructuredLogger("test", "test-id")

        # Should not raise, just skip
        with patch.dict(os.environ, {}, clear=True):
            _update_deployment_record("dep-123", "COMPLETED", job_state, logger)

    @patch("finalize_job.function.boto3")
    @patch.dict(os.environ, {"DEPLOYMENT_STATE_TABLE": "test-table"})
    def test_step_name_field_used_as_manifest_key(self, mock_boto3):
        """When step has a 'name' field, it becomes the manifest key (not the step key)."""
        from finalize_job.function import _update_deployment_record
        from shared.logging import StructuredLogger

        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        job_state = _make_job_state(
            steps={
                "namespace": {"status": "SUCCESS", "name": "custom-ns-name"},
            },
        )

        logger = StructuredLogger("test", "test-id")
        _update_deployment_record("dep-123", "COMPLETED", job_state, logger)

        manifest = mock_table.update_item.call_args.kwargs["ExpressionAttributeValues"][":r"]
        assert "custom-ns-name" in manifest
        assert manifest["custom-ns-name"] == {"type": "namespace"}

    @patch("finalize_job.function.boto3")
    @patch.dict(os.environ, {"DEPLOYMENT_STATE_TABLE": "test-table"})
    def test_step_without_name_falls_back_to_step_key(self, mock_boto3):
        """When step has no 'name' field, the step key becomes the manifest key."""
        from finalize_job.function import _update_deployment_record
        from shared.logging import StructuredLogger

        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        job_state = _make_job_state(
            steps={
                "namespace": {"status": "SUCCESS"},
            },
        )

        logger = StructuredLogger("test", "test-id")
        _update_deployment_record("dep-123", "COMPLETED", job_state, logger)

        manifest = mock_table.update_item.call_args.kwargs["ExpressionAttributeValues"][":r"]
        assert "namespace" in manifest
        assert manifest["namespace"] == {"type": "namespace"}
