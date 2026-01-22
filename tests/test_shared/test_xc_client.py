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
