"""
Runtime-настройки запуска бенчмарка через переменные окружения.

JSON-конфиги передаются как base64-строки:
  - BENCH_CELERY_CONFIG_B64
  - BENCH_CONNECTIONS_CONFIG_B64
  - BENCH_RULE_BANKS_CONFIG_B64
  - BENCH_BENCHMARKS_CONFIG_B64
"""

from __future__ import annotations

import base64
import json
from functools import lru_cache
from typing import Annotated, Any, Dict, List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _parse_benchmark_ids(value: object) -> List[str]:
    """Нормализация benchmark_ids из CSV/JSON/list."""
    if value is None:
        return []

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        if raw.startswith("["):
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValueError("benchmark_ids JSON должен быть массивом")
            return [str(item).strip() for item in parsed if str(item).strip()]
        return [item.strip() for item in raw.split(",") if item.strip()]

    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    raise ValueError("benchmark_ids должен быть строкой или списком")


def _decode_json_from_base64(value: str, field_name: str) -> Dict[str, Any]:
    """Декодирует base64 JSON-строку в dict и валидирует формат."""
    try:
        decoded_bytes = base64.b64decode(value.encode("utf-8"), validate=True)
    except Exception as exc:
        raise ValueError(f"{field_name} не является корректным base64") from exc

    try:
        parsed = json.loads(decoded_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"{field_name} содержит некорректный JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} должен декодироваться в JSON-объект")
    return parsed


class AppSettings(BaseSettings):
    """Глобальные настройки запуска benchmark runner."""

    celery_config_b64: str
    connections_config_b64: str
    rule_banks_config_b64: str
    benchmarks_config_b64: str

    benchmark_ids: Annotated[List[str], NoDecode] = Field(default_factory=list)
    benchmark_run_id: Optional[int] = None

    model_config = SettingsConfigDict(
        env_prefix="BENCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator(
        "celery_config_b64",
        "connections_config_b64",
        "rule_banks_config_b64",
        "benchmarks_config_b64",
        mode="before",
    )
    @classmethod
    def validate_required_b64_fields(cls, value: object) -> str:
        """Обязательные base64-поля должны быть непустыми строками."""
        if value is None:
            raise ValueError("обязательная переменная окружения не задана")
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("значение base64 не должно быть пустым")
        return cleaned

    @field_validator("benchmark_ids", mode="before")
    @classmethod
    def parse_benchmark_ids(cls, value: object) -> List[str]:
        """
        Поддерживает несколько форматов:
          - JSON array: '["bench_a","bench_b"]'
          - CSV строка: 'bench_a,bench_b'
          - list из env/кода.
        """
        return _parse_benchmark_ids(value)

    def decode_celery_config(self) -> Dict[str, Any]:
        """Возвращает celery-конфиг из BENCH_CELERY_CONFIG_B64."""
        return _decode_json_from_base64(
            self.celery_config_b64,
            "BENCH_CELERY_CONFIG_B64",
        )

    def decode_connections_config(self) -> Dict[str, Any]:
        """Возвращает connections-конфиг из BENCH_CONNECTIONS_CONFIG_B64."""
        return _decode_json_from_base64(
            self.connections_config_b64,
            "BENCH_CONNECTIONS_CONFIG_B64",
        )

    def decode_rule_banks_config(self) -> Dict[str, Any]:
        """Возвращает rule-banks конфиг из BENCH_RULE_BANKS_CONFIG_B64."""
        return _decode_json_from_base64(
            self.rule_banks_config_b64,
            "BENCH_RULE_BANKS_CONFIG_B64",
        )

    def decode_benchmarks_config(self) -> Dict[str, Any]:
        """Возвращает benchmarks-конфиг из BENCH_BENCHMARKS_CONFIG_B64."""
        return _decode_json_from_base64(
            self.benchmarks_config_b64,
            "BENCH_BENCHMARKS_CONFIG_B64",
        )


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Кэшируем настройки, чтобы не перечитывать env на каждом вызове."""
    return AppSettings()
