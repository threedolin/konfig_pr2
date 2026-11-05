"""Check repeated text repository lookups and complete graph validation."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.pom import RepositoryError
from src.test_repository import TestRepository, direct_dependencies


FIXTURES = Path(__file__).parent / "fixtures"


class TextRepositoryAdapterTests(unittest.TestCase):
    """Check loading and safe reuse of the text graph adapter."""

    def setUp(self):
        """Create a directory for temporary repository files."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.filename = Path(self.directory.name) / "repository.txt"

    def make_repository(self, content):
        """Write a repository and load the adapter."""
        self.filename.write_text(content, encoding="utf-8")
        return TestRepository(self.filename)

    def test_file_is_read_once(self):
        """Repeated requests use declarations already held in memory."""
        with patch(
            "src.test_repository.Path.read_text",
            return_value="A: B\nB:\n",
        ) as read:
            repository = TestRepository(self.filename)
            self.assertEqual(repository.canonical_name("A"), "A")
            self.assertEqual(repository.dependency_names("A"), ["B"])
            self.assertEqual(repository.dependency_names("B"), [])
            repository.dependency_names("A")
        read.assert_called_once_with(encoding="utf-8")

    def test_multiletter_names_and_diamond(self):
        """Keep uppercase multiletter names and both shared-node edges."""
        repository = TestRepository(FIXTURES / "text_diamond.txt")
        self.assertEqual(repository.canonical_name("ROOT"), "ROOT")
        self.assertEqual(
            repository.dependency_names("ROOT"), ["LEFT", "RIGHT"]
        )
        self.assertEqual(repository.dependency_names("LEFT"), ["SHARED"])
        self.assertEqual(repository.dependency_names("RIGHT"), ["SHARED"])
        self.assertEqual(repository.dependency_names("SHARED"), [])

    def test_comments_whitespace_and_duplicate_edges(self):
        """Skip comments and preserve the first occurrence of each edge."""
        repository = self.make_repository(
            "# comment\n\n ROOT : RIGHT LEFT RIGHT # duplicate\n"
            "LEFT:\nRIGHT:\n"
        )
        self.assertEqual(repository.dependency_names("ROOT"), ["RIGHT", "LEFT"])

    def test_dependency_list_is_a_copy(self):
        """Mutating a returned list must not change the repository graph."""
        repository = self.make_repository("A: B\nB:\n")
        dependencies = repository.dependency_names("A")
        dependencies.clear()
        self.assertEqual(repository.dependency_names("A"), ["B"])

    def test_missing_reference_is_rejected_during_loading(self):
        """Check dangling references even in another disconnected component."""
        with self.assertRaisesRegex(RepositoryError, "MISSING"):
            self.make_repository("ROOT:\nOTHER: MISSING\n")

    def test_cycles_and_self_loop_are_valid(self):
        """Allow forward references, cycles and self dependencies."""
        repository = TestRepository(FIXTURES / "text_cycle.txt")
        self.assertEqual(repository.dependency_names("A"), ["B"])
        self.assertEqual(repository.dependency_names("B"), ["C"])
        self.assertEqual(repository.dependency_names("C"), ["A"])
        self.assertEqual(repository.dependency_names("SELF"), ["SELF"])

    def test_missing_package_is_rejected(self):
        """Both adapter methods report a missing package consistently."""
        repository = self.make_repository("ROOT:\n")
        for method in (
            repository.canonical_name, repository.dependency_names,
        ):
            with self.subTest(method=method.__name__):
                with self.assertRaisesRegex(RepositoryError, "не найден"):
                    method("UNKNOWN")

    def test_missing_file_is_reported_as_repository_error(self):
        """Wrap missing-file errors in the repository error type."""
        with self.assertRaisesRegex(RepositoryError, "прочитать"):
            TestRepository(self.filename)

    def test_direct_dependencies_remains_direct(self):
        """The stage-two API does not traverse transitive dependencies."""
        self.assertEqual(direct_dependencies(
            FIXTURES / "text_chain.txt", "A"
        ), ("A", ["B"]))

    def test_disconnected_components_and_leaf(self):
        """Read separate components and explicit leaves from one file."""
        repository = TestRepository(FIXTURES / "text_disconnected.txt")
        self.assertEqual(repository.dependency_names("MAIN"), ["LEAF"])
        self.assertEqual(repository.dependency_names("OTHER"), ["END"])
        self.assertEqual(repository.dependency_names("ISOLATED"), [])
        leaf = TestRepository(FIXTURES / "text_leaf.txt")
        self.assertEqual(leaf.dependency_names("LEAF"), [])


if __name__ == "__main__":
    unittest.main()
