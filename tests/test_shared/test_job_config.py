# tests/test_shared/test_job_config.py
import pytest
from shared.job_config import JobConfig, validate_job_config, substitute_variables


def test_validate_job_config_minimal():
    """Minimal valid job config with just user provisioning."""
    config = {
        "job_id": "test-job",
        "ssm_base_path": "/tenantOps/test",
        "user": {"enabled": True, "group_names": [], "namespace_roles": []},
        "namespace": {"enabled": False},
        "resources": []
    }
    result = validate_job_config(config)
    assert result.job_id == "test-job"
    assert result.user.enabled is True


def test_validate_job_config_with_resources():
    """Job config with resource definitions."""
    config = {
        "job_id": "api-lab",
        "ssm_base_path": "/tenantOps/sec-lab",
        "user": {"enabled": True, "group_names": ["lab-users"], "namespace_roles": []},
        "namespace": {"enabled": True},
        "resources": [
            {
                "type": "origin_pool",
                "depends_on": [],
                "metadata": {"name": "{{petname}}-pool", "namespace": "{{petname}}"},
                "spec": {"port": 80}
            }
        ]
    }
    result = validate_job_config(config)
    assert len(result.resources) == 1
    assert result.resources[0].type == "origin_pool"


def test_validate_job_config_missing_required_field():
    """Missing required field raises error."""
    config = {"job_id": "test"}  # Missing ssm_base_path
    with pytest.raises(ValueError, match="ssm_base_path"):
        validate_job_config(config)


def test_substitute_variables():
    """Template variables are substituted correctly."""
    template = {"name": "{{petname}}-pool", "email": "{{email}}"}
    variables = {"petname": "fuzzy-cat", "email": "user@test.com"}
    result = substitute_variables(template, variables)
    assert result["name"] == "fuzzy-cat-pool"
    assert result["email"] == "user@test.com"
