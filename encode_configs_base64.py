"""
Утилита кодирует JSON-конфиги в base64 для env-переменных BENCH_*.

Пути задаются глобальными переменными ниже.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict

# Редактируй пути здесь:
CELERY_JSON_PATH: Path = Path("configs/celery.example.json")
CONNECTIONS_JSON_PATH: Path = Path("configs/connections.example.json")
RULE_BANKS_JSON_PATH: Path = Path("configs/rule_banks.clickhouse_baseline.json")
BENCHMARKS_JSON_PATH: Path = Path("configs/benchmarks.example.json")


def _resolve_path(raw_path: Path) -> Path:
    if raw_path.is_absolute():
        return raw_path
    return (Path.cwd() / raw_path).resolve()


def _read_json_file(path: Path) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise ValueError(f"Файл не найден: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Некорректный JSON в файле {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"JSON в {path} должен быть объектом")
    return data


def _json_to_base64(data: Dict[str, Any]) -> str:
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(encoded).decode("ascii")


def main() -> None:
    celery_data = _read_json_file(_resolve_path(CELERY_JSON_PATH))
    connections_data = _read_json_file(_resolve_path(CONNECTIONS_JSON_PATH))
    rule_banks_data = _read_json_file(_resolve_path(RULE_BANKS_JSON_PATH))
    benchmarks_data = _read_json_file(_resolve_path(BENCHMARKS_JSON_PATH))

    print("BENCH_CELERY_CONFIG_B64='" + _json_to_base64(celery_data) + "'")
    print("BENCH_CONNECTIONS_CONFIG_B64='" + _json_to_base64(connections_data) + "'")
    print("BENCH_RULE_BANKS_CONFIG_B64='" + _json_to_base64(rule_banks_data) + "'")
    print("BENCH_BENCHMARKS_CONFIG_B64='" + _json_to_base64(benchmarks_data) + "'")


if __name__ == "__main__":
    main()
