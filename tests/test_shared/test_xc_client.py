# tests/test_shared/test_xc_client.py
import pytest
from unittest.mock import patch, MagicMock


def test_xc_client_init_sets_auth_header():
    """XCClient sets Authorization header on init."""
    from shared.xc_client import XCClient

    with patch('shared.xc_client.requests.Session') as mock_session_class:
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.get.return_value.status_code = 200
        mock_session.get.return_value.json.return_value = {"user": "test"}

        client = XCClient(
            tenant_url="https://test.console.ves.volterra.io",
            api_token="test-token"
        )

        mock_session.headers.update.assert_called_with({
            'Authorization': 'APIToken test-token',
            'Content-Type': 'application/json'
        })


def test_xc_client_validates_session_on_init():
    """XCClient calls whoami to validate session."""
    from shared.xc_client import XCClient

    with patch('shared.xc_client.requests.Session') as mock_session_class:
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.get.return_value.status_code = 200
        mock_session.get.return_value.json.return_value = {"user": "test"}

        client = XCClient(
            tenant_url="https://test.console.ves.volterra.io",
            api_token="test-token"
        )

        mock_session.get.assert_called_with(
            "https://test.console.ves.volterra.io/api/web/custom/namespaces/system/whoami"
        )


def test_xc_client_invalid_token_raises():
    """XCClient raises on invalid token."""
    from shared.xc_client import XCClient
    from shared.errors import PermanentError

    with patch('shared.xc_client.requests.Session') as mock_session_class:
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.get.return_value.status_code = 401
        mock_session.get.return_value.text = "Unauthorized"

        with pytest.raises(PermanentError, match="Invalid token"):
            XCClient(
                tenant_url="https://test.console.ves.volterra.io",
                api_token="bad-token"
            )


def test_xc_client_get_success():
    """XCClient.get returns response data on success."""
    from shared.xc_client import XCClient

    with patch('shared.xc_client.requests.Session') as mock_session_class:
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Whoami succeeds
        whoami_response = MagicMock()
        whoami_response.status_code = 200
        whoami_response.json.return_value = {"user": "test"}

        # GET succeeds
        get_response = MagicMock()
        get_response.status_code = 200
        get_response.json.return_value = {"items": [{"name": "pool1"}]}

        mock_session.get.side_effect = [whoami_response, get_response]

        client = XCClient("https://test.console.ves.volterra.io", "token")
        result = client.get("/api/config/namespaces/ns/origin_pools")

        assert result == {"items": [{"name": "pool1"}]}


def test_xc_client_post_success():
    """XCClient.post returns response data on success."""
    from shared.xc_client import XCClient

    with patch('shared.xc_client.requests.Session') as mock_session_class:
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        whoami_response = MagicMock()
        whoami_response.status_code = 200
        whoami_response.json.return_value = {"user": "test"}
        mock_session.get.return_value = whoami_response

        post_response = MagicMock()
        post_response.status_code = 200
        post_response.json.return_value = {"metadata": {"name": "pool1"}}
        mock_session.post.return_value = post_response

        client = XCClient("https://test.console.ves.volterra.io", "token")
        result = client.post("/api/config/namespaces/ns/origin_pools", {"spec": {}})

        assert result == {"metadata": {"name": "pool1"}}


def test_xc_client_retries_on_503():
    """XCClient retries on 503 Service Unavailable."""
    from shared.xc_client import XCClient

    with patch('shared.xc_client.requests.Session') as mock_session_class:
        with patch('shared.xc_client.time.sleep'):
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            whoami_response = MagicMock()
            whoami_response.status_code = 200
            whoami_response.json.return_value = {"user": "test"}

            fail_response = MagicMock()
            fail_response.status_code = 503
            fail_response.text = "Service Unavailable"

            success_response = MagicMock()
            success_response.status_code = 200
            success_response.json.return_value = {"ok": True}

            mock_session.get.side_effect = [whoami_response, fail_response, success_response]

            client = XCClient("https://test.console.ves.volterra.io", "token")
            result = client.get("/api/test")

            assert result == {"ok": True}
            assert mock_session.get.call_count == 3  # whoami + 2 retries


