"""Test stage-four reverse dependency queries through the command line."""

import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from src.cli import main


FIXTURES = Path(__file__).parent / "fixtures"


class ReverseCliTests(unittest.TestCase):
    """Check full-repository consumers, bounded scopes and mode errors."""

    def arguments(self, package="CORE", depth=3, fixture="text_reverse.txt"):
        """Create valid test-mode reverse lookup arguments."""
        return [
            "--package", package, "--repository", str(FIXTURES / fixture),
            "--test-mode", "true", "--max-depth", str(depth), "--reverse",
        ]

    def invoke(self, arguments):
        """Capture CLI diagnostics and argparse exit statuses."""
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with contextlib.redirect_stderr(stderr):
                try:
                    status = main(arguments)
                except SystemExit as error:
                    status = error.code
        return status, stdout.getvalue(), stderr.getvalue()

    def test_complete_repository_consumers(self):
        """Find applications outside the target's outgoing dependency graph."""
        status, stdout, stderr = self.invoke(self.arguments())
        self.assertEqual((status, stderr), (0, ""))
        self.assertEqual(stdout.splitlines(), [
            "Обратные зависимости CORE (максимальная глубина: 3):",
            "Область поиска: весь тестовый репозиторий",
            "  CORE [глубина=0]: LIB, TOOL",
            "  LIB [глубина=1]: APP, CLI",
            "  TOOL [глубина=1]: APP",
            "  APP [глубина=2]: (нет)",
            "  CLI [глубина=2]: (нет)",
        ])
        self.assertNotIn("ISOLATED", stdout)

    def test_direct_consumers_at_depth_one(self):
        """Exclude transitive applications when only direct users are needed."""
        status, stdout, stderr = self.invoke(self.arguments(depth=1))
        self.assertEqual((status, stderr), (0, ""))
        self.assertIn("CORE [глубина=0]: LIB, TOOL", stdout)
        self.assertIn("LIB [глубина=1]: (предел глубины)", stdout)
        self.assertNotIn("APP", stdout)
        self.assertNotIn("CLI", stdout)

    def test_zero_depth(self):
        """A zero-depth reverse query displays only its target vertex."""
        status, stdout, stderr = self.invoke(self.arguments(depth=0))
        self.assertEqual((status, stderr), (0, ""))
        self.assertIn("CORE [глубина=0]: (предел глубины)", stdout)
        self.assertNotIn("LIB", stdout)

    def test_no_consumers(self):
        """Treat known isolated vertices and top-level consumers as leaves."""
        for package in ("ISOLATED", "APP"):
            with self.subTest(package=package):
                status, stdout, stderr = self.invoke(self.arguments(package))
                self.assertEqual((status, stderr), (0, ""))
                self.assertIn(f"{package} [глубина=0]: (нет)", stdout)

    def test_cycle_and_self_loop(self):
        """Keep reversed cycles and finish even with a large depth limit."""
        for package, lines in (
            ("A", ["A [глубина=0]: C", "C [глубина=1]: B",
                   "B [глубина=2]: A"]),
            ("SELF", ["SELF [глубина=0]: SELF"]),
        ):
            with self.subTest(package=package):
                status, stdout, stderr = self.invoke(self.arguments(
                    package, 100, "text_cycle.txt"
                ))
                self.assertEqual((status, stderr), (0, ""))
                for line in lines:
                    self.assertIn(line, stdout)

    def test_scoped_lookup_excludes_other_consumers(self):
        """A project scope must not include consumers from another project."""
        status, stdout, stderr = self.invoke(
            self.arguments() + ["--analysis-root", "APP"]
        )
        self.assertEqual((status, stderr), (0, ""))
        self.assertIn("граф APP, глубина 3; только найденные рёбра", stdout)
        self.assertIn("LIB [глубина=1]: APP", stdout)
        self.assertNotIn("CLI", stdout)

    def test_target_at_scope_boundary(self):
        """A target discovered at the forward depth limit remains queryable."""
        status, stdout, stderr = self.invoke(
            self.arguments("LIB", 1) + ["--analysis-root", "APP"]
        )
        self.assertEqual((status, stderr), (0, ""))
        self.assertIn("LIB [глубина=0]: APP", stdout)
        self.assertIn("APP [глубина=1]: (предел глубины)", stdout)

    def test_target_outside_scoped_graph(self):
        """A target beyond the source depth limit is not an empty result."""
        status, stdout, stderr = self.invoke(
            self.arguments(depth=1) + ["--analysis-root", "APP"]
        )
        self.assertEqual((status, stdout), (1, ""))
        self.assertIn("не найден в выбранной области поиска", stderr)

    def test_unknown_target(self):
        """Report an unknown test package with no partial reverse output."""
        status, stdout, stderr = self.invoke(self.arguments("UNKNOWN"))
        self.assertEqual((status, stdout), (1, ""))
        self.assertIn("не найден", stderr)

    def test_analysis_root_requires_reverse_mode(self):
        """Reject a scope option that cannot affect forward traversal."""
        arguments = self.arguments() + ["--analysis-root", "APP"]
        arguments.remove("--reverse")
        status, stdout, stderr = self.invoke(arguments)
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("только с --reverse", stderr)

    def test_invalid_analysis_root(self):
        """Apply normal package validation to the source graph root too."""
        status, stdout, stderr = self.invoke(
            self.arguments() + ["--analysis-root", "invalid"]
        )
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("A-Z", stderr)

    def test_maven_reverse_requires_scope_before_network_access(self):
        """An unspecified Maven consumer search must fail before HTTP work."""
        with patch("src.cli.MavenRepository") as repository:
            status, stdout, stderr = self.invoke([
                "--package", "g:lib:1", "--repository", "https://example.org",
                "--reverse",
            ])
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("нужен --analysis-root", stderr)
        repository.assert_not_called()


if __name__ == "__main__":
    unittest.main()
