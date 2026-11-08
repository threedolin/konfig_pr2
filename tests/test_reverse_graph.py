"""Test reverse dependency indexing and reuse of the iterative BFS."""

import copy
import unittest

from src.graph import build_graph, format_graph, reverse_adjacency


class ReverseGraphTests(unittest.TestCase):
    """Check reverse edges, complete scope, shortest paths and cycles."""

    def test_target_only_and_isolated_vertices(self):
        """Keep every vertex, including dependencies without their own row."""
        result = reverse_adjacency({"APP": ["LIB"], "ISOLATED": []})
        self.assertEqual(result, {
            "APP": [], "LIB": ["APP"], "ISOLATED": [],
        })

    def test_duplicate_edges_and_order(self):
        """Keep each consumer once, preserving source declaration order."""
        result = reverse_adjacency({
            "WORKER": ["LIB", "LIB"], "APP": ["LIB"], "LIB": [],
        })
        self.assertEqual(result["LIB"], ["WORKER", "APP"])

    def test_no_mutation_or_aliasing(self):
        """Changes to reverse edges must not change the source graph."""
        source = {"APP": ["LIB", "LIB"], "LIB": []}
        before = copy.deepcopy(source)
        result = reverse_adjacency(source)
        result["LIB"].append("OTHER")
        self.assertEqual(source, before)

    def test_self_edges_and_cycles(self):
        """Reverse edges without discarding self references or cycles."""
        source = {"A": ["A", "B"], "B": ["C"], "C": ["A"]}
        self.assertEqual(reverse_adjacency(source), {
            "A": ["A", "C"], "B": ["A"], "C": ["B"],
        })

    def test_consumers_outside_forward_closure(self):
        """Find consumers outside the target's outgoing dependency graph."""
        source = {
            "TARGET": ["RUNTIME"], "RUNTIME": [],
            "CONSUMER": ["TARGET"], "OUTER": ["CONSUMER"],
            "UNRELATED": ["OTHER"], "OTHER": [],
        }
        index = reverse_adjacency(source)
        graph = build_graph("TARGET", index.__getitem__, 2)
        self.assertEqual(graph.depths, {
            "TARGET": 0, "CONSUMER": 1, "OUTER": 2,
        })
        self.assertNotIn("RUNTIME", graph.depths)
        self.assertNotIn("UNRELATED", graph.depths)

    def test_diamond_and_depth_boundary(self):
        """Keep both converging edges without expanding the boundary twice."""
        source = {
            "TARGET": [], "LEFT": ["TARGET"], "RIGHT": ["TARGET"],
            "APP": ["LEFT", "RIGHT"], "OUTER": ["APP"],
        }
        index, calls = reverse_adjacency(source), []

        def consumers(package):
            """Record the requested vertex and return its direct consumers."""
            calls.append(package)
            return index[package]

        graph = build_graph("TARGET", consumers, 2)
        self.assertEqual(graph.depths, {
            "TARGET": 0, "LEFT": 1, "RIGHT": 1, "APP": 2,
        })
        self.assertEqual(graph.adjacency["LEFT"], ["APP"])
        self.assertEqual(graph.adjacency["RIGHT"], ["APP"])
        self.assertEqual(calls, ["TARGET", "LEFT", "RIGHT"])
        self.assertEqual(graph.expanded, {"TARGET", "LEFT", "RIGHT"})

    def test_shortest_reverse_distance(self):
        """A direct consumer must retain depth one despite an indirect path."""
        source = {
            "TARGET": [], "MIDDLE": ["TARGET"],
            "JUNCTION": ["MIDDLE", "TARGET"], "CONSUMER": ["JUNCTION"],
        }
        index = reverse_adjacency(source)
        graph = build_graph("TARGET", index.__getitem__, 2)
        self.assertEqual(graph.depths, {
            "TARGET": 0, "MIDDLE": 1, "JUNCTION": 1, "CONSUMER": 2,
        })
        self.assertEqual(graph.adjacency["MIDDLE"], ["JUNCTION"])

    def test_cycle_preserves_root_depth(self):
        """Keep cycle edges without scheduling the root a second time."""
        index = reverse_adjacency({
            "TARGET": ["PEER"], "PEER": ["TARGET"], "CONSUMER": ["TARGET"],
        })
        graph = build_graph("TARGET", index.__getitem__, 3)
        self.assertEqual(graph.depths, {
            "TARGET": 0, "PEER": 1, "CONSUMER": 1,
        })
        self.assertEqual(graph.adjacency["PEER"], ["TARGET"])
        self.assertEqual(graph.expanded, {"TARGET", "PEER", "CONSUMER"})

    def test_isolated_target(self):
        """A known package without consumers is a successful empty result."""
        index = reverse_adjacency({"TARGET": [], "UNRELATED": []})
        graph = build_graph("TARGET", index.__getitem__, 2)
        self.assertEqual(graph.depths, {"TARGET": 0})
        self.assertEqual(graph.adjacency["TARGET"], [])
        self.assertEqual(graph.expanded, {"TARGET"})

    def test_reverse_format_and_scope(self):
        """Display reverse direction and keep the search scope visible."""
        index = reverse_adjacency({"APP": ["LIB"], "LIB": []})
        graph = build_graph("LIB", index.__getitem__, 2)
        graph.reverse, graph.scope = True, "весь тестовый репозиторий"
        self.assertEqual(format_graph(graph), (
            "Обратные зависимости LIB (максимальная глубина: 2):\n"
            "Область поиска: весь тестовый репозиторий\n"
            "  LIB [глубина=0]: APP\n"
            "  APP [глубина=1]: (нет)"
        ))


if __name__ == "__main__":
    unittest.main()
