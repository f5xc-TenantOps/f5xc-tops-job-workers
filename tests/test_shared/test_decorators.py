"""Tests for shared.decorators module."""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from shared.decorators import extract_correlation_id, lambda_handler, with_retry
from shared.errors import PermanentError, RateLimitError, TransientError


class TestWithRetry:
    """Tests for @with_retry decorator."""

    def test_retries_on_transient_error(self):
        """Test that @with_retry retries on TransientError."""
        call_count = 0

        @with_retry(max_attempts=3, backoff_base=1)
        def flaky_function():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TransientError("Temporary failure")
            return "success"

        with patch("shared.decorators.time.sleep"):
            result = flaky_function()

        assert result == "success"
        assert call_count == 3

    def test_respects_rate_limit_retry_after(self):
        """Test that @with_retry respects RateLimitError.retry_after."""
        call_count = 0
        sleep_times = []

        @with_retry(max_attempts=3)
        def rate_limited_function():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RateLimitError("Rate limited", retry_after=45)
            return "success"

        with patch("shared.decorators.time.sleep") as mock_sleep:
            mock_sleep.side_effect = lambda t: sleep_times.append(t)
            result = rate_limited_function()

        assert result == "success"
        assert sleep_times == [45]

    def test_stops_after_max_attempts(self):
        """Test that @with_retry stops after max_attempts."""
        call_count = 0

        @with_retry(max_attempts=3, backoff_base=1)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise TransientError("Always fails")

        with patch("shared.decorators.time.sleep"):
            with pytest.raises(TransientError):
                always_fails()

        assert call_count == 3

    def test_does_not_retry_permanent_error(self):
        """Test that @with_retry does NOT retry PermanentError."""
        call_count = 0

        @with_retry(max_attempts=3)
        def permanent_failure():
            nonlocal call_count
            call_count += 1
            raise PermanentError("Bad request")

        with pytest.raises(PermanentError):
            permanent_failure()

        assert call_count == 1

    def test_exponential_backoff_for_transient_error(self):
        """Test exponential backoff timing for TransientError."""
        sleep_times = []

        @with_retry(max_attempts=4, backoff_base=2)
        def always_fails():
            raise TransientError("Always fails")

        with patch("shared.decorators.time.sleep") as mock_sleep:
            mock_sleep.side_effect = lambda t: sleep_times.append(t)
            with pytest.raises(TransientError):
                always_fails()

        # backoff_base ** attempt: 2**0=1, 2**1=2, 2**2=4
        assert sleep_times == [1, 2, 4]

    def test_returns_result_on_first_success(self):
        """Test that result is returned on first successful call."""
        @with_retry(max_attempts=3)
        def succeeds_immediately():
            return "immediate success"

        result = succeeds_immediately()
        assert result == "immediate success"


class TestExtractCorrelationId:
    """Tests for extract_correlation_id function."""

    def test_from_direct_event(self):
        """Test extraction from direct invocation payload."""
        event = {"correlation_id": "direct-123"}
        result = extract_correlation_id(event)
        assert result == "direct-123"

    def test_from_sqs_event(self):
        """Test extraction from SQS message body."""
        event = {
            "Records": [
                {
                    "body": json.dumps({"correlation_id": "sqs-456", "data": "test"})
                }
            ]
        }
        result = extract_correlation_id(event)
        assert result == "sqs-456"

    def test_from_dynamodb_stream_event(self):
        """Test extraction from DynamoDB stream NewImage."""
        event = {
            "Records": [
                {
                    "dynamodb": {
                        "NewImage": {
                            "correlation_id": {"S": "dynamo-789"},
                            "other_field": {"S": "value"},
                        }
                    }
                }
            ]
        }
        result = extract_correlation_id(event)
        assert result == "dynamo-789"

    def test_generates_uuid_when_not_found(self):
        """Test that a UUID is generated when correlation_id is not found."""
        event = {"some_field": "value"}
        result = extract_correlation_id(event)

        # Verify it's a valid UUID
        parsed_uuid = uuid.UUID(result)
        assert str(parsed_uuid) == result

    def test_generates_uuid_for_empty_event(self):
        """Test UUID generation for empty event."""
        event = {}
        result = extract_correlation_id(event)

        parsed_uuid = uuid.UUID(result)
        assert str(parsed_uuid) == result

    def test_handles_invalid_sqs_body_json(self):
        """Test handling of invalid JSON in SQS body."""
        event = {"Records": [{"body": "not valid json"}]}
        result = extract_correlation_id(event)

        # Should generate UUID when JSON parsing fails
        parsed_uuid = uuid.UUID(result)
        assert str(parsed_uuid) == result

    def test_sqs_body_without_correlation_id(self):
        """Test SQS body that doesn't contain correlation_id."""
        event = {"Records": [{"body": json.dumps({"other": "data"})}]}
        result = extract_correlation_id(event)

        # Should generate UUID
        parsed_uuid = uuid.UUID(result)
        assert str(parsed_uuid) == result


