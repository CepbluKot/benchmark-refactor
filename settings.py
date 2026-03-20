"""
Runtime-настройки запуска бенчмарка через переменные окружения.

JSON-конфиги передаются как base64-строки:
  - BENCH_CELERY_CONFIG_B64
  - BENCH_CONNECTIONS_CONFIG_B64
  - BENCH_RULE_BANKS_CONFIG_B64
  - BENCH_BENCHMARKS_CONFIG_B64

Дополнительные параметры launcher:
  - BENCH_TEST_DATABASE
  - BENCH_RESULT_CONNECTION_ID
  - BENCH_RESULT_DATABASE
  - BENCH_RESULT_TABLE
  - BENCH_LEGACY_RESULT_TABLE
  - BENCH_PHASED_RESULT_TABLE
  - BENCH_PHASED_RUNS_TABLE
"""

from __future__ import annotations

import base64
import json
import logging
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


def _normalize_log_level(value: object) -> str:
    """Нормализует уровень логирования к одному из стандартных уровней."""
    if value is None:
        return "INFO"

    normalized = str(value).strip().upper()
    if not normalized:
        return "INFO"

    valid_levels = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
    if normalized in valid_levels:
        return normalized

    # Поддерживаем также числовые уровни logging (например, 20).
    try:
        numeric = int(normalized)
    except ValueError as exc:
        raise ValueError(
            "log_level должен быть одним из: CRITICAL, ERROR, WARNING, INFO, DEBUG, NOTSET "
            "или числовым уровнем logging"
        ) from exc

    if numeric < logging.NOTSET:
        raise ValueError("числовой log_level не может быть отрицательным")
    return str(numeric)


class AppSettings(BaseSettings):
    """Глобальные настройки запуска benchmark runner."""

    celery_config_b64: str
    connections_config_b64: str
    rule_banks_config_b64: str
    benchmarks_config_b64: str

    benchmark_ids: Annotated[List[str], NoDecode] = Field(default_factory=list)
    benchmark_run_id: Optional[int] = None
    test_database: Optional[str] = None
    result_connection_id: Optional[str] = None
    result_database: str = "benchmark_results"
    result_table: str = "benchmark_results"
    legacy_result_table: Optional[str] = None
    phased_result_table: Optional[str] = None
    phased_runs_table: str = "benchmark_runs"
    log_level: str = "INFO"
    source_result_timeout_sec: float = 3600.0

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

    @field_validator("log_level", mode="before")
    @classmethod
    def parse_log_level(cls, value: object) -> str:
        """Нормализует уровень логирования из окружения."""
        return _normalize_log_level(value)

    @field_validator("test_database", mode="before")
    @classmethod
    def parse_test_database(cls, value: object) -> Optional[str]:
        """Нормализует имя тестовой БД (или выключает override при пустом значении)."""
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        return normalized

    @field_validator("result_connection_id", mode="before")
    @classmethod
    def parse_result_connection_id(cls, value: object) -> Optional[str]:
        """Нормализует id connection для result-store (или выключает override)."""
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        return normalized

    @field_validator("result_database", "result_table", mode="before")
    @classmethod
    def parse_non_empty_result_target(cls, value: object) -> str:
        """Проверяет, что target result-store не пустой."""
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("result_database/result_table не должны быть пустыми")
        return normalized

    @field_validator("legacy_result_table", "phased_result_table", mode="before")
    @classmethod
    def parse_optional_table_name(cls, value: object) -> Optional[str]:
        """Нормализует optional имя таблицы (пустая строка -> None)."""
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        return normalized

    @field_validator("phased_runs_table", mode="before")
    @classmethod
    def parse_phased_runs_table(cls, value: object) -> str:
        """Проверяет, что имя phased runs table не пустое."""
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("phased_runs_table не должно быть пустым")
        return normalized

    @field_validator("source_result_timeout_sec", mode="before")
    @classmethod
    def parse_source_result_timeout_sec(cls, value: object) -> float:
        """Нормализует таймаут ожидания source task."""
        if value is None:
            return 3600.0
        text = str(value).strip()
        if not text:
            return 3600.0
        try:
            parsed = float(text)
        except Exception as exc:
            raise ValueError("source_result_timeout_sec должен быть числом секунд") from exc
        if parsed <= 0:
            raise ValueError("source_result_timeout_sec должен быть > 0")
        return parsed

    @property
    def resolved_legacy_result_table(self) -> str:
        """Эффективная таблица для старых стратегий."""
        return self.legacy_result_table or self.result_table

    @property
    def resolved_phased_result_table(self) -> str:
        """Эффективная таблица для phased-стратегии."""
        return self.phased_result_table or f"{self.result_table}__phased"

    @property
    def resolved_phased_runs_table(self) -> str:
        """Эффективная таблица run-level метаданных для phased-стратегии."""
        return self.phased_runs_table

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
