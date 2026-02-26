import pytest


def test_prepare_job_config_from_event():
    """Job config passed directly in event."""
    from prepare_job_config.function import prepare_config
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

    result = prepare_config(event, logger)
    assert result["job_config"]["job_id"] == "test-job"
    assert result["variables"]["petname"] == "fuzzy-cat"


def test_prepare_job_config_rejects_missing_config():
    """Event without job_config raises PermanentError."""
    from prepare_job_config.function import prepare_config
    from shared.errors import PermanentError
    from shared.logging import StructuredLogger

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "email": "user@test.com",
        "petname": "fuzzy-cat"
    }

    with pytest.raises(PermanentError, match="Event must contain 'job_config'"):
        prepare_config(event, logger)


def test_prepare_job_config_substitutes_variables():
    """Template variables are substituted in resource specs."""
    from prepare_job_config.function import prepare_config
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

    result = prepare_config(event, logger)
    assert result["job_config"]["resources"][0]["metadata"]["name"] == "fuzzy-cat-pool"


def test_prepare_job_config_substitutes_namespace_roles():
    """Template variables are substituted in user namespace_roles."""
    from prepare_job_config.function import prepare_config
    from shared.logging import StructuredLogger

    logger = StructuredLogger("test", "test-correlation-id")
    event = {
        "job_config": {
            "job_id": "test-job",
            "ssm_base_path": "/test",
            "user": {
                "enabled": True,
                "group_names": ["xc-lab-users"],
                "namespace_roles": [
                    {"namespace": "system", "role": "xc-lab-mcn-ce"},
                    {"namespace": "{{petname}}", "role": "ves-io-admin-role"},
                ],
            },
            "namespace": {"enabled": True},
            "resources": [],
        },
        "email": "user@test.com",
        "petname": "fuzzy-cat",
    }

    result = prepare_config(event, logger)
    roles = result["job_config"]["user"]["namespace_roles"]
    assert roles[0] == {"namespace": "system", "role": "xc-lab-mcn-ce"}
    assert roles[1] == {"namespace": "fuzzy-cat", "role": "ves-io-admin-role"}
