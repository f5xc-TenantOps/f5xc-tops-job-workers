# tests/test_cert_mgmt.py
import base64
import pytest
from unittest.mock import MagicMock, patch
from io import BytesIO


class MockContext:
    function_name = "cert_mgmt"


@patch.dict("os.environ", {
    "SSM_BASE_PATH": "/tenantOps/test",
    "S3_BUCKET": "test-bucket",
    "CERT_NAME": "wildcard.example.com"
})
@patch("cert_mgmt.function.get_ssm_parameters")
@patch("cert_mgmt.function.XCClient")
@patch("cert_mgmt.function.boto3")
def test_handler_create_certificate_success(mock_boto3, mock_xc_client, mock_get_params):
    """Successfully create a new certificate."""
    from cert_mgmt.function import handler

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_certificate.return_value = {}
    mock_xc_client.return_value = mock_client

    mock_s3 = MagicMock()
    mock_s3.get_object.side_effect = [
        {"Body": BytesIO(b"cert-data")},
        {"Body": BytesIO(b"key-data")}
    ]
    mock_boto3.client.return_value = mock_s3

    result = handler({}, MockContext())

    assert result["statusCode"] == 200
    assert "created" in result["body"]
    mock_client.create_certificate.assert_called_once()
    call_args = mock_client.create_certificate.call_args
    assert call_args[0][0] == "shared"
    assert call_args[0][1] == "wildcard.example.com"
    assert call_args[0][2] == base64.b64encode(b"cert-data").decode("utf-8")
    assert call_args[0][3] == base64.b64encode(b"key-data").decode("utf-8")


@patch.dict("os.environ", {
    "SSM_BASE_PATH": "/tenantOps/test",
    "S3_BUCKET": "test-bucket",
    "CERT_NAME": "wildcard.example.com"
})
@patch("cert_mgmt.function.get_ssm_parameters")
@patch("cert_mgmt.function.XCClient")
@patch("cert_mgmt.function.boto3")
def test_handler_replace_certificate_when_exists(mock_boto3, mock_xc_client, mock_get_params):
    """Replace certificate when it already exists."""
    from cert_mgmt.function import handler
    from shared.errors import ResourceExistsError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_certificate.side_effect = ResourceExistsError("already exists")
    mock_client.replace_certificate.return_value = {}
    mock_xc_client.return_value = mock_client

    mock_s3 = MagicMock()
    mock_s3.get_object.side_effect = [
        {"Body": BytesIO(b"cert-data")},
        {"Body": BytesIO(b"key-data")}
    ]
    mock_boto3.client.return_value = mock_s3

    result = handler({}, MockContext())

    assert result["statusCode"] == 200
    assert "replaced" in result["body"]
    mock_client.create_certificate.assert_called_once()
    mock_client.replace_certificate.assert_called_once()


@patch.dict("os.environ", {
    "S3_BUCKET": "test-bucket",
    "CERT_NAME": "wildcard.example.com"
})
def test_handler_missing_ssm_base_path():
    """Raise PermanentError when SSM_BASE_PATH is missing."""
    from cert_mgmt.function import handler

    result = handler({}, MockContext())

    assert result["statusCode"] == 400
    assert "SSM_BASE_PATH" in result["body"]


@patch.dict("os.environ", {
    "SSM_BASE_PATH": "/tenantOps/test",
    "CERT_NAME": "wildcard.example.com"
})
def test_handler_missing_s3_bucket():
    """Raise PermanentError when S3_BUCKET is missing."""
    from cert_mgmt.function import handler

    result = handler({}, MockContext())

    assert result["statusCode"] == 400
    assert "S3_BUCKET" in result["body"]


@patch.dict("os.environ", {
    "SSM_BASE_PATH": "/tenantOps/test",
    "S3_BUCKET": "test-bucket"
})
def test_handler_missing_cert_name():
    """Raise PermanentError when CERT_NAME is missing."""
    from cert_mgmt.function import handler

    result = handler({}, MockContext())

    assert result["statusCode"] == 400
    assert "CERT_NAME" in result["body"]


def test_upload_cert_to_tenant_create():
    """Create certificate when it does not exist."""
    from cert_mgmt.function import upload_cert_to_tenant

    mock_client = MagicMock()
    mock_client.create_certificate.return_value = {}

    result = upload_cert_to_tenant(
        client=mock_client,
        name="test-cert",
        cert_data=b"cert-data",
        key_data=b"key-data",
        namespace="shared"
    )

    assert "created" in result
    mock_client.create_certificate.assert_called_once_with(
        "shared",
        "test-cert",
        base64.b64encode(b"cert-data").decode("utf-8"),
        base64.b64encode(b"key-data").decode("utf-8")
    )


def test_upload_cert_to_tenant_replace():
    """Replace certificate when it already exists."""
    from cert_mgmt.function import upload_cert_to_tenant
    from shared.errors import ResourceExistsError

    mock_client = MagicMock()
    mock_client.create_certificate.side_effect = ResourceExistsError("exists")
    mock_client.replace_certificate.return_value = {}

    result = upload_cert_to_tenant(
        client=mock_client,
        name="test-cert",
        cert_data=b"cert-data",
        key_data=b"key-data",
        namespace="shared"
    )

    assert "replaced" in result
    mock_client.replace_certificate.assert_called_once()


def test_fetch_cert_from_s3():
    """Fetch certificate and key from S3."""
    from cert_mgmt.function import fetch_cert_from_s3

    mock_s3 = MagicMock()
    mock_s3.get_object.side_effect = [
        {"Body": BytesIO(b"cert-content")},
        {"Body": BytesIO(b"key-content")}
    ]

    cert_data, key_data = fetch_cert_from_s3(
        mock_s3, "bucket", "cert.pem", "key.pem"
    )

    assert cert_data == b"cert-content"
    assert key_data == b"key-content"
    assert mock_s3.get_object.call_count == 2
