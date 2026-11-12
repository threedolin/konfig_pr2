"""Render three examples and compare them with native Maven dependency trees."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.request import urlopen

from src.graph import build_graph, format_graph
from src.maven import MavenRepository
from src.visualization import find_renderer, render_graph


MAX_DEPTH = 3
CENTRAL = "https://repo.maven.apache.org/maven2"
PLUGIN_VERSION = "3.8.1"
PLUGIN = ("org.apache.maven.plugins:maven-dependency-plugin:"
          f"{PLUGIN_VERSION}:tree")
PACKAGES = (
    ("junit", "junit:junit:4.13.2"),
    ("hamcrest-library", "org.hamcrest:hamcrest-library:1.3"),
    ("slf4j-api", "org.slf4j:slf4j-api:2.0.17"),
)
FORMATS = (("text", ".maven-tree.txt"), ("dot", ".maven.dot"),
           ("json", ".maven.json"))
SETTINGS = """<settings><mirrors><mirror>
<id>central-only</id><mirrorOf>*</mirrorOf>
<url>https://repo.maven.apache.org/maven2</url>
</mirror></mirrors></settings>"""


def failure_log(message):
    """Keep failed comparison diagnostics after the working directory closes."""
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="konfig-pr2-error-",
        suffix=".log", delete=False,
    ) as handle:
        handle.write(message)
        return Path(handle.name)


def run_tool(command, log, timeout=180):
    """Execute comparison tooling and retain diagnostics outside the repo."""
    try:
        result = subprocess.run(
            [str(part) for part in command], check=True,
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError) as error:
        chunks = [getattr(error, name, "") or ""
                  for name in ("stdout", "stderr")]
        detail = "\n".join(part.decode("utf-8", errors="replace")
                           if isinstance(part, bytes) else part
                           for part in chunks)
        diagnostic = failure_log(str(error) + "\n" + detail)
        raise RuntimeError(
            f"ошибка внешнего инструмента; см. {diagnostic}"
        ) from error
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    return result.stdout.strip() or result.stderr.strip()


def tool_versions(maven, work):
    """Record actual Maven, D2 and dependency plugin versions."""
    version = run_tool([maven, "--version"], work / "maven-version.log", 60)
    version = re.sub(r"\x1b\[[0-9;]*m", "", version).splitlines()[0]
    d2_version = run_tool(
        [find_renderer(), "--version"], work / "d2-version.log", 60
    )
    versions = {"maven": version, "d2": d2_version,
                "maven_dependency_plugin": PLUGIN_VERSION}
    dot = shutil.which("dot")
    if dot:
        versions["graphviz"] = run_tool([dot, "-V"], work / "dot-version.log")
    return versions


def download_pom(coordinates, directory):
    """Fetch the unchanged published POM for the native project comparison."""
    group, artifact, version = coordinates.split(":")
    relative = (f"{group.replace('.', '/')}/{artifact}/{version}/"
                f"{artifact}-{version}.pom")
    url = f"{CENTRAL}/{relative}"
    with urlopen(url, timeout=60) as response:
        data = response.read()
    directory.mkdir()
    pom = directory / "pom.xml"
    pom.write_bytes(data)
    return pom, url, hashlib.sha256(data).hexdigest()


def export_maven(maven, settings, pom, output, label):
    """Export text, DOT and JSON using the pinned native dependency plugin."""
    files = {}
    for output_type, suffix in FORMATS:
        target = output / (label + suffix)
        command = [
            maven, "-B", "-ntp", "-Dstyle.color=never", "-s", settings,
            "-f", pom, PLUGIN, "-Dverbose=true",
            f"-DoutputType={output_type}", f"-DoutputFile={target}",
            "-DappendOutput=false",
        ]
        run_tool(command, pom.parent / f"maven-{output_type}.log")
        if not target.is_file():
            raise RuntimeError(f"Maven не создал {target}")
        if output_type == "dot":
            lines = target.read_text(encoding="utf-8").splitlines()
            target.write_text("\n".join(line.rstrip() for line in lines) + "\n",
                              encoding="utf-8")
        files[output_type] = target.name
    dot = shutil.which("dot")
    if dot:
        image = output / f"{label}.maven.svg"
        run_tool([dot, "-Tsvg", output / files["dot"], "-o", image],
                 pom.parent / "graphviz.log")
        files["maven_svg"] = image.name
    return files


def gav(node):
    """Normalize one native JSON node to group, artifact and version."""
    return f"{node['groupId']}:{node['artifactId']}:{node['version']}"


def read_maven_graph(filename):
    """Merge verbose tree occurrences into a graph without recursive calls."""
    root = json.loads(filename.read_text(encoding="utf-8"))
    adjacency, pending = {}, [root]
    while pending:
        node = pending.pop()
        name = gav(node)
        adjacency.setdefault(name, [])
        for child in node.get("children", []) or []:
            target = gav(child)
            if target not in adjacency[name]:
                adjacency[name].append(target)
            adjacency.setdefault(target, [])
            pending.append(child)
    return build_graph(gav(root), adjacency.__getitem__, MAX_DEPTH)


def graph_sets(graph):
    """Count unique GAV vertices and directed edges rather than tree rows."""
    edges = {(parent, child) for parent, children in graph.adjacency.items()
             for child in children}
    return set(graph.adjacency), edges


def compare_graphs(application, native):
    """Record graph differences while keeping raw native output as evidence."""
    own_nodes, own_edges = graph_sets(application)
    native_nodes, native_edges = graph_sets(native)
    return {
        "application": {"nodes": len(own_nodes), "edges": len(own_edges)},
        "maven_json": {"nodes": len(native_nodes), "edges": len(native_edges)},
        "application_only_nodes": sorted(own_nodes - native_nodes),
        "maven_only_nodes": sorted(native_nodes - own_nodes),
        "application_only_edges": sorted(own_edges - native_edges),
        "maven_only_edges": sorted(native_edges - own_edges),
    }


def reproduce_example(maven, settings, work, output, specification):
    """Render one graph and compare it to Maven on the same original POM."""
    label, coordinates = specification
    repository = MavenRepository(CENTRAL)
    root = repository.canonical_name(coordinates)
    graph = build_graph(root, repository.dependency_names, MAX_DEPTH)
    graph_text = output / f"{label}.graph.txt"
    graph_text.write_text(format_graph(graph) + "\n", encoding="utf-8")
    d2, svg = render_graph(graph, output / f"{label}.svg")
    pom, url, digest = download_pom(coordinates, work / label)
    files = export_maven(maven, settings, pom, output, label)
    native = read_maven_graph(output / files["json"])
    if native.root != root:
        raise RuntimeError("Maven выбрал другой корневой пакет")
    result = compare_graphs(graph, native)
    result.update({
        "label": label, "coordinates": coordinates,
        "pom_url": url, "pom_sha256": digest, "max_depth": MAX_DEPTH,
        "files": {**files, "graph": graph_text.name,
                  "d2": d2.name, "svg": svg.name},
    })
    return result


def main():
    """Reproduce examples, invoking Maven only for the native comparison."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maven", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("examples"))
    options = parser.parse_args()
    maven = options.maven.expanduser().resolve()
    if not maven.is_file():
        parser.error("файл исполняемого Maven не найден")
    output = options.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="konfig-pr2-comparison-") as name:
        work = Path(name)
        settings = work / "settings.xml"
        settings.write_text(SETTINGS, encoding="utf-8")
        report = {"tools": tool_versions(maven, work), "max_depth": MAX_DEPTH,
                  "note": "Counts describe verbose JSON; see native text "
                          "for omitted duplicate/conflict annotations.",
                  "examples": []}
        for specification in PACKAGES:
            print(f"Comparing {specification[1]}", flush=True)
            report["examples"].append(reproduce_example(
                maven, settings, work, output, specification
            ))
    filename = output / "comparison.json"
    filename.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(filename)


if __name__ == "__main__":
    main()
