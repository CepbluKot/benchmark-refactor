"""
CLI-утилита валидации JSON-конфигов бенчмарка по пути.

Поддерживает 3 режима:
  1) `single`  — валидация одного файла заданного типа;
  2) `parts`   — валидация 4 секций (celery/connections/rule_banks/benchmarks)
                 + сборка полного root-конфига с проверкой ссылок;
  3) `project` — валидация project-файла и всех его ссылок через loader.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from pydantic import ValidationError

from loader import load_config, parse_config_parts
from models import (
    BenchmarkProjectConfig,
    BenchmarkRootConfig,
    BenchmarksFileConfig,
    CeleryConfig,
    ConnectionsFileConfig,
    RuleBanksFileConfig,
)

SINGLE_CONFIG_MODELS = {
    "celery": CeleryConfig,
    "connections": ConnectionsFileConfig,
    "rule_banks": RuleBanksFileConfig,
    "benchmarks": BenchmarksFileConfig,
    "project": BenchmarkProjectConfig,
    "root": BenchmarkRootConfig,
}


def _read_json_object(path: Path) -> Dict[str, Any]:
    """Читает JSON-файл и гарантирует корневой объект (`dict`)."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise ValueError(f"Файл не найден: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Некорректный JSON в файле {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"JSON в файле {path} должен быть объектом")
    return payload


def validate_single_config(config_type: str, path: Path) -> Any:
    """
    Валидирует один JSON-файл строго по выбранному типу.

    Доступные типы:
      - celery
      - connections
      - rule_banks
      - benchmarks
      - project
      - root
    """
    model_cls = SINGLE_CONFIG_MODELS[config_type]
    raw = _read_json_object(path)
    try:
        return model_cls.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(
            f"Ошибка валидации {config_type}-конфига в {path}:\n{exc}"
        ) from exc


def validate_project_config(path: Path) -> BenchmarkRootConfig:
    """Валидирует project-файл и собирает полный root-конфиг."""
    return load_config(path)


def validate_parts_configs(
    celery_path: Path,
    connections_path: Path,
    rule_banks_path: Path,
    benchmarks_path: Path,
) -> BenchmarkRootConfig:
    """Валидирует 4 отдельных JSON-секции и их кросс-ссылки."""
    return parse_config_parts(
        celery_raw=_read_json_object(celery_path),
        connections_raw=_read_json_object(connections_path),
        rule_banks_raw=_read_json_object(rule_banks_path),
        benchmarks_raw=_read_json_object(benchmarks_path),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Валидация JSON-конфигов DDL benchmark по пути."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    single = subparsers.add_parser(
        "single",
        help="Валидировать один JSON-файл заданного типа.",
    )
    single.add_argument(
        "--type",
        required=True,
        choices=sorted(SINGLE_CONFIG_MODELS.keys()),
        help="Тип проверяемого JSON.",
    )
    single.add_argument(
        "--path",
        required=True,
        help="Путь к JSON-файлу.",
    )

    parts = subparsers.add_parser(
        "parts",
        help=(
            "Валидировать 4 отдельных JSON-секции "
            "(celery/connections/rule_banks/benchmarks)."
        ),
    )
    parts.add_argument("--celery-path", required=True, help="Путь к celery JSON.")
    parts.add_argument(
        "--connections-path",
        required=True,
        help="Путь к connections JSON.",
    )
    parts.add_argument(
        "--rule-banks-path",
        required=True,
        help="Путь к rule_banks JSON.",
    )
    parts.add_argument(
        "--benchmarks-path",
        required=True,
        help="Путь к benchmarks JSON.",
    )

    project = subparsers.add_parser(
        "project",
        help=(
            "Валидировать project JSON и связанные файлы "
            "(connections/rule_banks/benchmarks_file)."
        ),
    )
    project.add_argument("--path", required=True, help="Путь к project JSON.")

    return parser


def _as_path(raw_path: str) -> Path:
    return Path(raw_path).expanduser().resolve()


def _print_root_summary(config: BenchmarkRootConfig) -> None:
    print(
        "OK: root config валиден "
        f"(connections={len(config.connections)}, "
        f"benchmarks={len(config.benchmarks)}, "
        f"rule_banks={len(config.rule_banks)}, "
        f"default_rule_banks={len(config.default_rule_banks)})"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "single":
            config_type = args.type
            path = _as_path(args.path)
            validated = validate_single_config(config_type=config_type, path=path)
            print(f"OK: {config_type}-конфиг валиден: {path}")
            if config_type == "connections":
                print(f"connections={len(validated.connections)}")
            elif config_type == "rule_banks":
                print(
                    f"rule_banks={len(validated.rule_banks)}, "
                    f"default_rule_banks={len(validated.default_rule_banks)}"
                )
            elif config_type == "benchmarks":
                print(f"benchmarks={len(validated.benchmarks)}")
            elif config_type == "project":
                source = (
                    "benchmarks_file"
                    if validated.benchmarks_file is not None
                    else "inline benchmarks"
                )
                print(
                    f"connections_file={validated.connections_file}, "
                    f"rule_banks_file={validated.rule_banks_file}, source={source}"
                )
            elif config_type == "root":
                _print_root_summary(validated)
            elif config_type == "celery":
                print(
                    f"workers={validated.workers}, "
                    f"threads_per_worker={validated.threads_per_worker}"
                )
            return 0

        if args.command == "parts":
            config = validate_parts_configs(
                celery_path=_as_path(args.celery_path),
                connections_path=_as_path(args.connections_path),
                rule_banks_path=_as_path(args.rule_banks_path),
                benchmarks_path=_as_path(args.benchmarks_path),
            )
            print("OK: все 4 секции валидны и успешно собраны в root config.")
            _print_root_summary(config)
            return 0

        if args.command == "project":
            config = validate_project_config(path=_as_path(args.path))
            print("OK: project-конфиг и связанные файлы валидны.")
            _print_root_summary(config)
            return 0

        parser.error(f"Неизвестная команда: {args.command}")
        return 2

    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
