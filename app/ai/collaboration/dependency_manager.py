"""Task dependency graph for a collaboration.

Provides validation (unknown edges, self-edges, cycles), topological ordering,
parallel execution waves and failure propagation.
"""

from __future__ import annotations

from collections import defaultdict

from app.ai.schemas.collaboration_schema import CollaborationTaskSpec
from app.core.exceptions import ValidationError


class DependencyError(ValidationError):
    default_user_message = "The collaboration plan has an invalid dependency graph."


class DependencyGraph:
    """Directed acyclic graph of collaboration tasks."""

    def __init__(self, tasks: list[CollaborationTaskSpec]) -> None:
        self._raw_tasks = list(tasks)
        self._tasks = {task.task_key: task for task in tasks}
        self._dependencies: dict[str, list[str]] = {
            task.task_key: list(task.depends_on) for task in tasks
        }

    # -- basics ------------------------------------------------------------
    @property
    def task_keys(self) -> list[str]:
        return list(self._tasks)

    def task(self, key: str) -> CollaborationTaskSpec:
        if key not in self._tasks:
            raise DependencyError(f"Unknown task '{key}'")
        return self._tasks[key]

    def dependencies_of(self, key: str) -> list[str]:
        return list(self._dependencies.get(key, []))

    def dependents_of(self, key: str) -> list[str]:
        return [task for task, deps in self._dependencies.items() if key in deps]

    def edges(self) -> list[tuple[str, str]]:
        return [(task, dep) for task, deps in self._dependencies.items() for dep in deps]

    # -- validation --------------------------------------------------------
    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self._tasks:
            errors.append("the plan has no tasks")
        seen: set[str] = set()
        for task in self._raw_tasks:
            if task.task_key in seen:
                errors.append(f"duplicate task key '{task.task_key}'")
            seen.add(task.task_key)

        for key, deps in self._dependencies.items():
            for dep in deps:
                if dep == key:
                    errors.append(f"task '{key}' depends on itself")
                elif dep not in self._tasks:
                    errors.append(f"task '{key}' depends on unknown task '{dep}'")

        cycle = self._find_cycle()
        if cycle:
            errors.append("circular dependency: " + " → ".join(cycle))
        return errors

    def _find_cycle(self) -> list[str] | None:
        state: dict[str, int] = {}
        stack: list[str] = []

        def visit(node: str) -> list[str] | None:
            state[node] = 1
            stack.append(node)
            for dep in self._dependencies.get(node, []):
                if dep not in self._tasks:
                    continue
                if state.get(dep) == 1:
                    index = stack.index(dep)
                    return stack[index:] + [dep]
                if state.get(dep, 0) == 0:
                    found = visit(dep)
                    if found:
                        return found
            stack.pop()
            state[node] = 2
            return None

        for key in self._tasks:
            if state.get(key, 0) == 0:
                found = visit(key)
                if found:
                    return found
        return None

    # -- ordering ----------------------------------------------------------
    def topological_order(self) -> list[str]:
        errors = self.validate()
        if errors:
            raise DependencyError("; ".join(errors))

        indegree = {key: len(deps) for key, deps in self._dependencies.items()}

        ready = sorted([key for key, degree in indegree.items() if degree == 0])
        order: list[str] = []
        while ready:
            key = ready.pop(0)
            order.append(key)
            for dependent in self.dependents_of(key):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
            ready.sort()
        return order

    def waves(self) -> list[list[str]]:
        """Groups of tasks that can run in parallel."""
        remaining = set(self._tasks)
        completed: set[str] = set()
        waves: list[list[str]] = []
        while remaining:
            wave = sorted(
                key
                for key in remaining
                if all(dep in completed for dep in self._dependencies.get(key, []))
            )
            if not wave:
                raise DependencyError("the plan contains a cycle and cannot be ordered")
            waves.append(wave)
            completed.update(wave)
            remaining.difference_update(wave)
        return waves

    def ready_tasks(self, completed: set[str], blocked: set[str] | None = None) -> list[str]:
        """Tasks whose dependencies are all satisfied and which are not blocked."""
        blocked = blocked or set()
        return sorted(
            key
            for key, deps in self._dependencies.items()
            if key not in completed
            and key not in blocked
            and all(dep in completed for dep in deps)
        )

    # -- failure handling --------------------------------------------------
    def propagate_failure(self, failed: str) -> list[str]:
        """Every downstream task that can no longer run."""
        affected: list[str] = []
        queue = [failed]
        while queue:
            current = queue.pop(0)
            for dependent in self.dependents_of(current):
                if dependent not in affected:
                    affected.append(dependent)
                    queue.append(dependent)
        return affected

    def blocked_after(self, failed_keys: set[str]) -> set[str]:
        blocked: set[str] = set()
        for key in failed_keys:
            blocked.update(self.propagate_failure(key))
        return blocked - failed_keys

    def describe(self) -> dict[str, list[str]]:
        """Adjacency map, used for the UI graph and checkpoint payloads."""
        adjacency: dict[str, list[str]] = defaultdict(list)
        for task, dep in self.edges():
            adjacency[task].append(dep)
        return {key: sorted(value) for key, value in adjacency.items()}
