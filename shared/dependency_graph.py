"""Dependency graph builder for resource orchestration."""

from typing import Dict, List, Sequence, Set
from .job_config import ResourceDefinition


class DependencyCycleError(Exception):
    """Raised when a circular dependency is detected."""
    pass


class MissingDependencyError(Exception):
    """Raised when a resource depends on a non-existent resource."""
    pass


class DuplicateResourceError(Exception):
    """Raised when multiple resources have the same name."""
    pass


class InvalidResourceError(Exception):
    """Raised when a resource definition is invalid."""
    pass


def _find_cycle(name: str, dependents: Dict[str, List[str]], in_degree: Dict[str, int]) -> List[str]:
    """Find one cycle path starting from the given node using DFS."""
    visited = set()
    path = []

    def dfs(current: str) -> bool:
        if current in visited:
            # Found cycle - extract the cycle portion
            cycle_start = path.index(current)
            return True
        visited.add(current)
        path.append(current)
        for dep in dependents.get(current, []):
            if in_degree.get(dep, 0) > 0:  # Only follow unresolved deps
                if dfs(dep):
                    return True
        path.pop()
        visited.remove(current)
        return False

    dfs(name)
    return path


def build_execution_order(resources: Sequence[ResourceDefinition]) -> List[List[ResourceDefinition]]:
    """Build execution levels from resource dependencies.

    Groups resources by execution level using topological sort.
    Level 0 contains resources with no dependencies, level 1 contains
    resources that only depend on level 0, etc.

    Args:
        resources: Sequence of resource definitions with depends_on fields.

    Returns:
        List of lists, where each inner list contains resources that
        can be executed in parallel at that level.

    Raises:
        DependencyCycleError: If circular dependencies are detected.
        MissingDependencyError: If a resource depends on a non-existent resource.
        DuplicateResourceError: If multiple resources have the same name.
        InvalidResourceError: If a resource is missing required 'name' in metadata.
    """
    if not resources:
        return []

    # Build name -> resource mapping with validation
    resource_map: Dict[str, ResourceDefinition] = {}
    for idx, resource in enumerate(resources):
        if "name" not in resource.metadata:
            raise InvalidResourceError(
                f"Resource at index {idx} missing required 'name' in metadata"
            )
        name = resource.metadata["name"]
        if name in resource_map:
            raise DuplicateResourceError(
                f"Duplicate resource name '{name}': found at multiple positions"
            )
        resource_map[name] = resource

    # Validate all dependencies exist
    for resource in resources:
        name = resource.metadata["name"]
        for dep in resource.depends_on:
            if dep not in resource_map:
                raise MissingDependencyError(
                    f"Resource '{name}' depends on '{dep}' which does not exist"
                )

    # Build dependency graph
    # in_degree[name] = number of unresolved dependencies
    in_degree: Dict[str, int] = {r.metadata["name"]: 0 for r in resources}
    # dependents[name] = list of resources that depend on this one
    dependents: Dict[str, List[str]] = {r.metadata["name"]: [] for r in resources}

    for resource in resources:
        name = resource.metadata["name"]
        for dep in resource.depends_on:
            in_degree[name] += 1
            dependents[dep].append(name)

    # Kahn's algorithm for topological sort by level
    levels: List[List[ResourceDefinition]] = []
    remaining: Set[str] = set(in_degree.keys())

    while remaining:
        # Find all resources with no remaining dependencies
        ready = [name for name in remaining if in_degree[name] == 0]

        if not ready:
            # Cycle detected - find and report the cycle
            cycle_start = next(iter(remaining))
            cycle_path = _find_cycle(cycle_start, dependents, in_degree)
            if cycle_path:
                cycle_str = " -> ".join(cycle_path + [cycle_path[0]])
                raise DependencyCycleError(
                    f"Circular dependency detected: {cycle_str}"
                )
            else:
                raise DependencyCycleError(
                    f"Circular dependency detected among: {remaining}"
                )

        # Add this level
        level = [resource_map[name] for name in ready]
        levels.append(level)

        # Remove from remaining and update in_degrees
        for name in ready:
            remaining.remove(name)
            for dependent in dependents[name]:
                in_degree[dependent] -= 1

    return levels