class TestLambdaHandler:
    """Tests for @lambda_handler decorator."""

    def test_wraps_function_correctly(self, capsys):
        """Test that @lambda_handler wraps function correctly."""
        @lambda_handler
        def my_handler(event, context, logger):
            logger.info("Processing")
            return {"result": "ok"}

        context = MagicMock()
        context.function_name = "test-function"
        event = {"correlation_id": "handler-123"}

        result = my_handler(event, context)

        assert result["statusCode"] == 200
        assert result["body"] == {"result": "ok"}

    def test_passes_logger_to_handler(self, capsys):
        """Test that logger is passed to the wrapped handler."""
        received_logger = None

        @lambda_handler
        def my_handler(event, context, logger):
            nonlocal received_logger
            received_logger = logger
            return "done"

        context = MagicMock()
        context.function_name = "test-function"
        event = {"correlation_id": "logger-test-123"}

        my_handler(event, context)

        assert received_logger is not None
        assert received_logger.correlation_id == "logger-test-123"
        assert received_logger.service == "test-function"

    def test_handles_permanent_error(self, capsys):
        """Test that PermanentError returns 400 status."""
        @lambda_handler
        def failing_handler(event, context, logger):
            raise PermanentError("Invalid input")

        context = MagicMock()
        context.function_name = "test-function"
        event = {}

        result = failing_handler(event, context)

        assert result["statusCode"] == 400
        assert result["body"] == "Invalid input"

    def test_reraises_transient_error(self):
        """Test that TransientError is re-raised for infrastructure retry."""
        @lambda_handler
        def transient_handler(event, context, logger):
            raise TransientError("Gateway timeout")

        context = MagicMock()
        context.function_name = "test-function"
        event = {}

        with pytest.raises(TransientError):
            transient_handler(event, context)

    def test_reraises_rate_limit_error(self):
        """Test that RateLimitError is re-raised for infrastructure retry."""
        @lambda_handler
        def rate_limited_handler(event, context, logger):
            raise RateLimitError("Too many requests", retry_after=60)

        context = MagicMock()
        context.function_name = "test-function"
        event = {}

        with pytest.raises(RateLimitError):
            rate_limited_handler(event, context)

    def test_reraises_unexpected_error(self):
        """Test that unexpected errors are re-raised."""
        @lambda_handler
        def unexpected_handler(event, context, logger):
            raise ValueError("Unexpected")

        context = MagicMock()
        context.function_name = "test-function"
        event = {}

        with pytest.raises(ValueError):
            unexpected_handler(event, context)

    def test_logs_invocation_and_completion(self, capsys):
        """Test that handler logs invocation and completion."""
        @lambda_handler
        def my_handler(event, context, logger):
            return "done"

        context = MagicMock()
        context.function_name = "test-function"
        event = {"correlation_id": "log-test-123"}

        my_handler(event, context)

        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")

        # Should have at least invoked and completed logs
        assert len(lines) >= 2

        invoked_log = json.loads(lines[0])
        completed_log = json.loads(lines[1])

        assert invoked_log["message"] == "Lambda invoked"
        assert completed_log["message"] == "Lambda completed"
        assert completed_log["status"] == "success"
