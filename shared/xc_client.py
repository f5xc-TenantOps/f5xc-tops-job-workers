"""Lightweight F5 XC API client.

Replaces f5xc_tops_py_client with a simpler implementation that gives
full control over retry logic and error handling.
"""

import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from .errors import PermanentError, TransientError, RateLimitError


class XCClient:
    """F5 XC API client with retry logic and error classification."""

    def __init__(
        self,
        tenant_url: str,
        api_token: str,
        validate: bool = True,
        max_retries: int = 3,
        backoff_base: float = 2.0
    ):
        """Initialize XC client.

        Args:
            tenant_url: F5 XC tenant URL (e.g., https://tenant.console.ves.volterra.io)
            api_token: API token for authentication
            validate: Whether to validate the session on init
            max_retries: Maximum retry attempts for transient errors
            backoff_base: Base for exponential backoff
        """
        self._tenant_url = self._validate_url(tenant_url)
        self._api_token = api_token
        self._max_retries = max_retries
        self._backoff_base = backoff_base

        self._session = requests.Session()
        self._session.headers.update({
            'Authorization': f'APIToken {api_token}',
            'Content-Type': 'application/json'
        })

        if validate:
            self._whoami()

    @staticmethod
    def _validate_url(url: str) -> str:
        """Validate and normalize tenant URL."""
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise PermanentError(f"Invalid tenant URL: {url}")
        return f"{parsed.scheme}://{parsed.netloc}"

    def _whoami(self) -> Dict[str, Any]:
        """Validate session by calling whoami endpoint."""
        response = self._session.get(
            f"{self._tenant_url}/api/web/custom/namespaces/system/whoami"
        )
        if response.status_code == 401:
            raise PermanentError("Invalid token")
        if response.status_code != 200:
            raise TransientError(f"Failed to validate session: {response.status_code}")
        return response.json()
