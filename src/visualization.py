"""Serialize dependency graphs as D2 and render SVG with the D2 executable."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from xml.etree import ElementTree

from .pom import RepositoryError


RENDER_TIMEOUT = 60
SVG_TAG = "{http://www.w3.org/2000/svg}svg"


def quote_label(value):
    """Quote D2 labels and keep dollar substitutions literal."""
    return json.dumps(value, ensure_ascii=False).replace("$", "\\$")


def node_order(graph):
    """Collect every vertex in stable order, including an isolated root."""
    names = [graph.root, *graph.depths, *graph.adjacency]
    for dependencies in graph.adjacency.values():
        names.extend(dependencies)
    return list(dict.fromkeys(names))


def node_lines(graph, package, identifier):
    """Style the root and distinguish unexpanded vertices from known leaves."""
    boundary = package not in graph.expanded
    label = package.replace(":", "\n")
    if boundary:
        label += "\n[предел глубины]"
    lines = [f"{identifier}: {quote_label(label)} {{", "  shape: rectangle"]
    lines.extend(["  style.border-radius: 8", "  style.font-size: 16"])
    if package == graph.root:
        lines.extend(["  style.fill: \"#DBEAFE\"",
                      "  style.stroke: \"#2563EB\"",
                      "  style.stroke-width: 3"])
    elif boundary:
        lines.append("  style.fill: \"#FEF3C7\"")
    else:
        lines.append("  style.fill: \"#F1F5F9\"")
    if boundary:
        lines.append("  style.stroke-dash: 5")
    return [*lines, "}"]


def format_d2(graph):
    """Represent the exact collected edges with stable IDs and quoted labels."""
    names = node_order(graph)
    identifiers = {name: f"n{index}" for index, name in enumerate(names)}
    direction = "Обратные зависимости" if graph.reverse else "Зависимости"
    title = f"{direction}: {graph.root}\nГлубина: {graph.max_depth}"
    if graph.scope:
        title += f"\nОбласть поиска: {graph.scope}"
    lines = ["direction: right", f"title: {quote_label(title)} {{",
             "  shape: text", "  near: top-center", "  style.font-size: 20",
             "}", ""]
    for package in names:
        lines.extend(node_lines(graph, package, identifiers[package]))
    lines.append("")
    for package, dependencies in graph.adjacency.items():
        for dependency in dict.fromkeys(dependencies):
            lines.append(f"{identifiers[package]} -> {identifiers[dependency]}")
    return "\n".join(lines) + "\n"


def find_renderer():
    """Find D2 on PATH or in the standard per-user installation directory."""
    executable = shutil.which("d2")
    if executable:
        return executable
    local = Path.home() / ".local" / "bin" / "d2"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    raise RepositoryError(
        "D2 не найден: установите d2 в PATH или ~/.local/bin; "
        "для текстового режима используйте --no-render"
    )


def run_renderer(executable, source, output):
    """Run D2 without a shell and turn failures into readable diagnostics."""
    try:
        subprocess.run(
            [executable, "--layout=dagre", "--theme=0", "--pad=32",
             "--salt=konfig-pr2", str(source), str(output)],
            check=True, capture_output=True, text=True, timeout=RENDER_TIMEOUT,
        )
    except subprocess.TimeoutExpired as error:
        raise RepositoryError("D2: превышен тайм-аут 60 секунд") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "ошибка рендеринга").strip()
        raise RepositoryError(f"D2: {detail}") from error
    except OSError as error:
        raise RepositoryError(f"не удалось запустить D2: {error}") from error


def validate_svg(filename):
    """Reject missing, empty, malformed or non-SVG renderer output."""
    try:
        root = ElementTree.parse(filename).getroot()
    except (OSError, ElementTree.ParseError) as error:
        raise RepositoryError(
            f"D2 не создал корректный SVG: {error}"
        ) from error
    if root.tag != SVG_TAG:
        raise RepositoryError("D2 создал документ без корневого элемента SVG")


def render_graph(graph, filename):
    """Save D2 and replace the SVG after successful, validated rendering."""
    try:
        output = Path(filename).resolve()
        source = output.with_suffix(".d2")
        if source.resolve() == output:
            raise RepositoryError("пути D2 и SVG не должны совпадать")
        source.write_text(format_d2(graph), encoding="utf-8")
        executable = find_renderer()
        with tempfile.TemporaryDirectory(
            prefix=".dependency-graph-", dir=output.parent
        ) as directory:
            temporary = Path(directory) / "graph.svg"
            run_renderer(executable, source, temporary)
            validate_svg(temporary)
            temporary.replace(output)
    except OSError as error:
        raise RepositoryError(
            f"невозможно сохранить диаграмму: {error}"
        ) from error
    return source, output
