"""Test D2 serialization and atomic SVG publication without network access."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from src.graph import build_graph
from src.pom import RepositoryError
from src.visualization import (
    find_renderer, format_d2, render_graph, run_renderer,
)


SVG = '<svg xmlns="http://www.w3.org/2000/svg"><text>OK</text></svg>'


class D2Tests(unittest.TestCase):
    """Verify node identities, exact edges, boundaries and quoted labels."""

    def test_diamond_is_deterministic(self):
        """Represent both incoming edges to a shared vertex exactly once."""
        adjacency = {"A": ["B", "C"], "B": ["D"], "C": ["D"], "D": []}
        graph = build_graph("A", adjacency.__getitem__, 3)
        source = format_d2(graph)
        self.assertEqual(source, format_d2(graph))
        edges = [line for line in source.splitlines() if " -> " in line]
        self.assertEqual(edges, [
            "n0 -> n1", "n0 -> n2", "n1 -> n3", "n2 -> n3",
        ])

    def test_leaf_and_boundary_are_distinct(self):
        """Only unknown boundary vertices receive a dashed depth-limit label."""
        adjacency = {"A": ["B", "C"], "B": [], "C": ["D"], "D": []}
        source = format_d2(build_graph("A", adjacency.__getitem__, 2))
        self.assertIn('n1: "B" {', source)
        self.assertIn('n3: "D\\n[предел глубины]" {', source)
        self.assertEqual(source.count("style.stroke-dash"), 1)

    def test_isolated_root_at_zero_depth(self):
        """Keep the root blue and visibly unexpanded when the limit is zero."""
        graph = build_graph("A", lambda name: [], 0)
        source = format_d2(graph)
        self.assertIn('n0: "A\\n[предел глубины]" {', source)
        self.assertIn('style.stroke: "#2563EB"', source)
        self.assertIn("style.stroke-dash: 5", source)
        self.assertNotIn(" -> ", source)

    def test_cycles_and_self_loops(self):
        """Keep closing edges and self loops in the generated D2 source."""
        adjacency = {"A": ["A", "B"], "B": ["A"]}
        source = format_d2(build_graph("A", adjacency.__getitem__, 10))
        for edge in ("n0 -> n0", "n0 -> n1", "n1 -> n0"):
            self.assertIn(edge, source)

    def test_labels_do_not_become_d2_identifiers(self):
        """Keep coordinates and substitutions in labels instead of node IDs."""
        root = 'group:artifact:1-${literal}"\\ Юникод'
        source = format_d2(build_graph(root, lambda name: [], 1))
        self.assertIn('n0: "group\\nartifact\\n1-\\${literal}', source)
        self.assertIn('\\"\\\\ Юникод', source)
        self.assertNotIn(root + " -> ", source)

    def test_reverse_scope_is_visible_in_diagram(self):
        """Put reverse direction and the scope into an actual diagram title."""
        graph = build_graph("A", lambda name: [], 1)
        graph.reverse, graph.scope = True, "только найденные рёбра"
        source = format_d2(graph)
        self.assertIn('title: "Обратные зависимости', source)
        self.assertIn("Область поиска: только найденные рёбра", source)
        self.assertIn("near: top-center", source)


class SvgPublicationTests(unittest.TestCase):
    """Preserve existing output until a validated renderer result is ready."""

    def setUp(self):
        """Provide an isolated destination with spaces and an existing SVG."""
        directory = tempfile.TemporaryDirectory(prefix="graph output ")
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name) / "-graph.svg"
        self.output.write_text("previous SVG", encoding="utf-8")
        self.graph = build_graph("A", lambda name: [], 1)
        renderer = patch("src.visualization.find_renderer", return_value="d2")
        renderer.start()
        self.addCleanup(renderer.stop)

    def write_svg(self, executable, source, output):
        """Stand in for a successful renderer that writes a complete SVG."""
        self.assertTrue(source.is_absolute())
        self.assertTrue(output.is_absolute())
        self.assertTrue(source.is_file())
        output.write_text(SVG, encoding="utf-8")

    def test_success_replaces_existing_svg(self):
        """Publish a valid SVG and retain the corresponding D2 source."""
        with patch("src.visualization.run_renderer",
                   side_effect=self.write_svg):
            source, output = render_graph(self.graph, self.output)
        self.assertEqual(output, self.output)
        self.assertEqual(output.read_text(), SVG)
        self.assertEqual(source.read_text(), format_d2(self.graph))
        self.assertEqual(set(output.parent.iterdir()), {source, output})

    def test_renderer_failure_preserves_old_svg(self):
        """Rendering errors must not overwrite a user's existing image."""
        with patch("src.visualization.run_renderer",
                   side_effect=RepositoryError("D2 failed")):
            with self.assertRaisesRegex(RepositoryError, "D2 failed"):
                render_graph(self.graph, self.output)
        self.assertEqual(self.output.read_text(), "previous SVG")
        self.assertTrue(self.output.with_suffix(".d2").is_file())
        self.assertFalse(list(self.output.parent.glob(".dependency-graph-*")))

    def test_missing_or_invalid_svg_preserves_old_image(self):
        """Do not trust a successful exit without validating the output SVG."""
        for content in (None, "", "<svg>", "<html/>"):
            with self.subTest(content=content):
                with patch("src.visualization.run_renderer") as renderer:
                    if content is not None:
                        renderer.side_effect = (
                            lambda executable, source, output:
                            output.write_text(content, encoding="utf-8")
                        )
                    with self.assertRaises(RepositoryError):
                        render_graph(self.graph, self.output)
                self.assertEqual(self.output.read_text(), "previous SVG")

    def test_source_write_error_is_reported(self):
        """Report filesystem errors without invoking an external renderer."""
        with patch("pathlib.Path.write_text",
                   side_effect=PermissionError("no")):
            with patch("src.visualization.run_renderer") as renderer:
                with self.assertRaisesRegex(RepositoryError, "сохранить"):
                    render_graph(self.graph, self.output)
        renderer.assert_not_called()

    def test_path_resolution_error_is_reported(self):
        """Keep filesystem resolution errors inside normal CLI diagnostics."""
        with patch("pathlib.Path.resolve", side_effect=PermissionError("no")):
            with self.assertRaisesRegex(RepositoryError, "сохранить"):
                render_graph(self.graph, self.output)


