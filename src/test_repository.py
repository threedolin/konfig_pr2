"""Read and validate a text repository once for dependency graph traversal."""

import re
from pathlib import Path

from .pom import RepositoryError


TEST_PACKAGE_PATTERN = re.compile(r"[A-Z]+")


def _read_records(filename):
    """Read UTF-8 declarations and validate every referenced package."""
    try:
        content = Path(filename).expanduser().read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RepositoryError(
            f"невозможно прочитать тестовый файл: {error}"
        ) from error
    records = {}
    for number, line in enumerate(content.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if line:
            _add_record(records, line, number)
    _validate_references(records)
    return records


def _add_record(records, line, number):
    """Parse a single declaration and preserve first occurrence edge order."""
    name, separator, values = line.partition(":")
    name, dependencies = name.strip(), values.split()
    if not separator or not TEST_PACKAGE_PATTERN.fullmatch(name):
        raise RepositoryError(f"неверный формат тестовой строки {number}")
    if any(not TEST_PACKAGE_PATTERN.fullmatch(item)
           for item in dependencies):
        raise RepositoryError(f"неверное имя в тестовой строке {number}")
    if name in records:
        raise RepositoryError(f"повторное описание тестового пакета {name}")
    records[name] = list(dict.fromkeys(dependencies))


def _validate_references(records):
    """Require an explicit declaration for each referenced package."""
    for name, dependencies in records.items():
        for dependency in dependencies:
            if dependency not in records:
                raise RepositoryError(
                    f"пакет {dependency}, указанный в зависимостях "
                    f"пакета {name}, не найден в тестовом репозитории"
                )


class TestRepository:
    """Keep a validated text graph in memory for repeated direct lookups."""

    def __init__(self, filename):
        """Load the repository file exactly once before the BFS traversal."""
        self._records = _read_records(filename)

    def canonical_name(self, name):
        """Check that a test package exists and retain its uppercase name."""
        if name not in self._records:
            raise RepositoryError(
                f"пакет {name} не найден в тестовом репозитории"
            )
        return name

    def dependency_names(self, name):
        """Return a copy of the package's direct dependencies."""
        return list(self._records[self.canonical_name(name)])


def direct_dependencies(filename, package):
    """Preserve the direct-dependency API from stage two."""
    repository = TestRepository(filename)
    name = repository.canonical_name(package)
    return name, repository.dependency_names(name)
