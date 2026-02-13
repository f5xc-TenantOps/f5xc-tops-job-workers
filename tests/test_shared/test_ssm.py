import pytest
from unittest.mock import MagicMock, patch

from shared.errors import PermanentError, TransientError


class TestGetSsmParameters:
    """Tests for get_ssm_parameters()."""

    @patch("boto3.session.Session")
    def test_happy_path_returns_all_parameters(self, mock_session_cls):
        from shared.ssm import get_ssm_parameters

        mock_ssm = MagicMock()
        mock_session = MagicMock()
        mock_session.region_name = "us-east-1"
        mock_session.client.return_value = mock_ssm
        mock_session_cls.return_value = mock_session

        mock_ssm.get_parameters.return_value = {
            "Parameters": [
                {"Name": "/tenantOps/lab1/tenant-url", "Value": "https://tenant.example.com"},
                {"Name": "/tenantOps/lab1/api-token", "Value": "tok-abc123"},
            ],
            "InvalidParameters": [],
        }

        result = get_ssm_parameters(
            ["/tenantOps/lab1/tenant-url", "/tenantOps/lab1/api-token"]
        )

        assert result == {
            "tenant-url": "https://tenant.example.com",
            "api-token": "tok-abc123",
        }

    @patch("boto3.session.Session")
    def test_invalid_parameters_raises_permanent_error(self, mock_session_cls):
        from shared.ssm import get_ssm_parameters

        mock_ssm = MagicMock()
        mock_session = MagicMock()
        mock_session.region_name = "us-east-1"
        mock_session.client.return_value = mock_ssm
        mock_session_cls.return_value = mock_session

        mock_ssm.get_parameters.return_value = {
            "Parameters": [],
            "InvalidParameters": ["/tenantOps/wrong/tenant-url", "/tenantOps/wrong/api-token"],
        }

        with pytest.raises(PermanentError, match="SSM parameters not found"):
            get_ssm_parameters(
                ["/tenantOps/wrong/tenant-url", "/tenantOps/wrong/api-token"]
            )

    @patch("boto3.session.Session")
    def test_missing_parameters_raises_permanent_error(self, mock_session_cls):
        """Parameters not in InvalidParameters but also not returned."""
        from shared.ssm import get_ssm_parameters

        mock_ssm = MagicMock()
        mock_session = MagicMock()
        mock_session.region_name = "us-east-1"
        mock_session.client.return_value = mock_ssm
        mock_session_cls.return_value = mock_session

        mock_ssm.get_parameters.return_value = {
            "Parameters": [
                {"Name": "/tenantOps/lab1/tenant-url", "Value": "https://tenant.example.com"},
            ],
            "InvalidParameters": [],
        }

        with pytest.raises(PermanentError, match="SSM parameters missing from response"):
            get_ssm_parameters(
                ["/tenantOps/lab1/tenant-url", "/tenantOps/lab1/api-token"]
            )

    @patch("boto3.session.Session")
    def test_ssm_api_exception_raises_transient_error(self, mock_session_cls):
        from shared.ssm import get_ssm_parameters

        mock_ssm = MagicMock()
        mock_session = MagicMock()
        mock_session.region_name = "us-east-1"
        mock_session.client.return_value = mock_ssm
        mock_session_cls.return_value = mock_session

        mock_ssm.get_parameters.side_effect = Exception("Connection timeout")

        with pytest.raises(TransientError, match="Failed to fetch parameters"):
            get_ssm_parameters(["/tenantOps/lab1/tenant-url"])
