"""Tests for shared.errors module."""

import pytest

from shared.errors import (
    AmbiguousError,
    PermanentError,
    RateLimitError,
    ResourceExistsError,
    ResourceNotFoundError,
    TransientError,
)


class TestRateLimitError:
    """Tests for RateLimitError."""

    def test_can_be_raised_and_caught(self):
        """Test RateLimitError can be raised and caught."""
        with pytest.raises(RateLimitError) as exc_info:
            raise RateLimitError("Too many requests")

        assert str(exc_info.value) == "Too many requests"

    def test_stores_retry_after_value(self):
        """Test RateLimitError stores retry_after value."""
        error = RateLimitError("Rate limited", retry_after=60)
        assert error.retry_after == 60

    def test_default_retry_after_is_30(self):
        """Test default retry_after is 30 seconds."""
        error = RateLimitError("Rate limited")
        assert error.retry_after == 30

    def test_inherits_from_exception(self):
        """Test RateLimitError inherits from Exception."""
        assert issubclass(RateLimitError, Exception)


class TestTransientError:
    """Tests for TransientError."""

    def test_can_be_raised_and_caught(self):
        """Test TransientError can be raised and caught."""
        with pytest.raises(TransientError) as exc_info:
            raise TransientError("Gateway timeout")

        assert str(exc_info.value) == "Gateway timeout"

    def test_inherits_from_exception(self):
        """Test TransientError inherits from Exception."""
        assert issubclass(TransientError, Exception)


class TestPermanentError:
    """Tests for PermanentError."""

    def test_can_be_raised_and_caught(self):
        """Test PermanentError can be raised and caught."""
        with pytest.raises(PermanentError) as exc_info:
            raise PermanentError("Bad request")

        assert str(exc_info.value) == "Bad request"

    def test_inherits_from_exception(self):
        """Test PermanentError inherits from Exception."""
        assert issubclass(PermanentError, Exception)


class TestAmbiguousError:
    """Tests for AmbiguousError."""

    def test_can_be_raised_and_caught(self):
        """Test AmbiguousError can be raised and caught."""
        with pytest.raises(AmbiguousError) as exc_info:
            raise AmbiguousError("Internal server error")

        assert str(exc_info.value) == "Internal server error"

    def test_inherits_from_exception(self):
        """Test AmbiguousError inherits from Exception."""
        assert issubclass(AmbiguousError, Exception)


class TestResourceNotFoundError:
    """Tests for ResourceNotFoundError."""

    def test_can_be_raised_and_caught(self):
        """Test ResourceNotFoundError can be raised and caught."""
        with pytest.raises(ResourceNotFoundError) as exc_info:
            raise ResourceNotFoundError("Resource not found")

        assert str(exc_info.value) == "Resource not found"

    def test_inherits_from_exception(self):
        """Test ResourceNotFoundError inherits from Exception."""
        assert issubclass(ResourceNotFoundError, Exception)


class TestResourceExistsError:
    """Tests for ResourceExistsError."""

    def test_can_be_raised_and_caught(self):
        """Test ResourceExistsError can be raised and caught."""
        with pytest.raises(ResourceExistsError) as exc_info:
            raise ResourceExistsError("Resource already exists")

        assert str(exc_info.value) == "Resource already exists"

    def test_inherits_from_exception(self):
        """Test ResourceExistsError inherits from Exception."""
        assert issubclass(ResourceExistsError, Exception)
