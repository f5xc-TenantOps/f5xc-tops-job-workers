import pytest
from unittest.mock import MagicMock, patch, call


@patch("securemesh_site_v2_create.function.boto3")
@patch("securemesh_site_v2_create.function.get_ssm_parameters")
@patch("securemesh_site_v2_create.function.XCClient")
def test_create_site_success(mock_xc_client_class, mock_get_params, mock_boto3):
    """Successfully create site, token, and write token to S3."""
    from securemesh_site_v2_create.function import create_site
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_securemesh_site_v2.return_value = {
        "metadata": {"name": "fuzzy-cat-site"},
        "spec": {"site_state": "WAITING_FOR_REGISTRATION"}
    }
    mock_client.create_registration_token.return_value = {
        "spec": {"content": "eyJhbGci.jwt.token", "site_name": "fuzzy-cat-site"}
    }
    mock_xc_client_class.return_value = mock_client

    mock_s3 = MagicMock()
    mock_boto3.client.return_value = mock_s3

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/mcn-lab",
        "metadata": {"name": "fuzzy-cat-site", "namespace": "system"},
        "spec": {"kvm": {"not_managed": {}}},
        "dep_id": "dep-123"
    }

    result = create_site(event, logger)

    assert result["status"] == "success"
    assert result["name"] == "fuzzy-cat-site"
    assert result["created"] is True

    # Verify site was created
    mock_client.create_securemesh_site_v2.assert_called_once()
    create_payload = mock_client.create_securemesh_site_v2.call_args[0][0]
    assert create_payload["metadata"]["name"] == "fuzzy-cat-site"
    assert create_payload["namespace"] == "system"

    # Verify token was created (name starts with jwt-token-)
    mock_client.create_registration_token.assert_called_once()
    token_call_args = mock_client.create_registration_token.call_args[0]
    assert token_call_args[0] == "fuzzy-cat-site"  # site_name
    assert token_call_args[1].startswith("jwt-token-")  # token_name

    # Verify token was written to S3
    mock_s3.put_object.assert_called_once()
    s3_call = mock_s3.put_object.call_args
    assert s3_call[1]["Key"] == "dep-123/site_token"
    assert s3_call[1]["Body"] == "eyJhbGci.jwt.token"


@patch("securemesh_site_v2_create.function.boto3")
@patch("securemesh_site_v2_create.function.get_ssm_parameters")
@patch("securemesh_site_v2_create.function.XCClient")
def test_create_site_already_exists(mock_xc_client_class, mock_get_params, mock_boto3):
    """Site already exists - still create token and write to S3."""
    from securemesh_site_v2_create.function import create_site
    from shared.logging import StructuredLogger
    from shared.errors import ResourceExistsError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_securemesh_site_v2.side_effect = ResourceExistsError("exists")
    mock_client.create_registration_token.return_value = {
        "spec": {"content": "eyJhbGci.jwt.token", "site_name": "fuzzy-cat-site"}
    }
    mock_xc_client_class.return_value = mock_client

    mock_s3 = MagicMock()
    mock_boto3.client.return_value = mock_s3

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/mcn-lab",
        "metadata": {"name": "fuzzy-cat-site", "namespace": "system"},
        "spec": {"kvm": {"not_managed": {}}},
        "dep_id": "dep-123"
    }

    result = create_site(event, logger)

    assert result["status"] == "success"
    assert result["already_existed"] is True

    # Token should still be created even if site already existed
    mock_client.create_registration_token.assert_called_once()
    mock_s3.put_object.assert_called_once()


