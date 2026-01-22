"""Tests for shared.logging module."""

import json

import pytest

from shared.logging import StructuredLogger


class TestStructuredLogger:
    """Tests for StructuredLogger class."""

    def test_outputs_valid_json(self, capsys):
        """Test that logger outputs valid JSON."""
        logger = StructuredLogger(service="test-service", correlation_id="test-123")
        logger.info("Test message")

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())

        assert output["message"] == "Test message"
        assert output["service"] == "test-service"

    def test_correlation_id_included_in_all_logs(self, capsys):
        """Test that correlation_id is included in all log entries."""
        correlation_id = "corr-id-456"
        logger = StructuredLogger(service="test-service", correlation_id=correlation_id)

        logger.info("Info message")
        logger.error("Error message")
        logger.warn("Warn message")
        logger.debug("Debug message")

        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")

        assert len(lines) == 4
        for line in lines:
            output = json.loads(line)
            assert output["correlation_id"] == correlation_id

    def test_with_step_adds_step_to_logs(self, capsys):
        """Test that with_step() adds step field to logs."""
        logger = StructuredLogger(service="test-service", correlation_id="test-123")
        step_logger = logger.with_step("fetch_data")

        step_logger.info("Processing")

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())

        assert output["step"] == "fetch_data"
        assert output["correlation_id"] == "test-123"
        assert output["service"] == "test-service"

    def test_with_step_returns_new_logger(self):
        """Test that with_step() returns a new logger instance."""
        logger = StructuredLogger(service="test-service", correlation_id="test-123")
        step_logger = logger.with_step("my_step")

        assert step_logger is not logger
        assert step_logger.step == "my_step"
        assert logger.step is None

    def test_info_level(self, capsys):
        """Test INFO log level."""
        logger = StructuredLogger(service="test-service", correlation_id="test-123")
        logger.info("Info message")

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())

        assert output["level"] == "INFO"
        assert output["message"] == "Info message"

    def test_error_level(self, capsys):
        """Test ERROR log level."""
        logger = StructuredLogger(service="test-service", correlation_id="test-123")
        logger.error("Error message")

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())

        assert output["level"] == "ERROR"
        assert output["message"] == "Error message"

    def test_warn_level(self, capsys):
        """Test WARN log level."""
        logger = StructuredLogger(service="test-service", correlation_id="test-123")
        logger.warn("Warn message")

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())

        assert output["level"] == "WARN"
        assert output["message"] == "Warn message"

    def test_debug_level(self, capsys):
        """Test DEBUG log level."""
        logger = StructuredLogger(service="test-service", correlation_id="test-123")
        logger.debug("Debug message")

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())

        assert output["level"] == "DEBUG"
        assert output["message"] == "Debug message"

    def test_extra_kwargs_included_in_output(self, capsys):
        """Test that extra keyword arguments are included in log output."""
        logger = StructuredLogger(service="test-service", correlation_id="test-123")
        logger.info("User action", user_id="user-789", action="login")

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())

        assert output["user_id"] == "user-789"
        assert output["action"] == "login"

    def test_timestamp_included(self, capsys):
        """Test that timestamp is included in log output."""
        logger = StructuredLogger(service="test-service", correlation_id="test-123")
        logger.info("Test message")

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())

        assert "timestamp" in output
        # ISO format check
        assert "T" in output["timestamp"]