class RendererTests(unittest.TestCase):
    """Check executable lookup, argument handling and failure diagnostics."""

    def test_renderer_is_called_without_shell(self):
        """Pass paths as separate arguments even when they contain spaces."""
        with patch("src.visualization.subprocess.run") as run:
            run_renderer("/bin/d2", Path("/tmp/a b.d2"), Path("/tmp/a b.svg"))
        arguments, options = run.call_args
        self.assertEqual(arguments[0][-2:], ["/tmp/a b.d2", "/tmp/a b.svg"])
        self.assertNotIn("shell", options)
        self.assertTrue(options["check"])
        self.assertEqual(options["timeout"], 60)

    def test_failures_become_repository_errors(self):
        """Handle timeouts, nonzero exit status and failure to start D2."""
        failures = (
            subprocess.TimeoutExpired("d2", 60),
            subprocess.CalledProcessError(1, "d2", stderr="syntax error"),
            FileNotFoundError("missing executable"),
        )
        for failure in failures:
            with self.subTest(failure=failure):
                with patch("src.visualization.subprocess.run",
                           side_effect=failure):
                    with self.assertRaises(RepositoryError):
                        run_renderer("d2", Path("a.d2"), Path("a.svg"))

    def test_missing_renderer_explains_text_mode(self):
        """Explain installation and the available text-only mode."""
        with tempfile.TemporaryDirectory() as directory:
            with patch("src.visualization.shutil.which", return_value=None):
                with patch("pathlib.Path.home", return_value=Path(directory)):
                    with self.assertRaisesRegex(RepositoryError, "--no-render"):
                        find_renderer()

    def test_real_d2_smoke(self):
        """Compile cycles and special labels using D2 when it is installed."""
        try:
            find_renderer()
        except RepositoryError:
            self.skipTest("D2 is not installed")
        root = 'group:artifact:1-${literal}"\\ Юникод'
        adjacency = {root: [root, "LEAF"], "LEAF": []}
        graph = build_graph(root, adjacency.__getitem__, 2)
        with tempfile.TemporaryDirectory() as directory:
            _, output = render_graph(graph, Path(directory) / "graph.svg")
            svg = ElementTree.parse(output).getroot()
        self.assertEqual(svg.tag, "{http://www.w3.org/2000/svg}svg")
        self.assertTrue(any(node.tag.endswith("}text") for node in svg.iter()))
        self.assertIn("${literal}", "".join(svg.itertext()))


if __name__ == "__main__":
    unittest.main()
