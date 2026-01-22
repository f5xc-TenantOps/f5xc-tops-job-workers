"""Job configuration schema and validation for provisioning workflows."""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class UserConfig:
    """User provisioning configuration."""
    enabled: bool = False
    group_names: List[str] = field(default_factory=list)
    namespace_roles: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class NamespaceConfig:
    """Namespace provisioning configuration."""
    enabled: bool = False


@dataclass
class ResourceDefinition:
    """Definition of a resource to create."""
    type: str
    depends_on: List[str]
    metadata: Dict[str, Any]
    spec: Dict[str, Any]


@dataclass
class JobConfig:
    """Complete job configuration."""
    job_id: str
    ssm_base_path: str
    user: UserConfig
    namespace: NamespaceConfig
    resources: List[ResourceDefinition] = field(default_factory=list)
    description: Optional[str] = None


def validate_job_config(config: Dict[str, Any]) -> JobConfig:
    """Validate and parse a job configuration dictionary.

    Args:
        config: Raw job configuration dictionary.

    Returns:
        Validated JobConfig object.

    Raises:
        ValueError: If required fields are missing or invalid.
    """
    required_fields = ["job_id", "ssm_base_path"]
    for field_name in required_fields:
        if field_name not in config:
            raise ValueError(f"Missing required field: {field_name}")

    # Validate job_id: alphanumeric with hyphens/underscores only
    job_id = config["job_id"]
    if not re.match(r'^[a-zA-Z0-9_-]+$', job_id):
        raise ValueError(
            f"Invalid job_id '{job_id}': must contain only alphanumeric characters, hyphens, and underscores"
        )

    # Validate ssm_base_path: must start with "/" and contain only safe characters
    ssm_base_path = config["ssm_base_path"]
    if not ssm_base_path.startswith("/"):
        raise ValueError(
            f"Invalid ssm_base_path '{ssm_base_path}': must start with '/'"
        )
    if not re.match(r'^[a-zA-Z0-9/_-]+$', ssm_base_path):
        raise ValueError(
            f"Invalid ssm_base_path '{ssm_base_path}': must contain only alphanumeric characters, hyphens, underscores, and forward slashes"
        )

    user_config = UserConfig()
    if "user" in config:
        user_data = config["user"]
        user_config = UserConfig(
            enabled=user_data.get("enabled", False),
            group_names=user_data.get("group_names", []),
            namespace_roles=user_data.get("namespace_roles", [])
        )

    namespace_config = NamespaceConfig()
    if "namespace" in config:
        namespace_config = NamespaceConfig(
            enabled=config["namespace"].get("enabled", False)
        )

    resources = []
    for res in config.get("resources", []):
        resources.append(ResourceDefinition(
            type=res["type"],
            depends_on=res.get("depends_on", []),
            metadata=res["metadata"],
            spec=res["spec"]
        ))

    return JobConfig(
        job_id=config["job_id"],
        ssm_base_path=config["ssm_base_path"],
        description=config.get("description"),
        user=user_config,
        namespace=namespace_config,
        resources=resources
    )


def substitute_variables(template: Any, variables: Dict[str, str]) -> Any:
    """Recursively substitute {{variable}} patterns in a template.

    Args:
        template: Dictionary, list, or string with {{variable}} patterns.
        variables: Dictionary of variable names to values.

    Returns:
        Template with variables substituted.

    Raises:
        ValueError: If any {{variable}} patterns remain unsubstituted.
    """
    if isinstance(template, str):
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        # Check for unsubstituted variables
        unsubstituted = re.findall(r'\{\{(\w+)\}\}', result)
        if unsubstituted:
            raise ValueError(f"Unsubstituted variables: {', '.join(unsubstituted)}")
        return result
    elif isinstance(template, dict):
        return {k: substitute_variables(v, variables) for k, v in template.items()}
    elif isinstance(template, list):
        return [substitute_variables(item, variables) for item in template]
    else:
        return template


def validate_runtime_variables(email: str, petname: str) -> None:
    """Validate runtime variables for email and petname.

    Args:
        email: User email address.
        petname: Unique identifier for the job instance.

    Raises:
        ValueError: If email or petname format is invalid.
    """
    # Validate email: basic @ check
    if not email or '@' not in email:
        raise ValueError(f"Invalid email '{email}': must contain '@'")

    # Validate petname: alphanumeric and hyphens only
    if not petname or not re.match(r'^[a-zA-Z0-9-]+$', petname):
        raise ValueError(
            f"Invalid petname '{petname}': must contain only alphanumeric characters and hyphens"
        )
