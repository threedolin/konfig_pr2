"""Tests for bounded breadth-first dependency graph construction."""

import sys
import unittest

from src.graph import build_graph, format_graph


class GraphTests(unittest.TestCase):
    """Check graph structure, traversal bounds and readable output."""

    def build_fixture(self, dependencies, max_depth, root="A"):
        """Build a fixture while recording every dependency request."""
        calls = []

        def dependency_names(name):
            """Record expansion order and return the node's neighbors."""
            calls.append(name)
            return dependencies.get(name, [])

        graph = build_graph(root, dependency_names, max_depth)
        return graph, calls

    def test_zero_depth_does_not_request_root_dependencies(self):
        """A zero-depth graph contains only the unexpanded root."""
        graph, calls = self.build_fixture({"A": ["B"]}, 0)
        self.assertEqual(graph.root, "A")
        self.assertEqual(graph.max_depth, 0)
        self.assertEqual(graph.adjacency, {"A": []})
        self.assertEqual(graph.depths, {"A": 0})
        self.assertEqual(graph.expanded, set())
        self.assertEqual(calls, [])

    def test_negative_depth_is_rejected_before_fetching(self):
        """Invalid depth must not cause any dependency requests."""
        def dependency_names(name):
            """Fail if invalid input reaches the repository."""
            self.fail("Dependencies must not be requested")

        with self.assertRaises(ValueError):
            build_graph("A", dependency_names, -1)

    def test_leaf_is_expanded_when_it_is_inside_the_limit(self):
        """A queried leaf differs from an unqueried boundary node."""
        graph, calls = self.build_fixture({"A": []}, 3)
        self.assertEqual(graph.adjacency, {"A": []})
        self.assertEqual(graph.depths, {"A": 0})
        self.assertEqual(graph.expanded, {"A"})
        self.assertEqual(calls, ["A"])

    def test_boundary_nodes_are_present_but_not_requested(self):
        """Retain nodes at the limit without requesting their dependencies."""
        dependencies = {
            "A": ["B", "C"], "B": ["D"], "C": ["E"],
            "D": ["F"], "E": ["G"],
        }
        graph, calls = self.build_fixture(dependencies, 2)
        self.assertEqual(graph.adjacency, {
            "A": ["B", "C"], "B": ["D"], "C": ["E"], "D": [], "E": [],
        })
        self.assertEqual(graph.depths, {
            "A": 0, "B": 1, "C": 1, "D": 2, "E": 2,
        })
        self.assertEqual(graph.expanded, {"A", "B", "C"})
        self.assertEqual(calls, ["A", "B", "C"])
        self.assertNotIn("F", graph.adjacency)
        self.assertNotIn("G", graph.adjacency)

    def test_diamond_keeps_both_edges_to_the_shared_node(self):
        """Keep shared dependencies for each parent, including at the limit."""
        dependencies = {
            "A": ["B", "C"], "B": ["D"], "C": ["D"], "D": ["E"],
        }
        graph, calls = self.build_fixture(dependencies, 2)
        self.assertEqual(graph.adjacency, {
            "A": ["B", "C"], "B": ["D"], "C": ["D"], "D": [],
        })
        self.assertEqual(graph.depths, {"A": 0, "B": 1, "C": 1, "D": 2})
        self.assertEqual(graph.expanded, {"A", "B", "C"})
        self.assertEqual(calls, ["A", "B", "C"])
        self.assertEqual(list(graph.adjacency), ["A", "B", "C", "D"])

    def test_shared_node_is_expanded_only_once(self):
        """Multiple incoming edges must not duplicate network requests."""
        dependencies = {
            "A": ["B", "C"], "B": ["D"], "C": ["D"], "D": [],
        }
        graph, calls = self.build_fixture(dependencies, 3)
        self.assertEqual(calls, ["A", "B", "C", "D"])
        self.assertEqual(graph.expanded, {"A", "B", "C", "D"})
        self.assertEqual(graph.adjacency["B"], ["D"])
        self.assertEqual(graph.adjacency["C"], ["D"])

    def test_breadth_first_search_preserves_shortest_depths(self):
        """A longer route must not hide a shorter route to the same node."""
        dependencies = {
            "A": ["B", "C"], "B": ["D"], "C": ["X"],
            "D": ["X"], "X": ["Y"], "Y": [],
        }
        graph, calls = self.build_fixture(dependencies, 3)
        self.assertEqual(calls, ["A", "B", "C", "D", "X"])
        self.assertEqual(graph.depths, {
            "A": 0, "B": 1, "C": 1, "D": 2, "X": 2, "Y": 3,
        })
        self.assertEqual(graph.adjacency["C"], ["X"])
        self.assertEqual(graph.adjacency["D"], ["X"])
        self.assertEqual(graph.adjacency["X"], ["Y"])
        self.assertEqual(graph.adjacency["Y"], [])
        self.assertEqual(graph.expanded, {"A", "B", "C", "D", "X"})
        self.assertEqual(calls.count("X"), 1)
        self.assertEqual(
            list(graph.adjacency), ["A", "B", "C", "D", "X", "Y"]
        )

    def test_self_dependencies_and_cycles_terminate(self):
        """Cycles remain visible while each node is queried once."""
        dependencies = {"A": ["A", "B"], "B": ["A", "B"]}
        graph, calls = self.build_fixture(dependencies, 5)
        self.assertEqual(graph.adjacency, dependencies)
        self.assertEqual(graph.depths, {"A": 0, "B": 1})
        self.assertEqual(graph.expanded, {"A", "B"})
        self.assertEqual(calls, ["A", "B"])

    def test_duplicate_targets_are_removed_in_original_order(self):
        """Deduplication preserves the first occurrence of each target."""
        dependencies = {
            "A": ["B", "B", "C", "B", "A", "C"],
            "B": ["D", "D"], "C": ["D", "D"], "D": [],
        }
        graph, calls = self.build_fixture(dependencies, 3)
        self.assertEqual(graph.adjacency, {
            "A": ["B", "C", "A"], "B": ["D"], "C": ["D"], "D": [],
        })
        self.assertEqual(calls, ["A", "B", "C", "D"])
        self.assertEqual(graph.depths, {"A": 0, "B": 1, "C": 1, "D": 2})

    def test_unreachable_nodes_are_not_included_or_requested(self):
        """Visit only vertices reachable from the selected root."""
        dependencies = {"A": ["B"], "B": [], "Z": ["A", "Q"]}
        graph, calls = self.build_fixture(dependencies, 5)
        self.assertEqual(graph.adjacency, {"A": ["B"], "B": []})
        self.assertEqual(graph.depths, {"A": 0, "B": 1})
        self.assertEqual(graph.expanded, {"A", "B"})
        self.assertEqual(calls, ["A", "B"])

    def test_chain_longer_than_recursion_limit_is_supported(self):
        """Traversal must not depend on Python's recursion stack."""
        last_index = sys.getrecursionlimit() + 100
        calls = []

        def dependency_names(name):
            """Generate a chain longer than Python's recursion limit."""
            calls.append(name)
            index = int(name)
            return [str(index + 1)] if index < last_index else []

        graph = build_graph("0", dependency_names, last_index + 1)
        self.assertEqual(len(graph.adjacency), last_index + 1)
        self.assertEqual(len(graph.expanded), last_index + 1)
        self.assertEqual(len(calls), last_index + 1)
        self.assertEqual(graph.depths[str(last_index)], last_index)
        self.assertEqual(graph.adjacency[str(last_index)], [])
        self.assertEqual(calls, [str(i) for i in range(last_index + 1)])

    def test_dependency_error_propagates_without_being_replaced(self):
        """Fetching errors retain their original exception instance."""
        calls = []
        failure = RuntimeError("Cannot load B")

        def dependency_names(name):
            """Fail while loading the first transitive child."""
            calls.append(name)
            if name == "B":
                raise failure
            return ["B"]

        with self.assertRaises(RuntimeError) as raised:
            build_graph("A", dependency_names, 3)
        self.assertIs(raised.exception, failure)
        self.assertEqual(calls, ["A", "B"])

    def test_formatter_shows_depths_and_shared_edges(self):
        """Formatted diamonds show both edges and the depth boundary."""
        dependencies = {
            "A": ["B", "C"], "B": ["D"], "C": ["D"], "D": [],
        }
        graph, _ = self.build_fixture(dependencies, 2)
        self.assertEqual(format_graph(graph), (
            "Граф зависимостей A (максимальная глубина: 2):\n"
            "  A [глубина=0]: B, C\n"
            "  B [глубина=1]: D\n"
            "  C [глубина=1]: D\n"
            "  D [глубина=2]: (предел глубины)"
        ))

    def test_formatter_shows_cycles_as_normal_edges(self):
        """Cycle edges use the same representation as other edges."""
        graph, _ = self.build_fixture({"A": ["B"], "B": ["A"]}, 4)
        self.assertEqual(format_graph(graph), (
            "Граф зависимостей A (максимальная глубина: 4):\n"
            "  A [глубина=0]: B\n"
            "  B [глубина=1]: A"
        ))

    def test_formatter_marks_the_root_at_zero_depth(self):
        """The zero-depth root is a boundary even if it has no children."""
        graph, _ = self.build_fixture({"A": []}, 0)
        self.assertEqual(format_graph(graph), (
            "Граф зависимостей A (максимальная глубина: 0):\n"
            "  A [глубина=0]: (предел глубины)"
        ))


if __name__ == "__main__":
    unittest.main()
