"""Command-line interface for collecting direct Maven dependencies."""

import argparse
import sys
from pathlib import Path
from urllib.parse import urlsplit

from .maven import PACKAGE_PATTERN, MavenRepository
from .pom import RepositoryError
from .test_repository import TEST_PACKAGE_PATTERN
from .test_repository import direct_dependencies as test_dependencies


def non_negative_int(value):
    """Convert a string to a non-negative integer for argparse."""
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "глубина должна быть целым числом"
        ) from error
    if number < 0:
        raise argparse.ArgumentTypeError(
            "глубина не может быть отрицательной"
        )
    return number


def build_parser():
    """Create the parser for user-configurable application parameters."""
    parser = argparse.ArgumentParser(
        description="Сбор прямых зависимостей Maven (вариант 18, этап 2)."
    )
    parser.add_argument(
        "--package", required=True, metavar="NAME",
        help="groupId:artifactId[:version] или A в тестовом режиме",
    )
    parser.add_argument(
        "--repository", required=True, metavar="URL_OR_PATH",
        help="URL Maven-репозитория либо путь к тестовому файлу",
    )
    parser.add_argument(
        "--test-mode", choices=("true", "false"), default="false",
        help="использовать тестовый репозиторий (true/false)",
    )
    parser.add_argument(
        "--output", default="graph.svg", metavar="FILE",
        help="SVG-файл для этапа визуализации (по умолчанию graph.svg)",
    )
    parser.add_argument(
        "--max-depth", type=non_negative_int, default=3,
        metavar="N", help="максимальная глубина (по умолчанию 3)",
    )
    return parser


def validate_package(name, is_test_mode, parser):
    """Check the package name for the selected repository mode."""
    pattern = TEST_PACKAGE_PATTERN if is_test_mode else PACKAGE_PATTERN
    if pattern.fullmatch(name):
        return
    if is_test_mode:
        parser.error("в тестовом режиме имя пакета должно состоять из A-Z")
    parser.error(
        "имя Maven-пакета должно иметь вид groupId:artifactId[:version]"
    )


def valid_repository_url(source):
    """Check URL components and reject credentials, queries and fragments."""
    try:
        url = urlsplit(source)
        valid = (
            url.scheme in ("http", "https")
            and bool(url.hostname)
            and url.username is None
            and url.password is None
            and not url.query
            and not url.fragment
        )
        _ = url.port
    except ValueError:
        valid = False
    return valid


def validate_repository(source, is_test_mode, parser):
    """Check a readable test file or a syntactically valid HTTP(S) URL."""
    if is_test_mode:
        path = Path(source).expanduser()
        if not path.is_file():
            parser.error("файл тестового репозитория не найден")
        try:
            with path.open("r", encoding="utf-8"):
                pass
        except (OSError, UnicodeError) as error:
            parser.error(f"невозможно прочитать тестовый файл: {error}")
        return

    if any(char.isspace() for char in source):
        parser.error("URL репозитория не должен содержать пробелы")
    if not valid_repository_url(source):
        parser.error("требуется корректный URL репозитория HTTP(S)")


def validate_output(filename, parser):
    """Check the requested SVG filename and its destination folder."""
    path = Path(filename)
    if path.suffix.lower() != ".svg" or path.stem == "":
        parser.error("имя выходного файла должно оканчиваться на .svg")
    if not path.parent.is_dir():
        parser.error("каталог для выходного файла не существует")
    if path.is_dir():
        parser.error("выходной файл не может быть каталогом")


def main(argv=None):
    """Validate options, print direct dependencies and return an exit status."""
    parser = build_parser()
    options = parser.parse_args(argv)
    is_test_mode = options.test_mode == "true"
    validate_package(options.package, is_test_mode, parser)
    validate_repository(options.repository, is_test_mode, parser)
    validate_output(options.output, parser)

    try:
        if is_test_mode:
            package, dependencies = test_dependencies(
                options.repository, options.package
            )
        else:
            package, dependencies = MavenRepository(
                options.repository
            ).direct_dependencies(options.package)
    except RepositoryError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Прямые зависимости {package}:")
    if dependencies:
        for dependency in dependencies:
            print(f"  {dependency}")
    else:
        print("  (нет)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