@patch("securemesh_site_v2_create.function.boto3")
@patch("securemesh_site_v2_create.function.get_ssm_parameters")
@patch("securemesh_site_v2_create.function.XCClient")
def test_create_site_dep_id_from_job_state(mock_xc_client_class, mock_get_params, mock_boto3):
    """dep_id extracted from job_state when not a top-level event key."""
    from securemesh_site_v2_create.function import create_site
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_securemesh_site_v2.return_value = {"metadata": {"name": "test-site"}}
    mock_client.create_registration_token.return_value = {
        "spec": {"content": "eyJhbGci.jwt.token", "site_name": "test-site"}
    }
    mock_xc_client_class.return_value = mock_client

    mock_s3 = MagicMock()
    mock_boto3.client.return_value = mock_s3

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/mcn-lab",
        "metadata": {"name": "test-site", "namespace": "system"},
        "spec": {"kvm": {"not_managed": {}}},
        "job_state": {"dep_id": "dep-456"}
    }

    result = create_site(event, logger)

    assert result["status"] == "success"
    mock_s3.put_object.assert_called_once()
    s3_call = mock_s3.put_object.call_args
    assert s3_call[1]["Key"] == "dep-456/site_token"


@patch("securemesh_site_v2_create.function.boto3")
@patch("securemesh_site_v2_create.function.get_ssm_parameters")
@patch("securemesh_site_v2_create.function.XCClient")
def test_create_site_no_dep_id_skips_s3(mock_xc_client_class, mock_get_params, mock_boto3):
    """When no dep_id is provided, skip S3 write."""
    from securemesh_site_v2_create.function import create_site
    from shared.logging import StructuredLogger

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_securemesh_site_v2.return_value = {"metadata": {"name": "test-site"}}
    mock_client.create_registration_token.return_value = {
        "spec": {"content": "eyJhbGci.jwt.token", "site_name": "test-site"}
    }
    mock_xc_client_class.return_value = mock_client

    mock_s3 = MagicMock()
    mock_boto3.client.return_value = mock_s3

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/mcn-lab",
        "metadata": {"name": "test-site", "namespace": "system"},
        "spec": {"kvm": {"not_managed": {}}}
        # No dep_id
    }

    result = create_site(event, logger)

    assert result["status"] == "success"
    mock_s3.put_object.assert_not_called()


@patch("securemesh_site_v2_create.function.boto3")
@patch("securemesh_site_v2_create.function.get_ssm_parameters")
@patch("securemesh_site_v2_create.function.XCClient")
def test_create_site_permanent_error_raises(mock_xc_client_class, mock_get_params, mock_boto3):
    """Permanent errors from site creation propagate."""
    from securemesh_site_v2_create.function import create_site
    from shared.logging import StructuredLogger
    from shared.errors import PermanentError

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_securemesh_site_v2.side_effect = PermanentError("Invalid payload")
    mock_xc_client_class.return_value = mock_client

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "ssm_base_path": "/tenantOps/mcn-lab",
        "metadata": {"name": "test-site", "namespace": "system"},
        "spec": {"kvm": {"not_managed": {}}}
    }

    with pytest.raises(PermanentError):
        create_site(event, logger)


@patch("securemesh_site_v2_create.function.boto3")
@patch("securemesh_site_v2_create.function.get_ssm_parameters")
@patch("securemesh_site_v2_create.function.XCClient")
def test_handler_state_tracking(mock_xc_client_class, mock_get_params, mock_boto3):
    """Handler tracks resource state via job_state."""
    from securemesh_site_v2_create.function import handler

    mock_get_params.return_value = {
        "tenant-url": "https://test.console.ves.volterra.io",
        "token-value": "token"
    }

    mock_client = MagicMock()
    mock_client.create_securemesh_site_v2.return_value = {"metadata": {"name": "test-site"}}
    mock_client.create_registration_token.return_value = {
        "spec": {"content": "jwt", "site_name": "test-site"}
    }
    mock_xc_client_class.return_value = mock_client
    mock_boto3.client.return_value = MagicMock()

    class MockContext:
        function_name = "securemesh_site_v2_create"

    event = {
        "ssm_base_path": "/tenantOps/mcn-lab",
        "metadata": {"name": "test-site", "namespace": "system"},
        "spec": {"kvm": {"not_managed": {}}},
        "dep_id": "dep-123"
    }

    result = handler(event, MockContext())

    assert result["statusCode"] == 200
    assert result["body"]["status"] == "success"
