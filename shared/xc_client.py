"""Lightweight F5 XC API client.

Replaces f5xc_tops_py_client with a simpler implementation that gives
full control over retry logic and error handling.
"""

import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from .errors import PermanentError, TransientError, RateLimitError, ResourceExistsError


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

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            path: API path (e.g., /api/config/namespaces/ns/origin_pools)
            payload: Request body for POST/PUT

        Returns:
            Response JSON data.

        Raises:
            PermanentError: For 4xx errors (except 429)
            ResourceExistsError: For 409 Conflict
            TransientError: For 5xx errors after retries exhausted
            RateLimitError: For 429 after retries exhausted
        """
        url = f"{self._tenant_url}{path}"

        for attempt in range(self._max_retries):
            try:
                if method == "GET":
                    response = self._session.get(url)
                elif method == "POST":
                    response = self._session.post(url, json=payload)
                elif method == "PUT":
                    response = self._session.put(url, json=payload)
                elif method == "DELETE":
                    response = self._session.delete(url, json=payload)
                else:
                    raise ValueError(f"Unsupported method: {method}")

                return self._handle_response(response, attempt)

            except (TransientError, RateLimitError):
                if attempt == self._max_retries - 1:
                    raise
                # Sleep handled in _handle_response for rate limits

        raise TransientError(f"Request failed after {self._max_retries} attempts")

    def _handle_response(self, response: requests.Response, attempt: int) -> Dict[str, Any]:
        """Handle HTTP response with error classification.

        Args:
            response: HTTP response
            attempt: Current attempt number (for backoff calculation)

        Returns:
            Response JSON data on success.

        Raises:
            PermanentError: For 4xx errors
            ResourceExistsError: For 409 Conflict
            TransientError: For 5xx errors
            RateLimitError: For 429 Rate Limit
        """
        status = response.status_code

        # Success
        if 200 <= status < 300:
            try:
                return response.json()
            except Exception:
                return {}

        # Extract error message
        try:
            error_data = response.json()
            message = error_data.get("message", response.text)
        except Exception:
            message = response.text

        # Rate limit - sleep and retry
        if status == 429:
            retry_after = int(response.headers.get("Retry-After", 30))
            time.sleep(retry_after)
            raise RateLimitError(message, retry_after=retry_after)

        # Conflict - resource exists
        if status == 409:
            raise ResourceExistsError(message)

        # Client errors - permanent
        if 400 <= status < 500:
            raise PermanentError(f"API error {status}: {message}")

        # Server errors - transient, backoff and retry
        if status >= 500:
            time.sleep(self._backoff_base ** attempt)
            raise TransientError(f"API error {status}: {message}")

        raise TransientError(f"Unexpected status {status}: {message}")

    def get(self, path: str) -> Dict[str, Any]:
        """HTTP GET request."""
        return self._request("GET", path)

    def post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """HTTP POST request."""
        return self._request("POST", path, payload)

    def put(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """HTTP PUT request."""
        return self._request("PUT", path, payload)

    def delete(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """HTTP DELETE request."""
        return self._request("DELETE", path, payload)
