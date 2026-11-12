"""Exercise Maven collection against an offline HTTP repository and POMs."""

import contextlib
import functools
import io
import subprocess
import sys
import threading
import unittest
from http.client import IncompleteRead
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from src.cli import main
from src.graph import build_graph
from src.maven import MavenRepository
from src.pom import (
    Dependency, RepositoryError, expand, make_model, parse_xml,
    resolve_dependency,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "maven"


def pom(body):
    """Wrap a short POM fragment in a project document for model tests."""
    return parse_xml(f"<project>{body}</project>", "fixture", "project")


class QuietHandler(SimpleHTTPRequestHandler):
    """Serve fixture files without printing HTTP logs to the test output."""

    def log_message(self, format_string, *args):
        """Suppress the standard request log."""


class HttpRepositoryTests(unittest.TestCase):
    """Verify HTTP paths, metadata, parent/BOM retrieval and CLI output."""

    @classmethod
    def setUpClass(cls):
        """Start an isolated repository on an available local TCP port."""
        handler = functools.partial(QuietHandler, directory=str(FIXTURES))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(
            target=cls.server.serve_forever, daemon=True
        )
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        """Release the server and wait for its worker thread to finish."""
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_metadata_parent_properties_and_bom(self):
        """Load only direct dependencies with inherited and managed versions."""
        repository = MavenRepository(self.url + "/")
        package, dependencies = repository.direct_dependencies(
            "org.example:demo"
        )
        self.assertEqual(package, "org.example:demo:2.0")
        self.assertEqual(dependencies, [
            Dependency("org.example", "test-helper", "4.0", "test"),
            Dependency("org.example", "lib", "3.2"),
            Dependency("org.example", "managed", "5.0"),
            Dependency("org.example", "optional", "2.0", "provided",
                       optional=True),
        ])
        self.assertEqual(set(repository.models), {
            ("org.example", "demo", "2.0"),
            ("org.example", "parent", "1.0"),
            ("org.example", "bom", "1.0"),
        })

    def test_explicit_version_without_metadata(self):
        """An explicit version works even when metadata is absent."""
        package, dependencies = MavenRepository(self.url).direct_dependencies(
            "org.example:empty:1.0"
        )
        self.assertEqual((package, dependencies), ("org.example:empty:1.0", []))

    def test_unknown_package(self):
        """Report the URL and HTTP status for a missing artifact."""
        with self.assertRaisesRegex(RepositoryError, "HTTP 404"):
            MavenRepository(self.url).direct_dependencies("missing:missing:1.0")

    def test_cli_process(self):
        """Run the entry point against HTTP without an external network."""
        result = subprocess.run(
            [sys.executable, "-m", "src.cli", "--package", "org.example:demo",
             "--repository", self.url, "--max-depth", "2", "--no-render"],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout.splitlines(), [
            "Граф зависимостей org.example:demo:2.0 "
            "(максимальная глубина: 2):",
            "  org.example:demo:2.0 [глубина=0]: "
            "org.example:test-helper:4.0, org.example:lib:3.2, "
            "org.example:managed:5.0, org.example:optional:2.0",
            "  org.example:test-helper:4.0 [глубина=1]: "
            "org.example:shared:1.0",
            "  org.example:lib:3.2 [глубина=1]: org.example:shared:1.0",
            "  org.example:managed:5.0 [глубина=1]: org.example:demo:2.0",
            "  org.example:optional:2.0 [глубина=1]: (нет)",
            "  org.example:shared:1.0 [глубина=2]: (предел глубины)",
        ])

    def test_graph_requests_only_vertices_within_expansion_depth(self):
        """Load a shared child once and keep a cycle back to the root."""
        repository = MavenRepository(self.url)
        root = repository.canonical_name("org.example:demo")
        with patch.object(
            repository, "direct_dependencies",
            wraps=repository.direct_dependencies,
        ) as fetch:
            graph = build_graph(root, repository.dependency_names, 3)
        self.assertEqual(fetch.call_count, 6)
        self.assertEqual(graph.depths["org.example:shared:1.0"], 2)
        self.assertEqual(graph.adjacency["org.example:managed:5.0"], [root])
        self.assertEqual(graph.adjacency["org.example:shared:1.0"], [])

    def test_zero_depth_loads_metadata_but_not_pom(self):
        """Version discovery works while no dependency POM is requested."""
        repository = MavenRepository(self.url)
        with patch.object(
            repository, "read_xml", wraps=repository.read_xml
        ) as read:
            root = repository.canonical_name("org.example:demo")
            graph = build_graph(root, repository.dependency_names, 0)
        self.assertEqual(read.call_count, 1)
        self.assertTrue(read.call_args[0][0].endswith("maven-metadata.xml"))
        self.assertEqual(graph.adjacency, {root: []})
        self.assertEqual(repository.models, {})

    def test_cli_download_failure(self):
        """Expose an operational error as exit code one with no traceback."""
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with contextlib.redirect_stderr(stderr):
                status = main([
                    "--package", "missing:missing:1.0",
                    "--repository", self.url, "--no-render",
                ])
        self.assertEqual((status, stdout.getvalue()), (1, ""))
        self.assertIn("HTTP 404", stderr.getvalue())

    def test_reverse_cli_process(self):
        """Find shared-package consumers inside a downloaded project graph."""
        result = subprocess.run(
            [sys.executable, "-m", "src.cli", "--reverse",
             "--package", "org.example:shared:1.0",
             "--analysis-root", "org.example:demo:2.0",
             "--repository", self.url, "--max-depth", "2", "--no-render"],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout.splitlines(), [
            "Обратные зависимости org.example:shared:1.0 "
            "(максимальная глубина: 2):",
            "Область поиска: граф org.example:demo:2.0, глубина 2; "
            "только найденные рёбра",
            "  org.example:shared:1.0 [глубина=0]: "
            "org.example:test-helper:4.0, org.example:lib:3.2",
            "  org.example:test-helper:4.0 [глубина=1]: org.example:demo:2.0",
            "  org.example:lib:3.2 [глубина=1]: org.example:demo:2.0",
            "  org.example:demo:2.0 [глубина=2]: (предел глубины)",
        ])

    def test_reverse_scoped_graph_excludes_unrequested_edges(self):
        """Do not infer incoming cycle edges from unexpanded boundary nodes."""
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with contextlib.redirect_stderr(stderr):
                status = main([
                    "--package", "org.example:demo:2.0", "--reverse",
                    "--analysis-root", "org.example:demo:2.0",
                    "--repository", self.url, "--max-depth", "1", "--no-render",
                ])
        self.assertEqual((status, stderr.getvalue()), (0, ""))
        self.assertIn("только найденные рёбра", stdout.getvalue())
        self.assertIn("demo:2.0 [глубина=0]: (нет)", stdout.getvalue())
        self.assertNotIn("managed:5.0", stdout.getvalue())

    def test_reverse_target_outside_downloaded_scope(self):
        """A valid fixed coordinate outside the selected graph is an error."""
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with contextlib.redirect_stderr(stderr):
                status = main([
                    "--package", "org.example:empty:1.0", "--reverse",
                    "--analysis-root", "org.example:demo:2.0",
                    "--repository", self.url, "--max-depth", "1", "--no-render",
                ])
        self.assertEqual((status, stdout.getvalue()), (1, ""))
        self.assertIn("не найден в выбранной области", stderr.getvalue())


class MavenModelTests(unittest.TestCase):
    """Check parsing edge cases and management without downloading artifacts."""

    def setUp(self):
        """Create an unconnected repository for mocked document reads."""
        self.repository = MavenRepository("https://example.invalid/maven")

    def select_version(self, body):
        """Select a version from an in-memory metadata document."""
        metadata = parse_xml(
            f"<metadata><versioning>{body}</versioning></metadata>",
            "fixture", "metadata",
        )
        with patch.object(self.repository, "read_xml", return_value=metadata):
            return self.repository.select_package("org.example:demo")[-1]

    def test_metadata_fallbacks(self):
        """Prefer release, then latest, then the last published version."""
        cases = (
            ("<release>1.9</release><latest>2.0-SNAPSHOT</latest>", "1.9"),
            ("<latest>2.0</latest>", "2.0"),
            ("<versions><version>1.9</version><version>1.10</version>"
             "</versions>", "1.10"),
        )
        for xml, expected in cases:
            with self.subTest(xml=xml):
                self.assertEqual(self.select_version(xml), expected)

    def test_missing_or_unsafe_metadata_version(self):
        """Reject missing versions and values that could escape a URL path."""
        for xml in ("", "<release>../../other</release>"):
            with self.subTest(xml=xml):
                with self.assertRaisesRegex(RepositoryError, "версия"):
                    self.select_version(xml)

    def test_network_errors_and_timeout(self):
        """Wrap connectivity errors and timeouts with repository context."""
        for error in (
            URLError("offline"), TimeoutError("timeout"), IncompleteRead(b"")
        ):
            with self.subTest(error=error):
                with patch("src.maven.urlopen", side_effect=error):
                    with self.assertRaisesRegex(RepositoryError, "загрузить"):
                        self.repository.read_xml("demo.pom", "project")

    def test_invalid_xml_response(self):
        """Reject invalid XML and a successful HTTP response containing HTML."""
        for data in (
            b"<project>", b"<html>Not a POM</html>",
            b'<?xml version="1.0" encoding="missing"?><project/>',
        ):
            with self.subTest(data=data):
                with patch("src.maven.urlopen", return_value=io.BytesIO(data)):
                    with self.assertRaises(RepositoryError):
                        self.repository.read_xml("demo.pom", "project")

    def test_parent_cycle(self):
        """Detect a parent pointing back to the POM being loaded."""
        root = pom("<parent><groupId>a</groupId><artifactId>b</artifactId>"
                   "<version>1</version></parent>")
        with patch.object(self.repository, "read_xml", return_value=root):
            with self.assertRaisesRegex(RepositoryError, "цикл"):
                self.repository.load_model(("a", "b", "1"))
        self.assertEqual(self.repository.loading, set())

    def test_bom_cycle(self):
        """Reject a BOM that imports its own management."""
        root = pom("<dependencyManagement><dependencies><dependency>"
                   "<groupId>a</groupId><artifactId>b</artifactId>"
                   "<version>1</version><type>pom</type><scope>import</scope>"
                   "</dependency></dependencies></dependencyManagement>")
        with patch.object(self.repository, "read_xml", return_value=root):
            with self.assertRaisesRegex(RepositoryError, "BOM"):
                self.repository.direct_dependencies("a:b:1")

    def test_model_cache(self):
        """Read a published POM only once per repository instance."""
        with patch.object(
            self.repository, "read_xml", return_value=pom("")
        ) as read:
            first = self.repository.load_model(("a", "b", "1"))
            second = self.repository.load_model(("a", "b", "1"))
        self.assertIs(first, second)
        self.assertEqual(read.call_count, 1)

    def test_properties(self):
        """Expand nested properties, including a repeated placeholder."""
        self.assertEqual(expand("${a}-${a}", {"a": "${b}", "b": "1"}), "1-1")

    def test_bad_properties(self):
        """Reject missing properties and cycles with a model error."""
        for properties in ({}, {"a": "${a}"}, {"a": "${b}", "b": "${a}"}):
            with self.subTest(properties=properties):
                with self.assertRaises(RepositoryError):
                    expand("${a}", properties)

    def test_inheritance_override(self):
        """A child overrides a dependency version without losing its scope."""
        body = ("<dependencies><dependency><groupId>g</groupId>"
                "<artifactId>a</artifactId><version>{}</version>{}"
                "</dependency></dependencies>")
        parent = make_model(
            pom(body.format("1", "<scope>test</scope>")), ("p", "p", "1")
        )
        child = make_model(pom(body.format("2", "")), ("g", "c", "1"), parent)
        self.assertEqual(len(child.dependencies), 1)
        self.assertEqual(resolve_dependency(
            child.dependencies[0], child.context, {}
        ), Dependency("g", "a", "2", "test"))

    def test_managed_defaults_and_classifier(self):
        """Use management for missing fields and keep classifier identities."""
        record = {"groupId": "g", "artifactId": "a", "classifier": "tests"}
        managed = {("g", "a", "jar", "tests"): {
            "version": "1", "scope": "test",
        }}
        dependency = resolve_dependency(record, {}, managed)
        self.assertEqual(
            str(dependency), "g:a:1 [scope=test, classifier=tests]"
        )

    def test_missing_version(self):
        """Report an unresolved required version as a model error."""
        with self.assertRaisesRegex(RepositoryError, "версия"):
            resolve_dependency({"groupId": "g", "artifactId": "a"}, {}, {})

    def test_management_is_not_a_direct_dependency(self):
        """Do not list dependencies declared only in dependencyManagement."""
        root = pom("<dependencyManagement><dependencies><dependency>"
                   "<groupId>g</groupId><artifactId>a</artifactId>"
                   "<version>1</version></dependency></dependencies>"
                   "</dependencyManagement>")
        with patch.object(self.repository, "read_xml", return_value=root):
            _, dependencies = self.repository.direct_dependencies("g:root:1")
        self.assertEqual(dependencies, [])


if __name__ == "__main__":
    unittest.main()
