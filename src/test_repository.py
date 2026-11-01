"""Read direct neighbors from the small text repository used in examples."""

import re
from pathlib import Path

from .pom import RepositoryError


TEST_PACKAGE_PATTERN = re.compile(r"[A-Z]+")


def direct_dependencies(filename, package):
    """Read A: B C records and return only the requested package's neighbors."""
    try:
        content = Path(filename).expanduser().read_text(encoding="utf-8")
        lines = content.splitlines()
    except (OSError, UnicodeError) as error:
        raise RepositoryError(
            f"невозможно прочитать тестовый файл: {error}"
        ) from error
    repository = {}
    for number, line in enumerate(lines, 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name, separator, values = line.partition(":")
        name, dependencies = name.strip(), values.split()
        if not separator or not TEST_PACKAGE_PATTERN.fullmatch(name):
            raise RepositoryError(f"неверный формат тестовой строки {number}")
        if any(not TEST_PACKAGE_PATTERN.fullmatch(item)
               for item in dependencies):
            raise RepositoryError(f"неверное имя в тестовой строке {number}")
        if name in repository:
            raise RepositoryError(f"повторное описание тестового пакета {name}")
        repository[name] = list(dict.fromkeys(dependencies))
    if package not in repository:
        raise RepositoryError(
            f"пакет {package} не найден в тестовом репозитории"
        )
    return package, repository[package]
