# tests/test_shared/test_job_config.py
import pytest
from shared.job_config import (
    JobConfig,
    validate_job_config,
    substitute_variables,
    validate_runtime_variables,
)


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


def test_substitute_variables_undefined_raises_error():
    """Undefined variables raise ValueError."""
    template = {"name": "{{petname}}-pool", "owner": "{{undefined_var}}"}
    variables = {"petname": "fuzzy-cat"}
    with pytest.raises(ValueError, match="Unsubstituted variables: undefined_var"):
        substitute_variables(template, variables)


# Tests for input validation


def test_validate_job_config_invalid_job_id_with_spaces():
    """job_id with spaces raises error."""
    config = {"job_id": "test job", "ssm_base_path": "/tenantOps/test"}
    with pytest.raises(ValueError, match="Invalid job_id"):
        validate_job_config(config)


def test_validate_job_config_invalid_job_id_with_special_chars():
    """job_id with special characters raises error."""
    config = {"job_id": "test@job!", "ssm_base_path": "/tenantOps/test"}
    with pytest.raises(ValueError, match="Invalid job_id"):
        validate_job_config(config)


def test_validate_job_config_invalid_job_id_path_injection():
    """job_id with path traversal raises error."""
    config = {"job_id": "../etc/passwd", "ssm_base_path": "/tenantOps/test"}
    with pytest.raises(ValueError, match="Invalid job_id"):
        validate_job_config(config)


def test_validate_job_config_ssm_base_path_not_starting_with_slash():
    """ssm_base_path not starting with / raises error."""
    config = {"job_id": "test-job", "ssm_base_path": "tenantOps/test"}
    with pytest.raises(ValueError, match="must start with '/'"):
        validate_job_config(config)


def test_validate_job_config_ssm_base_path_with_special_chars():
    """ssm_base_path with invalid characters raises error."""
    config = {"job_id": "test-job", "ssm_base_path": "/tenant@Ops/test!"}
    with pytest.raises(ValueError, match="Invalid ssm_base_path"):
        validate_job_config(config)


def test_validate_job_config_ssm_base_path_with_path_traversal():
    """ssm_base_path with path traversal raises error."""
    config = {"job_id": "test-job", "ssm_base_path": "/tenantOps/../etc/passwd"}
    with pytest.raises(ValueError, match="Invalid ssm_base_path"):
        validate_job_config(config)


def test_validate_runtime_variables_valid():
    """Valid email and petname pass validation."""
    validate_runtime_variables("user@example.com", "fuzzy-cat-123")


def test_validate_runtime_variables_invalid_email_no_at():
    """Email without @ raises error."""
    with pytest.raises(ValueError, match="Invalid email"):
        validate_runtime_variables("userexample.com", "fuzzy-cat")


def test_validate_runtime_variables_invalid_email_empty():
    """Empty email raises error."""
    with pytest.raises(ValueError, match="Invalid email"):
        validate_runtime_variables("", "fuzzy-cat")


def test_validate_runtime_variables_invalid_petname_with_underscore():
    """Petname with underscore raises error."""
    with pytest.raises(ValueError, match="Invalid petname"):
        validate_runtime_variables("user@example.com", "fuzzy_cat")


def test_validate_runtime_variables_invalid_petname_with_special_chars():
    """Petname with special characters raises error."""
    with pytest.raises(ValueError, match="Invalid petname"):
        validate_runtime_variables("user@example.com", "fuzzy@cat!")


def test_validate_runtime_variables_invalid_petname_empty():
    """Empty petname raises error."""
    with pytest.raises(ValueError, match="Invalid petname"):
        validate_runtime_variables("user@example.com", "")
