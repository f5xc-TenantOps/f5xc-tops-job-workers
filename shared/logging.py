"""Structured logging for lambda functions.

Provides JSON-formatted logging with correlation IDs for tracing
requests across lambda invocations.
"""

import json
from datetime import datetime, timezone
from typing import Any, Optional


class StructuredLogger:
    """JSON logger with correlation tracking.

    All logs are written to stdout as JSON for CloudWatch Logs Insights.
    """

    def __init__(
        self,
        service: str,
        correlation_id: str,
        step: Optional[str] = None,
    ):
        """Initialize the logger.

        Args:
            service: The lambda function or service name.
            correlation_id: Unique ID for tracing related operations.
            step: Optional step name for sub-loggers.
        """
        self.service = service
        self.correlation_id = correlation_id
        self.step = step

    def _log(self, level: str, message: str, **kwargs: Any) -> None:
        """Write a structured log entry to stdout.

        Args:
            level: Log level (INFO, ERROR, WARN, DEBUG).
            message: Human-readable log message.
            **kwargs: Additional fields to include in the log entry.
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "service": self.service,
            "correlation_id": self.correlation_id,
            "message": message,
        }

        if self.step:
            entry["step"] = self.step

        # Add any extra fields
        entry.update(kwargs)

        print(json.dumps(entry))

    def info(self, message: str, **kwargs: Any) -> None:
        """Log at INFO level.

        Args:
            message: Log message.
            **kwargs: Additional fields.
        """
        self._log("INFO", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """Log at ERROR level.

        Args:
            message: Log message.
            **kwargs: Additional fields.
        """
        self._log("ERROR", message, **kwargs)

    def warn(self, message: str, **kwargs: Any) -> None:
        """Log at WARN level.

        Args:
            message: Log message.
            **kwargs: Additional fields.
        """
        self._log("WARN", message, **kwargs)

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log at DEBUG level.

        Args:
            message: Log message.
            **kwargs: Additional fields.
        """
        self._log("DEBUG", message, **kwargs)

    def with_step(self, step: str) -> "StructuredLogger":
        """Return a sub-logger with a step name.

        Useful for logging within specific operations while maintaining
        the same correlation_id and service.

        Args:
            step: Name of the current operation step.

        Returns:
            A new StructuredLogger with the step name included.
        """
        return StructuredLogger(
            service=self.service,
            correlation_id=self.correlation_id,
            step=step,
        )
