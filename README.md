# Визуализатор зависимостей Maven — вариант 18

Практическая работа №2 по конфигурационному управлению. Реализован **только
этап 1**: минимальное CLI-приложение с настройками через аргументы командной
строки, проверкой входных данных и выводом параметров в формате `ключ = значение`.

Получение зависимостей, обход графа и генерация SVG не входят в этап 1.
Приложение пока не обращается к репозиторию по сети и не создаёт SVG-файл.

## Требования

- Python 3.8 или новее.
- Сторонние библиотеки не нужны.
- Для запуска в Linux/macOS доступна оболочка `sh`.

## Структура

```text
.
├── .gitignore
├── README.md
├── run.sh
├── src/
│   ├── __init__.py
│   └── cli.py
└── tests/
    ├── __init__.py
    ├── fixtures/repository.txt
    └── test_cli.py
```

## Параметры CLI

| Аргумент | Назначение | Значение по умолчанию |
| --- | --- | --- |
| `--package NAME` | Имя пакета | Обязателен |
| `--repository URL_OR_PATH` | URL Maven-репозитория или путь к тестовому файлу | Обязателен |
| `--test-mode {true,false}` | Использовать тестовый репозиторий | `false` |
| `--output FILE` | Имя SVG-файла будущего графа | `graph.svg` |
| `--max-depth N` | Максимальная глубина анализа зависимостей | `3` |

**Правила проверки:**

- В обычном режиме имя пакета должно иметь вид `groupId:artifactId`
  (например, `org.apache.commons:commons-lang3`), а репозиторий — быть
  корректным HTTP(S)-URL.
- В тестовом режиме имя пакета состоит из заглавных латинских букв (`A`,
  `ABC`), а репозиторий задаётся путём к существующему читаемому файлу.
- `--test-mode` принимает только `true` или `false`.
- Выходной файл должен иметь расширение `.svg`; его каталог должен
  существовать.
- Максимальная глубина — целое неотрицательное число. `0` означает
  анализ только выбранного пакета.

## Запуск

Сборка не требуется. Из корня проекта:

```sh
./run.sh \
  --package org.apache.commons:commons-lang3 \
  --repository https://repo.maven.apache.org/maven2 \
  --test-mode false \
  --output graph.svg \
  --max-depth 3
```

Ожидаемый результат:

```text
package = org.apache.commons:commons-lang3
repository = https://repo.maven.apache.org/maven2
test_mode = false
output = graph.svg
max_depth = 3
```

Запуск без `run.sh`:

```sh
python3 -m src.cli --package org.example:demo \
  --repository https://repo.maven.apache.org/maven2
```

Тестовый режим:

```sh
./run.sh --package A --repository tests/fixtures/repository.txt \
  --test-mode true --output graph.svg --max-depth 2
```

Справка по аргументам: `./run.sh --help`.

## Демонстрация обработки ошибок

Некорректные параметры приводят к сообщению в `stderr` и коду выхода `2`:

| Параметр | Пример ошибочного ввода | Причина |
| --- | --- | --- |
| `--package` | `--package invalid` | Для Maven нужны `groupId:artifactId` |
| `--repository` | `--repository ftp://example.com` | Нужен HTTP(S)-URL |
| `--test-mode` | `--test-mode maybe` | Допустимы `true` и `false` |
| `--output` | `--output graph.png` | Ожидается SVG-файл |
| `--max-depth` | `--max-depth -1` | Глубина неотрицательна |

Дополнительно проверяются отсутствующие обязательные аргументы, отсутствие
тестового файла и несуществующий каталог для выходного файла.

Пример ошибки:

```sh
./run.sh --package org.example:demo \
  --repository https://repo.maven.apache.org/maven2 \
  --max-depth -1
```

```text
error: argument --max-depth: глубина не может быть отрицательной
```

## Тестирование

```sh
python3 -m unittest discover -s tests -v
```

Тесты проверяют корректные сценарии и обработку ошибок для всех пяти
параметров. Для работы тестов интернет не требуется.
