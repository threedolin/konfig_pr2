"""Test direct dependency extraction from the small text repository format."""

import tempfile
import unittest
from pathlib import Path

from src.pom import RepositoryError
from src.test_repository import direct_dependencies


class TextRepositoryTests(unittest.TestCase):
    """Check text parsing, empty packages and clear input diagnostics."""

    def read(self, content, package="A"):
        """Read a temporary repository encoded as UTF-8."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "repository.txt"
            path.write_text(content, encoding="utf-8")
            return direct_dependencies(path, package)

    def test_direct_only_and_duplicates(self):
        """Keep declaration order, remove duplicates and do not traverse."""
        self.assertEqual(self.read("# example\nA: B B C\nB: D\nC:\nD:\n"),
                         ("A", ["B", "C"]))

    def test_empty_package(self):
        """An explicitly declared leaf has no dependencies."""
        self.assertEqual(self.read("A:\n"), ("A", []))

    def test_unknown_package(self):
        """Distinguish a missing package from an empty one."""
        with self.assertRaisesRegex(RepositoryError, "не найден"):
            self.read("B:\n")

    def test_bad_records(self):
        """Reject malformed names, missing separators and repeated records."""
        for content in ("A B", "a: B", "A: b", "A:\nA: B"):
            with self.subTest(content=content):
                with self.assertRaises(RepositoryError):
                    self.read(content)

    def test_invalid_encoding(self):
        """Report undecodable files as repository errors."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "repository.txt"
            path.write_bytes(b"\xff")
            with self.assertRaisesRegex(RepositoryError, "прочитать"):
                direct_dependencies(path, "A")


if __name__ == "__main__":
    unittest.main()
