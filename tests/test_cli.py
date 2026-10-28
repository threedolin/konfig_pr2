"""Tests of user settings and validation errors in stage one."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from src.cli import main


FIXTURE = Path(__file__).parent / "fixtures" / "repository.txt"
REAL_REPOSITORY = "https://repo.maven.apache.org/maven2"


class CliTests(unittest.TestCase):
    """Check successful invocation and failures of every CLI parameter."""

    def setUp(self):
        """Provide a valid set of arguments for a Maven repository."""
        self.args = [
            "--package", "org.example:demo",
            "--repository", REAL_REPOSITORY,
            "--test-mode", "false",
            "--output", "graph.svg",
            "--max-depth", "3",
        ]

    def invoke(self, args):
        """Capture the CLI output and exit status without a child process."""
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with contextlib.redirect_stderr(stderr):
                try:
                    status = main(args)
                except SystemExit as error:
                    status = error.code
        return status, stdout.getvalue(), stderr.getvalue()

    def replace_value(self, name, value):
        """Return valid arguments with one user-supplied value replaced."""
        args = self.args.copy()
        args[args.index(name) + 1] = value
        return args

    def assert_invalid(self, args, message):
        """Require a command-line error with a useful explanation."""
        status, stdout, stderr = self.invoke(args)
        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn(message, stderr)

    def test_real_repository_outputs_every_setting(self):
        """Print all five parameters in key-value format."""
        status, stdout, stderr = self.invoke(self.args)
        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.splitlines(), [
            "package = org.example:demo",
            f"repository = {REAL_REPOSITORY}",
            "test_mode = false",
            "output = graph.svg",
            "max_depth = 3",
        ])

    def test_test_repository_outputs_every_setting(self):
        """Accept uppercase test packages and an existing test file."""
        args = self.replace_value("--package", "A")
        args[args.index("--repository") + 1] = str(FIXTURE)
        args[args.index("--test-mode") + 1] = "true"
        status, stdout, stderr = self.invoke(args)
        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertIn("package = A", stdout)
        self.assertIn("test_mode = true", stdout)

    def test_default_values(self):
        """Apply defaults for test mode, output file and maximum depth."""
        args = self.args[:4]
        status, stdout, stderr = self.invoke(args)
        self.assertEqual((status, stderr), (0, ""))
        self.assertIn("test_mode = false", stdout)
        self.assertIn("output = graph.svg", stdout)
        self.assertIn("max_depth = 3", stdout)

    def test_missing_package(self):
        """Reject a missing required package name."""
        self.assert_invalid(self.args[2:], "--package")

    def test_blank_package(self):
        """Reject an empty Maven package name."""
        self.assert_invalid(
            self.replace_value("--package", ""), "groupId:artifactId"
        )

    def test_invalid_maven_package(self):
        """Reject malformed Maven coordinates and whitespace."""
        for package in ("demo", "org.example:", "a:b:c", "a b:c"):
            with self.subTest(package=package):
                self.assert_invalid(
                    self.replace_value("--package", package),
                    "groupId:artifactId",
                )

    def test_invalid_test_package(self):
        """Test packages must be uppercase Latin letters."""
        args = self.replace_value("--package", "abc")
        args[args.index("--test-mode") + 1] = "true"
        self.assert_invalid(args, "A-Z")

    def test_missing_repository(self):
        """Reject a missing repository source."""
        args = self.args.copy()
        index = args.index("--repository")
        del args[index:index + 2]
        self.assert_invalid(args, "--repository")

    def test_invalid_repository_url(self):
        """Reject unsupported schemes and invalid host/port syntax."""
        values = (
            "ftp://example.org/repo", "https://", "not-a-url",
            "https://example.org:bad/repo", "https://a b/repo",
            "https://user:password@example.org/repo",
        )
        for source in values:
            with self.subTest(source=source):
                self.assert_invalid(
                    self.replace_value("--repository", source),
                    "репозитория",
                )

    def test_missing_test_repository_file(self):
        """Require an existing file in test mode."""
        args = self.replace_value("--package", "A")
        args[args.index("--test-mode") + 1] = "true"
        args[args.index("--repository") + 1] = "missing.txt"
        self.assert_invalid(args, "не найден")

    def test_directory_cannot_be_test_repository(self):
        """Reject a directory instead of a test repository file."""
        args = self.replace_value("--package", "A")
        args[args.index("--test-mode") + 1] = "true"
        args[args.index("--repository") + 1] = str(FIXTURE.parent)
        self.assert_invalid(args, "не найден")

    def test_invalid_test_mode(self):
        """Only true and false are valid test-mode choices."""
        self.assert_invalid(
            self.replace_value("--test-mode", "maybe"),
            "invalid choice",
        )

    def test_invalid_output_extension(self):
        """Reject an output file with the wrong extension."""
        for filename in ("graph.png", "graph", ".svg", ""):
            with self.subTest(filename=filename):
                self.assert_invalid(
                    self.replace_value("--output", filename), ".svg"
                )

    def test_invalid_output_directory(self):
        """Reject an output target inside a nonexistent directory."""
        with tempfile.TemporaryDirectory() as directory:
            output = str(Path(directory) / "missing" / "graph.svg")
            self.assert_invalid(
                self.replace_value("--output", output), "не существует"
            )

    def test_negative_max_depth(self):
        """Reject negative dependency depth values."""
        self.assert_invalid(
            self.replace_value("--max-depth", "-1"), "отрицательной"
        )

    def test_noninteger_max_depth(self):
        """Reject non-integer dependency depth values."""
        for depth in ("2.5", "many"):
            with self.subTest(depth=depth):
                self.assert_invalid(
                    self.replace_value("--max-depth", depth), "целым"
                )

    def test_zero_max_depth(self):
        """Zero is a valid depth for analysis of the selected package."""
        status, stdout, stderr = self.invoke(
            self.replace_value("--max-depth", "0")
        )
        self.assertEqual((status, stderr), (0, ""))
        self.assertIn("max_depth = 0", stdout)

    def test_unknown_option(self):
        """Reject options not defined in the program interface."""
        self.assert_invalid(self.args + ["--unsupported"], "unrecognized")


if __name__ == "__main__":
    unittest.main()
