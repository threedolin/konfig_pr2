"""Build and display a dependency graph with iterative breadth-first search."""

from collections import deque
from dataclasses import dataclass, field


ROOT_DEPTH = 0


@dataclass
class DependencyGraph:
    """Store adjacency, shortest root distances and expanded vertices."""

    root: str
    max_depth: int
    adjacency: dict = field(default_factory=dict)
    depths: dict = field(default_factory=dict)
    expanded: set = field(default_factory=set)


def build_graph(root, dependency_names, max_depth):
    """Use a FIFO queue to explore each vertex once within the depth limit."""
    if max_depth < ROOT_DEPTH:
        raise ValueError("глубина не может быть отрицательной")
    graph = DependencyGraph(root, max_depth, {root: []}, {root: ROOT_DEPTH})
    pending = deque([root])
    while pending:
        package = pending.popleft()
        depth = graph.depths[package]
        if depth >= max_depth:
            continue
        dependencies = list(dict.fromkeys(dependency_names(package)))
        graph.adjacency[package] = dependencies
        graph.expanded.add(package)
        for dependency in dependencies:
            if dependency not in graph.depths:
                graph.depths[dependency] = depth + 1
                graph.adjacency[dependency] = []
                pending.append(dependency)
    return graph


def format_graph(graph):
    """Render adjacency in BFS order and distinguish unexpanded boundaries."""
    lines = [f"Граф зависимостей {graph.root} "
             f"(максимальная глубина: {graph.max_depth}):"]
    for package, depth in graph.depths.items():
        if package not in graph.expanded:
            targets = "(предел глубины)"
        else:
            targets = ", ".join(graph.adjacency[package]) or "(нет)"
        lines.append(f"  {package} [глубина={depth}]: {targets}")
    return "\n".join(lines)
