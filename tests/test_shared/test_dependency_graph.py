import pytest
from shared.dependency_graph import (
    build_execution_order,
    DependencyCycleError,
    MissingDependencyError,
    DuplicateResourceError,
    InvalidResourceError,
)
from shared.job_config import ResourceDefinition


def test_build_execution_order_no_dependencies():
    """Resources with no dependencies run in parallel (level 0)."""
    resources = [
        ResourceDefinition(type="origin_pool", depends_on=[], metadata={"name": "pool-a"}, spec={}),
        ResourceDefinition(type="waf_policy", depends_on=[], metadata={"name": "waf-a"}, spec={}),
    ]
    levels = build_execution_order(resources)
    assert len(levels) == 1
    assert len(levels[0]) == 2


def test_build_execution_order_with_dependencies():
    """Resources execute in dependency order."""
    resources = [
        ResourceDefinition(type="origin_pool", depends_on=[], metadata={"name": "pool-a"}, spec={}),
        ResourceDefinition(type="waf_policy", depends_on=[], metadata={"name": "waf-a"}, spec={}),
        ResourceDefinition(type="http_lb", depends_on=["pool-a", "waf-a"], metadata={"name": "lb-a"}, spec={}),
    ]
    levels = build_execution_order(resources)
    assert len(levels) == 2
    # Level 0: pool-a, waf-a (no dependencies)
    level_0_names = {r.metadata["name"] for r in levels[0]}
    assert level_0_names == {"pool-a", "waf-a"}
    # Level 1: lb-a (depends on level 0)
    assert levels[1][0].metadata["name"] == "lb-a"


def test_build_execution_order_cycle_detection():
    """Circular dependency raises error with cycle path."""
    resources = [
        ResourceDefinition(type="a", depends_on=["b"], metadata={"name": "a"}, spec={}),
        ResourceDefinition(type="b", depends_on=["a"], metadata={"name": "b"}, spec={}),
    ]
    with pytest.raises(DependencyCycleError) as exc_info:
        build_execution_order(resources)
    # Error message should indicate a cycle path
    assert "Circular dependency detected" in str(exc_info.value)


def test_build_execution_order_empty():
    """Empty resources list returns empty levels."""
    levels = build_execution_order([])
    assert levels == []


def test_build_execution_order_missing_dependency():
    """Dependency on non-existent resource raises error."""
    resources = [
        ResourceDefinition(type="http_lb", depends_on=["pool-a"], metadata={"name": "lb-a"}, spec={}),
    ]
    with pytest.raises(MissingDependencyError) as exc_info:
        build_execution_order(resources)
    assert "lb-a" in str(exc_info.value)
    assert "pool-a" in str(exc_info.value)
    assert "does not exist" in str(exc_info.value)


def test_build_execution_order_duplicate_names():
    """Duplicate resource names raise error."""
    resources = [
        ResourceDefinition(type="origin_pool", depends_on=[], metadata={"name": "pool-a"}, spec={"port": 80}),
        ResourceDefinition(type="origin_pool", depends_on=[], metadata={"name": "pool-a"}, spec={"port": 443}),
    ]
    with pytest.raises(DuplicateResourceError) as exc_info:
        build_execution_order(resources)
    assert "pool-a" in str(exc_info.value)
    assert "Duplicate" in str(exc_info.value)


def test_build_execution_order_missing_name_in_metadata():
    """Resource without name in metadata raises error."""
    resources = [
        ResourceDefinition(type="origin_pool", depends_on=[], metadata={"namespace": "test"}, spec={}),
    ]
    with pytest.raises(InvalidResourceError) as exc_info:
        build_execution_order(resources)
    assert "index 0" in str(exc_info.value)
    assert "name" in str(exc_info.value)


def test_build_execution_order_three_levels():
    """Resources form three execution levels."""
    resources = [
        ResourceDefinition(type="origin_pool", depends_on=[], metadata={"name": "pool"}, spec={}),
        ResourceDefinition(type="waf_policy", depends_on=["pool"], metadata={"name": "waf"}, spec={}),
        ResourceDefinition(type="http_lb", depends_on=["waf"], metadata={"name": "lb"}, spec={}),
    ]
    levels = build_execution_order(resources)
    assert len(levels) == 3
    assert levels[0][0].metadata["name"] == "pool"
    assert levels[1][0].metadata["name"] == "waf"
    assert levels[2][0].metadata["name"] == "lb"
