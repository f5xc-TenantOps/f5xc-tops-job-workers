"""Lightweight F5 XC API client.

Replaces f5xc_tops_py_client with a simpler implementation that gives
full control over retry logic and error handling.
"""

import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from .errors import PermanentError, TransientError, RateLimitError, ResourceExistsError, ResourceNotFoundError

__all__ = ["XCClient"]


class XCClient:
    """F5 XC API client with retry logic and error classification."""

    def __init__(
        self,
        tenant_url: str,
        api_token: str,
        validate: bool = True,
        max_retries: int = 3,
        backoff_base: float = 2.0,
        timeout: tuple = (10, 30)
    ):
        """Initialize XC client.

        Args:
            tenant_url: F5 XC tenant URL (e.g., https://tenant.console.ves.volterra.io)
            api_token: API token for authentication
            validate: Whether to validate the session on init
            max_retries: Maximum retry attempts for transient errors
            backoff_base: Base for exponential backoff
            timeout: Request timeout as (connect_timeout, read_timeout) in seconds
        """
        self._tenant_url = self._validate_url(tenant_url)
        self._api_token = api_token
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._timeout = timeout

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
                    response = self._session.get(url, timeout=self._timeout)
                elif method == "POST":
                    response = self._session.post(url, json=payload, timeout=self._timeout)
                elif method == "PUT":
                    response = self._session.put(url, json=payload, timeout=self._timeout)
                elif method == "DELETE":
                    response = self._session.delete(url, json=payload, timeout=self._timeout)
                else:
                    raise ValueError(f"Unsupported method: {method}")

                return self._handle_response(response, attempt)

            except requests.exceptions.RequestException as e:
                if attempt == self._max_retries - 1:
                    raise TransientError(f"Network error: {e}") from e
                time.sleep(self._backoff_base ** attempt)

            except (TransientError, RateLimitError):
                if attempt == self._max_retries - 1:
                    raise
                # Sleep handled in _handle_response for rate limits

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

        # Not found
        if status == 404:
            raise ResourceNotFoundError(message)

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

    # --- Namespace Operations ---

    def create_namespace(self, name: str, description: str = "") -> Dict[str, Any]:
        """Create a namespace."""
        payload = {
            "metadata": {
                "name": name,
                "description": description,
                "annotations": {},
                "labels": {},
                "disable": False,
                "namespace": ""
            },
            "spec": {}
        }
        return self.post("/api/web/namespaces", payload)

    def get_namespace(self, name: str) -> Dict[str, Any]:
        """Get a namespace."""
        return self.get(f"/api/web/namespaces/{name}")

    def delete_namespace(self, name: str) -> Dict[str, Any]:
        """Delete a namespace (cascade)."""
        return self.post(f"/api/web/namespaces/{name}/cascade_delete", {"name": name})

    # --- User Operations ---

    def create_user(
        self,
        email: str,
        first_name: str,
        last_name: str,
        group_names: list = None,
        namespace_roles: list = None
    ) -> Dict[str, Any]:
        """Create a user."""
        payload = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "name": email,
            "namespace": "system",
            "group_names": group_names or [],
            "namespace_roles": namespace_roles or [],
            "idm_type": "SSO",
            "type": "USER"
        }
        return self.post("/api/web/custom/namespaces/system/user_roles", payload)

    def delete_user(self, email: str) -> Dict[str, Any]:
        """Delete a user."""
        payload = {"email": email, "namespace": "system"}
        return self.post("/api/web/custom/namespaces/system/users/cascade_delete", payload)

    def update_user(
        self,
        email: str,
        first_name: str,
        last_name: str,
        namespace_roles: list,
        group_names: list
    ) -> Dict[str, Any]:
        """Update a user."""
        payload = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "namespace": "system",
            "namespace_roles": namespace_roles,
            "group_names": group_names
        }
        return self.put("/api/web/custom/namespaces/system/user_roles", payload)

    # --- Generic Config Resources (full payload pass-through) ---

    def create_origin_pool(self, namespace: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create an origin pool."""
        return self.post(f"/api/config/namespaces/{namespace}/origin_pools", payload)

    def get_origin_pool(self, namespace: str, name: str) -> Dict[str, Any]:
        """Get an origin pool."""
        return self.get(f"/api/config/namespaces/{namespace}/origin_pools/{name}")

    def delete_origin_pool(self, namespace: str, name: str) -> Dict[str, Any]:
        """Delete an origin pool."""
        return self.delete(f"/api/config/namespaces/{namespace}/origin_pools/{name}")

    def create_http_loadbalancer(self, namespace: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create an HTTP load balancer."""
        return self.post(f"/api/config/namespaces/{namespace}/http_loadbalancers", payload)

    def get_http_loadbalancer(self, namespace: str, name: str) -> Dict[str, Any]:
        """Get an HTTP load balancer."""
        return self.get(f"/api/config/namespaces/{namespace}/http_loadbalancers/{name}")

    def delete_http_loadbalancer(self, namespace: str, name: str) -> Dict[str, Any]:
        """Delete an HTTP load balancer."""
        return self.delete(f"/api/config/namespaces/{namespace}/http_loadbalancers/{name}")

    def create_tcp_loadbalancer(self, namespace: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a TCP load balancer."""
        return self.post(f"/api/config/namespaces/{namespace}/tcp_loadbalancers", payload)

    def create_app_firewall(self, namespace: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create an app firewall (WAF policy)."""
        return self.post(f"/api/config/namespaces/{namespace}/app_firewalls", payload)

    def get_app_firewall(self, namespace: str, name: str) -> Dict[str, Any]:
        """Get an app firewall."""
        return self.get(f"/api/config/namespaces/{namespace}/app_firewalls/{name}")

    # --- Certificate Operations ---

    def create_certificate(
        self,
        namespace: str,
        name: str,
        cert_b64: str,
        key_b64: str
    ) -> Dict[str, Any]:
        """Create a certificate."""
        payload = {
            "metadata": {
                "name": name,
                "namespace": namespace,
                "disable": False
            },
            "spec": {
                "certificate_url": f"string:///{cert_b64}",
                "private_key": {
                    "clear_secret_info": {
                        "url": f"string:///{key_b64}"
                    }
                }
            }
        }
        return self.post(f"/api/config/namespaces/{namespace}/certificates", payload)

    def replace_certificate(
        self,
        namespace: str,
        name: str,
        cert_b64: str,
        key_b64: str
    ) -> Dict[str, Any]:
        """Replace a certificate."""
        payload = {
            "metadata": {
                "name": name,
                "namespace": namespace,
                "disable": False
            },
            "spec": {
                "certificate_url": f"string:///{cert_b64}",
                "private_key": {
                    "clear_secret_info": {
                        "url": f"string:///{key_b64}"
                    }
                }
            }
        }
        return self.put(f"/api/config/namespaces/{namespace}/certificates/{name}", payload)

    # --- Credential Operations ---

    def renew_api_credential(
        self,
        name: str,
        expiration_days: int,
        namespace: str = "system"
    ) -> Dict[str, Any]:
        """Renew an API credential."""
        payload = {
            "name": name,
            "namespace": namespace,
            "expiration_days": expiration_days
        }
        return self.post(f"/api/web/namespaces/{namespace}/renew/api_credentials", payload)

    def renew_service_credential(
        self,
        name: str,
        expiration_days: int,
        namespace: str = "system"
    ) -> Dict[str, Any]:
        """Renew a service credential."""
        payload = {
            "name": name,
            "namespace": namespace,
            "expiration_days": expiration_days
        }
        return self.post(f"/api/web/namespaces/{namespace}/renew/service_credentials", payload)