def test_xc_client_retries_on_429_with_retry_after():
    """XCClient respects Retry-After header on 429."""
    from shared.xc_client import XCClient

    with patch('shared.xc_client.requests.Session') as mock_session_class:
        with patch('shared.xc_client.time.sleep') as mock_sleep:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            whoami_response = MagicMock()
            whoami_response.status_code = 200
            whoami_response.json.return_value = {"user": "test"}

            rate_limit_response = MagicMock()
            rate_limit_response.status_code = 429
            rate_limit_response.headers = {"Retry-After": "5"}
            rate_limit_response.text = "Rate limited"

            success_response = MagicMock()
            success_response.status_code = 200
            success_response.json.return_value = {"ok": True}

            mock_session.get.side_effect = [whoami_response, rate_limit_response, success_response]

            client = XCClient("https://test.console.ves.volterra.io", "token")
            result = client.get("/api/test")

            mock_sleep.assert_called_with(5)


def test_xc_client_raises_permanent_on_400():
    """XCClient raises PermanentError on 400 Bad Request."""
    from shared.xc_client import XCClient
    from shared.errors import PermanentError

    with patch('shared.xc_client.requests.Session') as mock_session_class:
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        whoami_response = MagicMock()
        whoami_response.status_code = 200
        whoami_response.json.return_value = {"user": "test"}

        bad_request = MagicMock()
        bad_request.status_code = 400
        bad_request.text = "Bad Request"
        bad_request.json.return_value = {"message": "Invalid payload"}

        mock_session.get.side_effect = [whoami_response, bad_request]

        client = XCClient("https://test.console.ves.volterra.io", "token")

        with pytest.raises(PermanentError, match="Invalid payload"):
            client.get("/api/test")


def test_xc_client_raises_permanent_on_409_conflict():
    """XCClient raises ResourceExistsError on 409."""
    from shared.xc_client import XCClient
    from shared.errors import ResourceExistsError

    with patch('shared.xc_client.requests.Session') as mock_session_class:
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        whoami_response = MagicMock()
        whoami_response.status_code = 200
        whoami_response.json.return_value = {"user": "test"}
        mock_session.get.return_value = whoami_response

        conflict_response = MagicMock()
        conflict_response.status_code = 409
        conflict_response.text = "Conflict"
        conflict_response.json.return_value = {"message": "Resource already exists"}
        mock_session.post.return_value = conflict_response

        client = XCClient("https://test.console.ves.volterra.io", "token")

        with pytest.raises(ResourceExistsError):
            client.post("/api/test", {})


def test_create_namespace():
    """XCClient.create_namespace creates a namespace."""
    from shared.xc_client import XCClient

    with patch('shared.xc_client.requests.Session') as mock_session_class:
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        whoami_response = MagicMock()
        whoami_response.status_code = 200
        whoami_response.json.return_value = {"user": "test"}
        mock_session.get.return_value = whoami_response

        post_response = MagicMock()
        post_response.status_code = 200
        post_response.json.return_value = {"metadata": {"name": "test-ns"}}
        mock_session.post.return_value = post_response

        client = XCClient("https://test.console.ves.volterra.io", "token")
        result = client.create_namespace("test-ns", "Test namespace")

        # Verify correct endpoint and payload
        call_args = mock_session.post.call_args
        assert "/api/web/namespaces" in call_args[0][0]
        payload = call_args[1]["json"]
        assert payload["metadata"]["name"] == "test-ns"
        assert payload["metadata"]["description"] == "Test namespace"


def test_create_origin_pool():
    """XCClient.create_origin_pool creates with full payload."""
    from shared.xc_client import XCClient

    with patch('shared.xc_client.requests.Session') as mock_session_class:
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        whoami_response = MagicMock()
        whoami_response.status_code = 200
        whoami_response.json.return_value = {"user": "test"}
        mock_session.get.return_value = whoami_response

        post_response = MagicMock()
        post_response.status_code = 200
        post_response.json.return_value = {"metadata": {"name": "pool1"}}
        mock_session.post.return_value = post_response

        client = XCClient("https://test.console.ves.volterra.io", "token")
        payload = {
            "metadata": {"name": "pool1", "namespace": "ns1"},
            "spec": {"port": 80}
        }
        result = client.create_origin_pool("ns1", payload)

        call_args = mock_session.post.call_args
        assert "/api/config/namespaces/ns1/origin_pools" in call_args[0][0]
        assert call_args[1]["json"] == payload
