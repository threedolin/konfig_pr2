"""Validate the checked-in diagrams and evidence from the native comparison."""

import json
import re
import unittest
from pathlib import Path
from xml.etree import ElementTree

from scripts.reproduce_examples import graph_sets, read_maven_graph


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class ExampleTests(unittest.TestCase):
    """Keep rendered samples and counts consistent without downloading data."""

    def setUp(self):
        """Read the actual recorded comparison manifest."""
        self.report = json.loads(
            (EXAMPLES / "comparison.json").read_text(encoding="utf-8")
        )

    def test_three_d2_graphs_match_recorded_counts(self):
        """Match D2 vertex and edge declarations to the application counts."""
        self.assertEqual(len(self.report["examples"]), 3)
        for example in self.report["examples"]:
            with self.subTest(package=example["coordinates"]):
                source = (EXAMPLES / example["files"]["d2"]).read_text()
                nodes = re.findall(r"^n\d+: ", source, flags=re.MULTILINE)
                edges = re.findall(r"^n\d+ -> n\d+$", source, re.MULTILINE)
                self.assertEqual(len(nodes), example["application"]["nodes"])
                self.assertEqual(len(edges), example["application"]["edges"])

    def test_all_recorded_images_are_valid_svg(self):
        """Keep both application and native Graphviz images viewable."""
        for example in self.report["examples"]:
            for name in ("svg", "maven_svg"):
                if name not in example["files"]:
                    continue
                with self.subTest(package=example["label"], image=name):
                    root = ElementTree.parse(
                        EXAMPLES / example["files"][name]
                    ).getroot()
                    self.assertEqual(root.tag,
                                     "{http://www.w3.org/2000/svg}svg")

    def test_native_json_matches_recorded_counts(self):
        """Count unique coordinates and edges rather than repeated tree rows."""
        for example in self.report["examples"]:
            with self.subTest(package=example["coordinates"]):
                graph = read_maven_graph(EXAMPLES / example["files"]["json"])
                nodes, edges = graph_sets(graph)
                self.assertEqual(graph.root, example["coordinates"])
                self.assertEqual(len(nodes), example["maven_json"]["nodes"])
                self.assertEqual(len(edges), example["maven_json"]["edges"])

    def test_observed_scope_difference_is_retained(self):
        """Preserve the observed difference in the SLF4J comparison."""
        examples = {item["label"]: item for item in self.report["examples"]}
        self.assertEqual(examples["junit"]["application_only_nodes"], [])
        self.assertEqual(examples["hamcrest-library"]["maven_only_edges"], [])
        self.assertEqual(examples["slf4j-api"]["application_only_nodes"], [
            "org.hamcrest:hamcrest-library:1.3",
        ])
        self.assertEqual(examples["slf4j-api"]["maven_json"], {
            "nodes": 3, "edges": 2,
        })


if __name__ == "__main__":
    unittest.main()
