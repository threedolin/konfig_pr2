"""Read the static dependency model of a Maven POM using standard XML tools."""

import re
from dataclasses import dataclass
from xml.etree import ElementTree


PROPERTY_PATTERN = re.compile(r"\$\{([^}]+)\}")
PROPERTY_LIMIT = 64
DEPENDENCY_FIELDS = (
    "groupId", "artifactId", "version", "scope", "type", "classifier",
    "optional",
)


class RepositoryError(Exception):
    """Describe a repository, XML or dependency-model error for the CLI."""


def parse_xml(data, source, expected_root):
    """Parse XML, remove namespace prefixes and validate the document kind."""
    try:
        root = ElementTree.fromstring(data)
    except (ElementTree.ParseError, LookupError, ValueError) as error:
        raise RepositoryError(
            f"некорректный XML в {source}: {error}"
        ) from error
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    if root.tag != expected_root:
        raise RepositoryError(f"в {source} ожидается XML {expected_root}")
    return root


def text(node, path, default=""):
    """Read a stripped XML value, falling back for absent or empty elements."""
    return (node.findtext(path) or default).strip()


def expand(value, properties):
    """Substitute nested Maven properties and reject missing or cyclic ones."""
    seen = set()
    for _ in range(PROPERTY_LIMIT):
        matches = PROPERTY_PATTERN.findall(value)
        if not matches:
            return value
        if value in seen:
            raise RepositoryError(f"цикл свойств Maven: {value}")
        seen.add(value)
        for name in matches:
            if name not in properties:
                raise RepositoryError(f"неизвестное свойство Maven: {name}")
        value = PROPERTY_PATTERN.sub(
            lambda match: properties[match.group(1)], value
        )
    raise RepositoryError("превышена глубина подстановки свойств Maven")


def declarations(root, path):
    """Read only dependencies at the specified POM path, excluding plugins."""
    return [
        {child.tag: (child.text or "").strip() for child in node
         if child.tag in DEPENDENCY_FIELDS}
        for node in root.findall(path)
    ]


def dependency_key(record):
    """Identify a dependency by Maven's group, artifact, type and classifier."""
    group, artifact = record.get("groupId"), record.get("artifactId")
    if not group or not artifact:
        raise RepositoryError(
            "зависимость должна содержать groupId и artifactId"
        )
    kind = record.get("type", "jar")
    return group, artifact, kind, record.get("classifier", "")


def merge_records(inherited, own, properties):
    """Merge declarations by identity, letting child fields override parents."""
    records = {}
    for record in (*inherited, *own):
        identity = {
            field: expand(value, properties) for field, value in record.items()
            if field in ("groupId", "artifactId", "type", "classifier")
        }
        key = dependency_key(identity)
        records.setdefault(key, {}).update(record)
    return list(records.values())


@dataclass
class PomModel:
    """Keep inherited raw declarations until the consuming POM is known."""

    package: tuple
    properties: dict
    context: dict
    dependencies: list
    managed: list


def coordinate_properties(package, prefixes):
    """Expose Maven coordinate aliases for the project or its parent."""
    return {prefix + field: value for prefix in prefixes
            for field, value in zip(
                ("groupId", "artifactId", "version"), package
            )}


def make_model(root, package, parent=None):
    """Combine inherited properties, management and direct declarations."""
    properties = dict(parent.properties) if parent else {}
    properties.update({node.tag: (node.text or "").strip()
                       for node in root.findall("properties/*")})
    context = dict(properties)
    context.update(coordinate_properties(package, ("project.", "pom.", "")))
    if parent:
        context.update(coordinate_properties(
            parent.package, ("project.parent.", "parent.")
        ))
    dependencies = merge_records(
        parent.dependencies if parent else [],
        declarations(root, "dependencies/dependency"), context,
    )
    managed = merge_records(
        parent.managed if parent else [],
        declarations(root, "dependencyManagement/dependencies/dependency"),
        context,
    )
    return PomModel(package, properties, context, dependencies, managed)


@dataclass(frozen=True)
class Dependency:
    """Represent one direct dependency, including non-runtime scopes."""

    group: str
    artifact: str
    version: str
    scope: str = "compile"
    kind: str = "jar"
    classifier: str = ""
    optional: bool = False

    def __str__(self):
        """Format coordinates and dependency attributes for terminal output."""
        attributes = [f"scope={self.scope}"]
        if self.kind != "jar":
            attributes.append(f"type={self.kind}")
        if self.classifier:
            attributes.append(f"classifier={self.classifier}")
        if self.optional:
            attributes.append("optional=true")
        coordinates = f"{self.group}:{self.artifact}:{self.version}"
        return f"{coordinates} [{', '.join(attributes)}]"


def resolve_dependency(record, context, managed):
    """Apply management defaults and resolve a single declared dependency."""
    resolved = {name: expand(value, context)
                for name, value in record.items()}
    key = dependency_key(resolved)
    fields = {**managed.get(key, {}), **resolved}
    version = fields.get("version")
    if not version:
        raise RepositoryError(
            f"не указана версия зависимости {key[0]}:{key[1]}"
        )
    return Dependency(
        key[0], key[1], version, fields.get("scope", "compile"),
        key[2], key[3], fields.get("optional", "false") == "true",
    )
