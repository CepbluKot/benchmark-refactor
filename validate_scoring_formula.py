"""
CLI-утилита для проверки scoring.expression в benchmark-конфигах.

Сценарии:
  1) benchmarks-файл (`{"benchmarks": [...]}`);
  2) root-файл (`{"connections": ..., "benchmarks": ..., ...}`);
  3) project-файл (с ссылками на части конфига через loader).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from pydantic import ValidationError

from src.loader import load_config
from src.models import BenchmarkRootConfig, BenchmarksFileConfig
from src.scoring_validation import collect_scoring_formula_issues


def _read_json_object(path: Path) -> Dict[str, Any]:
    """Читает JSON-файл и гарантирует root-object."""
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


def _as_path(raw_path: str) -> Path:
    return Path(raw_path).expanduser().resolve()


def _load_benchmarks_from_file(path: Path, config_type: str):
    """Загружает benchmarks из выбранного типа входного конфига."""
    if config_type == "project":
        root = load_config(path)
        return root.benchmarks

    raw = _read_json_object(path)
    if config_type == "benchmarks":
        try:
            parsed = BenchmarksFileConfig.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"Ошибки в benchmarks-конфиге:\n{exc}") from exc
        return parsed.benchmarks

    try:
        parsed_root = BenchmarkRootConfig.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"Ошибки в root-конфиге:\n{exc}") from exc
    return parsed_root.benchmarks


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Проверка scoring.expression в benchmark-конфигах."
    )
    parser.add_argument(
        "--path",
        required=True,
        help="Путь к JSON-файлу конфига.",
    )
    parser.add_argument(
        "--type",
        choices=["benchmarks", "root", "project"],
        default="benchmarks",
        help="Тип файла: benchmarks (по умолчанию), root или project.",
    )
    parser.add_argument(
        "--benchmark-id",
        action="append",
        dest="benchmark_ids",
        default=None,
        help="Ограничить проверку указанными benchmark_id (можно задать несколько раз).",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        path = _as_path(args.path)
        benchmarks = _load_benchmarks_from_file(path=path, config_type=args.type)
        issues = collect_scoring_formula_issues(
            benchmarks=benchmarks,
            benchmark_ids=args.benchmark_ids,
        )
        if issues:
            print(
                "WARNING: найдены ошибки scoring.expression. Конфиг невалиден.",
                file=sys.stderr,
            )
            for issue in issues:
                print(f"- {issue}", file=sys.stderr)
            return 1

        checked = len(args.benchmark_ids) if args.benchmark_ids else len(benchmarks)
        print(f"OK: scoring.expression валиден (benchmarks={checked})")
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
