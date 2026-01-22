import pytest
from unittest.mock import MagicMock, patch


def test_fetch_job_config_from_event():
    """Job config passed directly in event."""
    from fetch_job_config.function import fetch_config
    from shared.logging import StructuredLogger

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "job_config": {
            "job_id": "test-job",
            "ssm_base_path": "/test",
            "user": {"enabled": True, "group_names": [], "namespace_roles": []},
            "namespace": {"enabled": False},
            "resources": []
        },
        "email": "user@test.com",
        "petname": "fuzzy-cat"
    }

    result = fetch_config(event, logger)
    assert result["job_config"]["job_id"] == "test-job"
    assert result["variables"]["petname"] == "fuzzy-cat"


@patch("fetch_job_config.function._get_dynamodb_client")
def test_fetch_job_config_from_dynamodb(mock_get_client):
    """Job config fetched from DynamoDB by job_id."""
    from fetch_job_config.function import fetch_config
    from shared.logging import StructuredLogger

    mock_dynamodb = MagicMock()
    mock_get_client.return_value = mock_dynamodb
    mock_dynamodb.get_item.return_value = {
        "Item": {
            "job_id": {"S": "api-lab"},
            "ssm_base_path": {"S": "/tenantOps/sec-lab"},
            "user": {"M": {"enabled": {"BOOL": True}, "group_names": {"L": []}, "namespace_roles": {"L": []}}},
            "namespace": {"M": {"enabled": {"BOOL": True}}},
            "resources": {"L": []}
        }
    }

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "job_id": "api-lab",
        "email": "user@test.com",
        "petname": "fuzzy-cat"
    }

    result = fetch_config(event, logger)
    assert result["job_config"]["job_id"] == "api-lab"


def test_fetch_job_config_substitutes_variables():
    """Template variables are substituted in resource specs."""
    from fetch_job_config.function import fetch_config
    from shared.logging import StructuredLogger

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "job_config": {
            "job_id": "test-job",
            "ssm_base_path": "/test",
            "user": {"enabled": False, "group_names": [], "namespace_roles": []},
            "namespace": {"enabled": True},
            "resources": [
                {
                    "type": "origin_pool",
                    "depends_on": [],
                    "metadata": {"name": "{{petname}}-pool", "namespace": "{{petname}}"},
                    "spec": {"port": 80}
                }
            ]
        },
        "email": "user@test.com",
        "petname": "fuzzy-cat"
    }

    result = fetch_config(event, logger)
    assert result["job_config"]["resources"][0]["metadata"]["name"] == "fuzzy-cat-pool"
