"""Fetch Maven metadata and POMs over HTTP without a package manager."""

import re
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

from .pom import (
    RepositoryError, dependency_key, expand, make_model, parse_xml,
    resolve_dependency, text,
)


COMPONENT = r"[A-Za-z0-9_][A-Za-z0-9_.-]*"
GROUP = r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*"
PACKAGE_PATTERN = re.compile(rf"{GROUP}:{COMPONENT}(?::{COMPONENT})?")
VERSION_PATTERN = re.compile(COMPONENT)
REQUEST_TIMEOUT = 20
MAX_POM_DEPTH = 32
VERSIONED_COORDINATES = 3


class MavenRepository:
    """Read direct dependencies, caching parent POMs and imported BOM models."""

    def __init__(self, repository):
        """Store the repository root and initialize the per-run model cache."""
        self.repository = repository.rstrip("/")
        self.models = {}
        self.loading = set()

    def read_xml(self, path, expected_root):
        """Download one XML document with a timeout and contextual errors."""
        url = f"{self.repository}/{path}"
        try:
            with urlopen(url, timeout=REQUEST_TIMEOUT) as response:
                data = response.read()
        except HTTPError as error:
            raise RepositoryError(
                f"не удалось загрузить {url}: HTTP {error.code}"
            ) from error
        except (URLError, OSError, HTTPException, ValueError) as error:
            raise RepositoryError(
                f"не удалось загрузить {url}: {error}"
            ) from error
        return parse_xml(data, url, expected_root)

    def select_package(self, name):
        """Use an explicit version or discover release/latest from metadata."""
        if not PACKAGE_PATTERN.fullmatch(name):
            raise RepositoryError("ожидается groupId:artifactId[:version]")
        parts = name.split(":")
        if len(parts) == VERSIONED_COORDINATES:
            return tuple(parts)
        group, artifact = parts
        path = f"{group.replace('.', '/')}/{artifact}/maven-metadata.xml"
        root = self.read_xml(path, "metadata")
        version = text(root, "versioning/release")
        version = version or text(root, "versioning/latest")
        if not version:
            versions = root.findall("versioning/versions/version")
            version = (versions[-1].text or "").strip() if versions else ""
        if not VERSION_PATTERN.fullmatch(version):
            raise RepositoryError(f"не найдена корректная версия пакета {name}")
        return group, artifact, version

    def load_model(self, package):
        """Load a POM and its parents, guarding cycles and deep chains."""
        if package in self.models:
            return self.models[package]
        if package in self.loading:
            raise RepositoryError("цикл родительских POM")
        if len(self.loading) >= MAX_POM_DEPTH:
            raise RepositoryError("превышена глубина родительских POM")
        group, artifact, version = self.select_coordinates(package)
        path = "/".join((group.replace(".", "/"), artifact, version,
                         f"{artifact}-{version}.pom"))
        self.loading.add(package)
        try:
            root = self.read_xml(path, "project")
            parent = self.load_parent(root)
            model = make_model(root, package, parent)
            self.models[package] = model
            return model
        finally:
            self.loading.remove(package)

    def select_coordinates(self, package):
        """Validate and encode fixed coordinates before constructing a URL."""
        if (len(package) != VERSIONED_COORDINATES
                or not PACKAGE_PATTERN.fullmatch(":".join(package))):
            raise RepositoryError(f"некорректные координаты POM: {package}")
        return tuple(quote(part, safe="") for part in package)

    def load_parent(self, root):
        """Resolve a published parent POM from the same repository."""
        node = root.find("parent")
        if node is None:
            return None
        properties = {item.tag: (item.text or "").strip()
                      for item in root.findall("properties/*")}
        package = tuple(expand(text(node, field), properties)
                        for field in ("groupId", "artifactId", "version"))
        return self.load_model(package)

    def management(self, model, stack=()):
        """Resolve management and BOM imports without listing them as edges."""
        if model.package in stack or len(stack) >= MAX_POM_DEPTH:
            raise RepositoryError("цикл или превышена глубина импорта BOM")
        imported, explicit = {}, {}
        for record in model.managed:
            resolved = {field: expand(value, model.context)
                        for field, value in record.items()}
            key = dependency_key(resolved)
            if key[2] == "pom" and resolved.get("scope") == "import":
                version = resolved.get("version", "")
                bom = self.load_model((key[0], key[1], version))
                for item, fields in self.management(
                    bom, (*stack, model.package)
                ).items():
                    imported.setdefault(item, fields)
            else:
                explicit[key] = resolved
        return {**imported, **explicit}

    def direct_dependencies(self, name):
        """Return selected coordinates and all effective direct declarations."""
        package = self.select_package(name)
        model = self.load_model(package)
        managed = self.management(model)
        dependencies = [resolve_dependency(record, model.context, managed)
                        for record in model.dependencies]
        return ":".join(package), dependencies

    def canonical_name(self, name):
        """Resolve the root version without loading its dependency POM."""
        return ":".join(self.select_package(name))

    def dependency_names(self, name):
        """Adapt direct Maven declarations to versioned graph vertex names."""
        _, dependencies = self.direct_dependencies(name)
        return [f"{item.group}:{item.artifact}:{item.version}"
                for item in dependencies]
