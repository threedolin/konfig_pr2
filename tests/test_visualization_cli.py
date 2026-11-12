"""Check stage-five rendering defaults and text-only command-line behavior."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.cli import main
from src.pom import RepositoryError


FIXTURE = Path(__file__).parent / "fixtures" / "text_diamond.txt"


class VisualizationCliTests(unittest.TestCase):
    """Check normal, disabled and failed visualization from the CLI."""

    def invoke(self, output, extra=()):
        """Run a test graph in-process and capture its terminal output."""
        arguments = [
            "--package", "ROOT", "--repository", str(FIXTURE),
            "--test-mode", "true", "--output", str(output), *extra,
        ]
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with contextlib.redirect_stderr(stderr):
                status = main(arguments)
        return status, stdout.getvalue(), stderr.getvalue()

    def test_default_mode_renders_requested_svg(self):
        """Request visualization unless the user explicitly disables it."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "custom.svg"
            with patch("src.cli.render_graph") as renderer:
                status, stdout, stderr = self.invoke(output)
        self.assertEqual((status, stderr), (0, ""))
        self.assertIn("ROOT [глубина=0]: LEFT, RIGHT", stdout)
        graph, filename = renderer.call_args[0]
        self.assertEqual((graph.root, filename), ("ROOT", str(output)))

    def test_no_render_does_not_create_files(self):
        """Text-only mode neither invokes D2 nor creates diagram artifacts."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "custom.svg"
            with patch("src.cli.render_graph") as renderer:
                status, stdout, stderr = self.invoke(output, ["--no-render"])
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual((status, stderr), (0, ""))
        self.assertIn("ROOT", stdout)
        renderer.assert_not_called()

    def test_renderer_error_has_no_partial_stdout(self):
        """A rendering failure returns an operational error before output."""
        with tempfile.TemporaryDirectory() as directory:
            with patch("src.cli.render_graph",
                       side_effect=RepositoryError("D2 failed")):
                status, stdout, stderr = self.invoke(
                    Path(directory) / "graph.svg"
                )
        self.assertEqual((status, stdout), (1, ""))
        self.assertEqual(stderr, "error: D2 failed\n")


if __name__ == "__main__":
    unittest.main()
