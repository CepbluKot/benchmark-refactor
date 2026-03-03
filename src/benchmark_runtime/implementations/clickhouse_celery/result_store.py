"""ClickHouse-backed result store для benchmark runtime."""

from __future__ import annotations

import json
import logging
import os
import re
from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
from threading import Lock
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from src.clickhouse_ddl import TableDDL
from src.models import ConnectionConfig
from src.naming import parse_variant_name

from ...contracts.result_store import BenchmarkResultStore
from ...types import (
    BenchmarkVariantResult,
    Query,
    ScoringConfig,
    StoredVariantSummary,
    StoredBenchmarkResult,
    TableBenchmarkPlan,
    TopTypeVariant,
    VariantJob,
    build_variant_params,
)
from .common import json_dumps, make_readable_bytes
from .scoring import ScoreEvaluationError, evaluate_score_expression, validate_score_expression

logger = logging.getLogger(__name__)

_RESULTS_TIMEZONE_NAME = "Europe/Moscow"
_RESULTS_TZ = ZoneInfo(_RESULTS_TIMEZONE_NAME)

try:
    import sqlparse  # type: ignore
except ImportError:  # pragma: no cover - опциональная зависимость для красивого SQL-format.
    sqlparse = None

try:
    import redis as redis_module  # type: ignore
except ImportError:  # pragma: no cover - redis опционален.
    redis_module = None


class ClickHouseConnectionParams(BaseModel):
    """Минимальные параметры подключения к ClickHouse."""

    host: str
    port: int = Field(default=9000, gt=0)
    login: str
    password: str

    @classmethod
    def from_connection_config(cls, connection: ConnectionConfig) -> "ClickHouseConnectionParams":
        """Создаёт параметры подключения из runtime `ConnectionConfig`."""
        return cls(
            host=connection.host,
            port=connection.port,
            login=connection.login,
            password=connection.password,
        )


class ClickHouseBenchmarkResultStore(BenchmarkResultStore):
    """Хранилище результатов в ClickHouse с поддержкой top-N для sequential stage2."""

    _PHASED_STRATEGIES: tuple[str, ...] = ("sequential_phased_topn_strategy",)

    _PHASE_BY_VARIANT_MODE: dict[str, int] = {
        "source_baseline": 0,
        "order_by": 1,
        "types": 2,
        "types_validation": 2,
        "codecs": 3,
        "codecs_validation": 3,
        "index_granularity": 4,
        "indexes": 5,
        "indexes_validation": 5,
        "final_validation": 6,
    }
    _PHASE_NAME_BY_VARIANT_MODE: dict[str, str] = {
        "source_baseline": "source_baseline",
        "order_by": "order_by",
        "types": "types",
        "types_validation": "types_validation",
        "codecs": "codecs",
        "codecs_validation": "codecs_validation",
        "index_granularity": "index_granularity",
        "indexes": "indexes",
        "indexes_validation": "indexes_validation",
        "final_validation": "final_validation",
    }

    _LEGACY_DUPLICATE_SIZE_COLUMNS: tuple[str, ...] = (
        "tested_table_total_size_bytes_with_indexes",
        "tested_table_total_size_bytes_with_indexes_readable",
    )
    _LEGACY_PRIMARY_INDEX_SPLIT_COLUMNS: tuple[str, ...] = (
        "tested_table_primary_index_size_bytes",
        "tested_table_primary_index_size_bytes_readable",
        "tested_table_primary_index_size_percent_from_total_size",
    )
    _LEGACY_DATA_SKIPPING_INDEX_PERCENT_COLUMNS: tuple[str, ...] = (
        "tested_table_indexes_sizes_percent_from_col_size",
    )
    _LEGACY_DUPLICATE_STAGE_COLUMNS: tuple[str, ...] = (
        "phase",
        "phase_name",
    )

    _LEGACY_MEMORY_COLUMNS: tuple[str, ...] = (
        "tested_table_insert_memory_usage_measurements",
        "source_table_insert_memory_usage_measurements",
        "tested_table_insert_memory_usage_measurements_percentiles",
        "source_table_insert_memory_usage_measurements_percentiles",
        "tested_table_select_memory_usage_measurements",
        "source_table_select_memory_usage_measurements",
        "tested_table_select_memory_usage_measurements_percentiles",
        "source_table_select_memory_usage_measurements_percentiles",
        "tested_table_insert_memory_usage_measurements_readable",
        "source_table_insert_memory_usage_measurements_readable",
        "tested_table_insert_memory_usage_measurements_percentiles_readable",
        "source_table_insert_memory_usage_measurements_percentiles_readable",
        "tested_table_select_memory_usage_measurements_readable",
        "source_table_select_memory_usage_measurements_readable",
        "tested_table_select_memory_usage_measurements_percentiles_readable",
        "source_table_select_memory_usage_measurements_percentiles_readable",
    )

    _LEGACY_SELECT_AGGREGATE_COLUMNS: tuple[str, ...] = (
        "tested_table_select_time_ms_measurements",
        "source_table_select_time_ms_measurements",
        "tested_table_select_time_ms_measurements_percentiles",
        "source_table_select_time_ms_measurements_percentiles",
        "tested_table_select_time_ms_measurements_percentiles_speed_up_coefs",
        "tested_table_select_rows_per_second_measurements",
        "source_table_select_rows_per_second_measurements",
        "tested_table_select_rows_per_second_measurements_percentiles",
        "source_table_select_rows_per_second_measurements_percentiles",
        "tested_table_select_bytes_per_second_measurements",
        "tested_table_select_bytes_per_second_measurements_readable",
        "source_table_select_bytes_per_second_measurements",
        "source_table_select_bytes_per_second_measurements_readable",
        "tested_table_select_bytes_per_second_measurements_percentiles",
        "tested_table_select_bytes_per_second_measurements_percentiles_readable",
        "source_table_select_bytes_per_second_measurements_percentiles",
        "source_table_select_bytes_per_second_measurements_percentiles_readable",
    )
    _RUNS_LEGACY_UNUSED_COLUMNS: tuple[str, ...] = (
        "source_table_ddl",
        "total_rows",
        "data_path",
        "benchmark_queries",
        "score_weights",
        "config_json",
    )
    _INSERT_COLUMNS: list[str] = [
        "benchmark_run_id",
        "benchmark_started_at",
        "benchmark_id",
        "id",
        "parent_id",
        "celery_task_id",
        "celery_worker_hostname",
        "started_at",
        "finished_at",
        "source_db_name",
        "source_table_name",
        "tested_table_ddl",
        "variant_params_json",
        "source_table_ddl",
        "is_source_table_copy",
        "index_params",
        "total_n_rows_in_tested_table",
        "total_n_rows_in_source_table",
        "measured_percentiles",
        "insert_test_n_rows",
        "tested_table_insert_time_ms_measurements",
        "source_table_insert_time_ms_measurements",
        "tested_table_insert_time_ms_measurements_percentiles",
        "source_table_insert_time_ms_measurements_percentiles",
        "tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs",
        "tested_table_insert_rows_per_second_measurements",
        "source_table_insert_rows_per_second_measurements",
        "tested_table_insert_rows_per_second_measurements_percentiles",
        "source_table_insert_rows_per_second_measurements_percentiles",
        "tested_table_insert_bytes_per_second_measurements",
        "tested_table_insert_bytes_per_second_measurements_readable",
        "source_table_insert_bytes_per_second_measurements",
        "source_table_insert_bytes_per_second_measurements_readable",
        "tested_table_insert_bytes_per_second_measurements_percentiles",
        "tested_table_insert_bytes_per_second_measurements_percentiles_readable",
        "source_table_insert_bytes_per_second_measurements_percentiles",
        "source_table_insert_bytes_per_second_measurements_percentiles_readable",
        "tested_table_insert_metrics_json",
        "source_table_insert_metrics_json",
        "tested_table_select_test_query",
        "source_table_select_test_query",
        "select_metrics_json",
        "tested_table_select_metrics_by_query_json",
        "source_table_select_metrics_by_query_json",
        "tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json",
        "tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json",
        "tested_table_select_time_ms_percentiles_speed_up_coefs_vs_source_by_query_json",
        "tested_table_consumed_compressed_size_bytes_by_each_column",
        "source_table_consumed_compressed_size_bytes_by_each_column",
        "tested_table_consumed_compressed_size_bytes_overall",
        "tested_table_consumed_compressed_size_bytes_overall_readable",
        "tested_table_consumed_compressed_size_bytes_with_indexes_json",
        "tested_table_primary_index_size_json",
        "source_table_consumed_compressed_size_bytes_overall_json",
        "tested_table_compression_overall_coef",
        "tested_table_compression_by_each_column_coef",
        "source_table_n_rows_in_size_test",
        "tested_table_n_rows_in_size_test",
        "size_bytes_total",
        "size_bytes_by_column_json",
        "size_bytes_indexes_json",
        "tested_table_cols_sizes",
        "tested_table_indexes_sizes",
        "insert_metrics_json",
        "extra_json",
        "variant_table",
        "variant_mode",
        "variant_mode_id",
        "variant_params",
        "rank_in_phase",
        "is_top_n",
        "measurement_quality_flag",
        "measurement_quality_details_json",
        "score_calculation_json",
        "score",
    ]
    _PHASED_INSERT_COLUMNS: list[str] = [
        "benchmark_run_id",
        "benchmark_started_at",
        "benchmark_id",
        "id",
        "parent_id",
        "celery_task_id",
        "celery_worker_hostname",
        "started_at",
        "finished_at",
        "source_db_name",
        "source_table_name",
        "tested_table_ddl",
        "variant_params_json",
        "variant_table",
        "variant_mode",
        "variant_mode_id",
        "variant_params",
        "total_n_rows_in_tested_table",
        "size_bytes_total",
        "size_bytes_by_column_json",
        "size_bytes_indexes_json",
        "tested_table_consumed_compressed_size_bytes_with_indexes_json",
        "tested_table_primary_index_size_json",
        "source_table_consumed_compressed_size_bytes_overall_json",
        "tested_table_compression_overall_coef",
        "select_metrics_json",
        "tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json",
        "tested_table_select_time_ms_percentiles_speed_up_coefs_vs_source_by_query_json",
        "insert_metrics_json",
        "score_calculation_json",
        "score",
        "rank_in_phase",
        "is_top_n",
        "measurement_quality_flag",
        "measurement_quality_details_json",
    ]
    _PRETTY_JSON_STRING_COLUMNS: tuple[str, ...] = (
        "index_params",
        "variant_params_json",
        "tested_table_select_metrics_by_query_json",
        "source_table_select_metrics_by_query_json",
        "tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json",
        "tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json",
        "tested_table_select_time_ms_percentiles_speed_up_coefs_vs_source_by_query_json",
        "select_metrics_json",
        "tested_table_insert_metrics_json",
        "source_table_insert_metrics_json",
        "insert_metrics_json",
        "size_bytes_by_column_json",
        "size_bytes_indexes_json",
        "tested_table_consumed_compressed_size_bytes_by_each_column",
        "source_table_consumed_compressed_size_bytes_by_each_column",
        "tested_table_compression_by_each_column_coef",
        "tested_table_cols_sizes",
        "tested_table_primary_index_size_json",
        "tested_table_consumed_compressed_size_bytes_with_indexes_json",
        "source_table_consumed_compressed_size_bytes_overall_json",
        "measurement_quality_details_json",
        "score_calculation_json",
    )
    _SQL_TEXT_COLUMNS: tuple[str, ...] = (
        "tested_table_ddl",
        "source_table_ddl",
        "tested_table_select_test_query",
        "source_table_select_test_query",
    )
    _SQL_JSON_COLUMNS: tuple[str, ...] = (
        "select_metrics_json",
        "tested_table_select_metrics_by_query_json",
        "source_table_select_metrics_by_query_json",
        "tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json",
        "tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json",
        "tested_table_select_time_ms_percentiles_speed_up_coefs_vs_source_by_query_json",
    )
    _CUSTOM_SCORE_CONTEXT_FALLBACK_KEYS: frozenset[str] = frozenset(
        {
            "measured_percentiles",
            "source",
            "tested",
            "speedup",
            "compression",
            "compression_overall_coef",
            "ratios",
            "medians",
            "source_size_bytes",
            "tested_size_bytes",
            "per_query",
            "tested_table_insert_metrics_json",
            "source_table_insert_metrics_json",
            "tested_table_select_metrics_by_query_json",
            "source_table_select_metrics_by_query_json",
            "tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json",
            "tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json",
            "tested_table_select_time_ms_percentiles_speed_up_coefs_vs_source_by_query_json",
        }
    )

    def __init__(
        self,
        connection: ConnectionConfig | ClickHouseConnectionParams,
        database: str = "benchmark_results",
        table: str = "benchmark_results",
        runs_table: str = "benchmark_runs",
        legacy_table: Optional[str] = None,
        phased_table: Optional[str] = None,
        phased_runs_table: Optional[str] = None,
        create_legacy_table: bool = True,
        *,
        create_table_if_missing: bool = True,
    ) -> None:
        if isinstance(connection, ConnectionConfig):
            self._connection = ClickHouseConnectionParams.from_connection_config(connection)
        else:
            self._connection = connection
        self._database = database
        self._legacy_table = legacy_table or table
        self._phased_table = phased_table or table
        self._phased_runs_table = phased_runs_table or runs_table
        self._create_legacy_table = bool(create_legacy_table)
        # Backward-compat properties for legacy call-sites/tests.
        self._table = self._phased_table
        self._runs_table = self._phased_runs_table
        self._client = self._build_client()
        self._record_insert_lock = Lock()
        self._record_lock_redis_client = None
        self._record_lock_redis_prefix = str(
            os.getenv("BENCH_RESULT_STORE_REDIS_LOCK_PREFIX", "bench_result_store_lock")
        ).strip() or "bench_result_store_lock"
        self._record_lock_redis_ttl_sec = self._parse_float_env(
            "BENCH_RESULT_STORE_REDIS_LOCK_TTL_SEC",
            default=300.0,
        )
        self._record_lock_redis_blocking_timeout_sec = self._parse_float_env(
            "BENCH_RESULT_STORE_REDIS_LOCK_BLOCKING_TIMEOUT_SEC",
            default=60.0,
        )
        self._record_lock_redis_url = self._resolve_redis_lock_url()
        self._init_redis_lock_client()

        if create_table_if_missing:
            self.ensure_schema()

    @property
    def database(self) -> str:
        """Имя БД, где хранится таблица результатов."""
        return self._database

    @property
    def table(self) -> str:
        """Имя таблицы результатов."""
        return self._phased_table

    @property
    def runs_table(self) -> str:
        """Имя таблицы run-level метаданных."""
        return self._phased_runs_table

    @property
    def legacy_table(self) -> str:
        """Имя legacy-таблицы результатов (для старых стратегий)."""
        return self._legacy_table

    @property
    def phased_table(self) -> str:
        """Имя phased-таблицы результатов (для новой стратегии)."""
        return self._phased_table

    @property
    def phased_runs_table(self) -> str:
        """Имя phased run-level таблицы."""
        return self._phased_runs_table

    def close(self) -> None:
        """Закрывает ClickHouse клиент (idempotent)."""
        try:
            if self._client is not None:
                close_method = getattr(self._client, "close", None)
                if callable(close_method):
                    close_method()
        except Exception:
            logger.exception("ClickHouseBenchmarkResultStore: ошибка close")

    def ensure_schema(self) -> None:
        """Создаёт БД/таблицу результатов, если они отсутствуют."""
        self._execute(f"CREATE DATABASE IF NOT EXISTS `{self._database}`")
        self._execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self._database}`.`{self._phased_runs_table}`
            (
                `id` String,
                `benchmark_run_id` Int32,
                `benchmark_id` String,
                `started_at` Nullable(DateTime64(3, 'Europe/Moscow')),
                `finished_at` Nullable(DateTime64(3, 'Europe/Moscow')),
                `source_db_name` String,
                `source_table_name` String,
                `top_n_winners` Nullable(Int32),
                `sequential_top_n_limits_json` Nullable(String),
                `updated_at` DateTime64(3, 'Europe/Moscow')
            )
            ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY (id)
            """
        )
        self._execute(
            f"""
            ALTER TABLE `{self._database}`.`{self._phased_runs_table}`
                ADD COLUMN IF NOT EXISTS `sequential_top_n_limits_json` Nullable(String)
            """
        )
        self._ensure_datetime_columns_timezone(
            table_name=self._phased_runs_table,
            column_types={
                "started_at": "Nullable(DateTime64(3, 'Europe/Moscow'))",
                "finished_at": "Nullable(DateTime64(3, 'Europe/Moscow'))",
                "updated_at": "DateTime64(3, 'Europe/Moscow')",
            },
        )
        for column_name in self._RUNS_LEGACY_UNUSED_COLUMNS:
            self._execute(
                f"""
                ALTER TABLE `{self._database}`.`{self._phased_runs_table}`
                    DROP COLUMN IF EXISTS `{column_name}`
                """
            )

        if self._legacy_table == self._phased_table and self._create_legacy_table:
            self._ensure_results_table_schema(self._phased_table)
            return
        self._ensure_phased_results_table_schema(self._phased_table)
        if self._create_legacy_table:
            self._ensure_results_table_schema(self._legacy_table)

    def _ensure_phased_results_table_schema(self, table_name: str) -> None:
        """Создаёт/мигрирует таблицу phased-стратегии (новая компактная схема)."""
        self._execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self._database}`.`{table_name}`
            (
                `benchmark_run_id` Int32,
                `benchmark_started_at` DateTime64(3, 'Europe/Moscow'),
                `benchmark_id` String,
                `id` String,
                `parent_id` Nullable(String),
                `celery_task_id` Nullable(String),
                `celery_worker_hostname` Nullable(String),
                `started_at` DateTime64(3, 'Europe/Moscow'),
                `finished_at` Nullable(DateTime64(3, 'Europe/Moscow')),
                `source_db_name` String,
                `source_table_name` String,
                `tested_table_ddl` String,
                `variant_params_json` Nullable(String),
                `variant_table` String,
                `variant_mode` String,
                `variant_mode_id` Nullable(Int32),
                `variant_params` String,
                `total_n_rows_in_tested_table` Nullable(Int64),
                `size_bytes_total` Nullable(Float64),
                `size_bytes_by_column_json` Nullable(String),
                `size_bytes_indexes_json` Nullable(String),
                `tested_table_consumed_compressed_size_bytes_with_indexes_json` Nullable(String),
                `tested_table_primary_index_size_json` Nullable(String),
                `source_table_consumed_compressed_size_bytes_overall_json` Nullable(String),
                `tested_table_compression_overall_coef` Nullable(Float64),
                `select_metrics_json` Nullable(String),
                `tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json` Nullable(String),
                `tested_table_select_time_ms_percentiles_speed_up_coefs_vs_source_by_query_json` Nullable(String),
                `insert_metrics_json` Nullable(String),
                `score_calculation_json` Nullable(String),
                `score` Nullable(Float64),
                `score_custom` Nullable(Float64),
                `rank_in_phase` Nullable(Int32),
                `is_top_n` Bool DEFAULT 0,
                `measurement_quality_flag` Nullable(String),
                `measurement_quality_details_json` Nullable(String),
                `rank_in_stage_column` Nullable(Int32),
                `is_top_n_in_stage_column` Bool DEFAULT 0
            )
            ENGINE = MergeTree
            ORDER BY (benchmark_id, benchmark_run_id, source_db_name, source_table_name, id)
            """
        )
        self._execute(
            f"""
            ALTER TABLE `{self._database}`.`{table_name}`
                ADD COLUMN IF NOT EXISTS `parent_id` Nullable(String),
                ADD COLUMN IF NOT EXISTS `celery_task_id` Nullable(String),
                ADD COLUMN IF NOT EXISTS `celery_worker_hostname` Nullable(String),
                ADD COLUMN IF NOT EXISTS `started_at` Nullable(DateTime64(3, 'Europe/Moscow')),
                ADD COLUMN IF NOT EXISTS `finished_at` Nullable(DateTime64(3, 'Europe/Moscow')),
                ADD COLUMN IF NOT EXISTS `variant_params_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `variant_mode_id` Nullable(Int32),
                ADD COLUMN IF NOT EXISTS `total_n_rows_in_tested_table` Nullable(Int64),
                ADD COLUMN IF NOT EXISTS `size_bytes_total` Nullable(Float64),
                ADD COLUMN IF NOT EXISTS `size_bytes_by_column_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `size_bytes_indexes_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `tested_table_consumed_compressed_size_bytes_with_indexes_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `tested_table_primary_index_size_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `source_table_consumed_compressed_size_bytes_overall_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `tested_table_compression_overall_coef` Nullable(Float64),
                ADD COLUMN IF NOT EXISTS `select_metrics_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `tested_table_select_time_ms_percentiles_speed_up_coefs_vs_source_by_query_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `insert_metrics_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `score_calculation_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `score_custom` Nullable(Float64),
                ADD COLUMN IF NOT EXISTS `rank_in_phase` Nullable(Int32),
                ADD COLUMN IF NOT EXISTS `is_top_n` Bool DEFAULT 0,
                ADD COLUMN IF NOT EXISTS `measurement_quality_flag` Nullable(String),
                ADD COLUMN IF NOT EXISTS `measurement_quality_details_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `rank_in_stage_column` Nullable(Int32),
                ADD COLUMN IF NOT EXISTS `is_top_n_in_stage_column` Bool DEFAULT 0
            """
        )
        self._ensure_datetime_columns_timezone(
            table_name=table_name,
            column_types={
                "benchmark_started_at": "DateTime64(3, 'Europe/Moscow')",
                "started_at": "DateTime64(3, 'Europe/Moscow')",
                "finished_at": "Nullable(DateTime64(3, 'Europe/Moscow'))",
            },
        )
        self._execute(
            f"""
            ALTER TABLE `{self._database}`.`{table_name}`
                DROP COLUMN IF EXISTS `stage_column_info_json`
            """
        )
        for column_name in self._LEGACY_PRIMARY_INDEX_SPLIT_COLUMNS:
            self._execute(
                f"""
                ALTER TABLE `{self._database}`.`{table_name}`
                    DROP COLUMN IF EXISTS `{column_name}`
                """
            )
        for column_name in self._LEGACY_DATA_SKIPPING_INDEX_PERCENT_COLUMNS:
            self._execute(
                f"""
                ALTER TABLE `{self._database}`.`{table_name}`
                    DROP COLUMN IF EXISTS `{column_name}`
                """
            )
        for column_name in self._LEGACY_DUPLICATE_STAGE_COLUMNS:
            self._execute(
                f"""
                ALTER TABLE `{self._database}`.`{table_name}`
                    DROP COLUMN IF EXISTS `{column_name}`
                """
            )

    def _ensure_results_table_schema(self, table_name: str) -> None:
        """Создаёт/мигрирует целевую таблицу результатов."""
        self._execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self._database}`.`{table_name}`
            (
                `benchmark_run_id` Int32,
                `benchmark_started_at` DateTime64(3, 'Europe/Moscow'),
                `benchmark_id` String,
                `id` String,
                `parent_id` Nullable(String),
                `celery_task_id` Nullable(String),
                `celery_worker_hostname` Nullable(String),
                `started_at` DateTime64(3, 'Europe/Moscow'),
                `finished_at` Nullable(DateTime64(3, 'Europe/Moscow')),
                `source_db_name` String,
                `source_table_name` String,
                `tested_table_ddl` String,
                `variant_params_json` Nullable(String),
                `source_table_ddl` Nullable(String),
                `is_source_table_copy` Nullable(Bool),
                `index_params` Nullable(String),
                `total_n_rows_in_tested_table` Nullable(Int64),
                `total_n_rows_in_source_table` Nullable(Int64),
                `measured_percentiles` Array(Int32),
                `insert_test_n_rows` Nullable(Int32),
                `tested_table_insert_time_ms_measurements` Array(Float64),
                `source_table_insert_time_ms_measurements` Array(Float64),
                `tested_table_insert_time_ms_measurements_percentiles` Array(Float64),
                `source_table_insert_time_ms_measurements_percentiles` Array(Float64),
                `tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs` Array(Float64),
                `tested_table_insert_rows_per_second_measurements` Array(Float64),
                `source_table_insert_rows_per_second_measurements` Array(Float64),
                `tested_table_insert_rows_per_second_measurements_percentiles` Array(Float64),
                `source_table_insert_rows_per_second_measurements_percentiles` Array(Float64),
                `tested_table_insert_bytes_per_second_measurements` Array(Float64),
                `tested_table_insert_bytes_per_second_measurements_readable` Array(String),
                `source_table_insert_bytes_per_second_measurements` Array(Float64),
                `source_table_insert_bytes_per_second_measurements_readable` Array(String),
                `tested_table_insert_bytes_per_second_measurements_percentiles` Array(Float64),
                `tested_table_insert_bytes_per_second_measurements_percentiles_readable` Array(String),
                `source_table_insert_bytes_per_second_measurements_percentiles` Array(Float64),
                `source_table_insert_bytes_per_second_measurements_percentiles_readable` Array(String),
                `tested_table_insert_metrics_json` Nullable(String),
                `source_table_insert_metrics_json` Nullable(String),
                `insert_metrics_json` Nullable(String),
                `tested_table_select_test_query` Nullable(String),
                `source_table_select_test_query` Nullable(String),
                `select_metrics_json` Nullable(String),
                `tested_table_select_metrics_by_query_json` Nullable(String),
                `source_table_select_metrics_by_query_json` Nullable(String),
                `tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json` Nullable(String),
                `tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json` Nullable(String),
                `tested_table_select_time_ms_percentiles_speed_up_coefs_vs_source_by_query_json` Nullable(String),
                `tested_table_consumed_compressed_size_bytes_by_each_column` Nullable(String),
                `source_table_consumed_compressed_size_bytes_by_each_column` Nullable(String),
                `tested_table_consumed_compressed_size_bytes_overall` Nullable(Float64),
                `tested_table_consumed_compressed_size_bytes_overall_readable` Nullable(String),
                `tested_table_consumed_compressed_size_bytes_with_indexes_json` Nullable(String),
                `tested_table_primary_index_size_json` Nullable(String),
                `source_table_consumed_compressed_size_bytes_overall_json` Nullable(String),
                `tested_table_compression_overall_coef` Nullable(Float64),
                `tested_table_compression_by_each_column_coef` Nullable(String),
                `source_table_n_rows_in_size_test` Nullable(Int64),
                `tested_table_n_rows_in_size_test` Nullable(Int64),
                `size_bytes_total` Nullable(Float64),
                `size_bytes_by_column_json` Nullable(String),
                `size_bytes_indexes_json` Nullable(String),
                `tested_table_cols_sizes` Nullable(String),
                `tested_table_indexes_sizes` Nullable(String),
                `extra_json` Nullable(String),
                `variant_table` String,
                `variant_mode` String,
                `variant_mode_id` Nullable(Int32),
                `variant_params` String,
                `rank_in_phase` Nullable(Int32),
                `is_top_n` Bool DEFAULT 0,
                `measurement_quality_flag` Nullable(String),
                `measurement_quality_details_json` Nullable(String),
                `rank_in_stage_column` Nullable(Int32),
                `is_top_n_in_stage_column` Bool DEFAULT 0,
                `score_calculation_json` Nullable(String),
                `score` Nullable(Float64),
                `score_custom` Nullable(Float64)
            )
            ENGINE = MergeTree
            ORDER BY (benchmark_id, benchmark_run_id, source_db_name, source_table_name, id)
            """
        )
        # Для уже существующей таблицы аккуратно добавляем новые колонки, чтобы
        # вставка не ломалась после обновления runtime-схемы.
        self._execute(
            f"""
            ALTER TABLE `{self._database}`.`{table_name}`
                ADD COLUMN IF NOT EXISTS `tested_table_select_metrics_by_query_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `source_table_select_metrics_by_query_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `tested_table_select_time_ms_percentiles_speed_up_coefs_vs_source_by_query_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `tested_table_insert_metrics_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `source_table_insert_metrics_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `insert_metrics_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `select_metrics_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `tested_table_consumed_compressed_size_bytes_with_indexes_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `source_table_consumed_compressed_size_bytes_overall_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `tested_table_primary_index_size_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `score_calculation_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `score_custom` Nullable(Float64),
                ADD COLUMN IF NOT EXISTS `variant_mode_id` Nullable(Int32),
                ADD COLUMN IF NOT EXISTS `parent_id` Nullable(String),
                ADD COLUMN IF NOT EXISTS `celery_task_id` Nullable(String),
                ADD COLUMN IF NOT EXISTS `celery_worker_hostname` Nullable(String),
                ADD COLUMN IF NOT EXISTS `started_at` Nullable(DateTime64(3, 'Europe/Moscow')),
                ADD COLUMN IF NOT EXISTS `finished_at` Nullable(DateTime64(3, 'Europe/Moscow')),
                ADD COLUMN IF NOT EXISTS `variant_params_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `size_bytes_total` Nullable(Float64),
                ADD COLUMN IF NOT EXISTS `size_bytes_by_column_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `size_bytes_indexes_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `rank_in_phase` Nullable(Int32),
                ADD COLUMN IF NOT EXISTS `is_top_n` Bool DEFAULT 0,
                ADD COLUMN IF NOT EXISTS `measurement_quality_flag` Nullable(String),
                ADD COLUMN IF NOT EXISTS `measurement_quality_details_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `rank_in_stage_column` Nullable(Int32),
                ADD COLUMN IF NOT EXISTS `is_top_n_in_stage_column` Bool DEFAULT 0
            """
        )
        self._ensure_datetime_columns_timezone(
            table_name=table_name,
            column_types={
                "benchmark_started_at": "DateTime64(3, 'Europe/Moscow')",
                "started_at": "DateTime64(3, 'Europe/Moscow')",
                "finished_at": "Nullable(DateTime64(3, 'Europe/Moscow'))",
            },
        )
        self._execute(
            f"""
            ALTER TABLE `{self._database}`.`{table_name}`
                DROP COLUMN IF EXISTS `stage_column_info_json`
            """
        )
        # Удаляем дублирующие legacy-поля размеров (дублируют consumed_compressed_*_with_indexes).
        for column_name in self._LEGACY_DUPLICATE_SIZE_COLUMNS:
            self._execute(
                f"""
                ALTER TABLE `{self._database}`.`{table_name}`
                    DROP COLUMN IF EXISTS `{column_name}`
                """
            )
        # Удаляем legacy-агрегаты SELECT из старой схемы:
        # теперь per-query метрики хранятся только в *_by_query_json.
        for column_name in self._LEGACY_SELECT_AGGREGATE_COLUMNS:
            self._execute(
                f"""
                ALTER TABLE `{self._database}`.`{table_name}`
                    DROP COLUMN IF EXISTS `{column_name}`
                """
            )
        # Удаляем legacy memory-колонки (раньше были отдельными полями в таблице).
        for column_name in self._LEGACY_MEMORY_COLUMNS:
            self._execute(
                f"""
                ALTER TABLE `{self._database}`.`{table_name}`
                    DROP COLUMN IF EXISTS `{column_name}`
                """
            )
        for column_name in self._LEGACY_PRIMARY_INDEX_SPLIT_COLUMNS:
            self._execute(
                f"""
                ALTER TABLE `{self._database}`.`{table_name}`
                    DROP COLUMN IF EXISTS `{column_name}`
                """
            )
        for column_name in self._LEGACY_DATA_SKIPPING_INDEX_PERCENT_COLUMNS:
            self._execute(
                f"""
                ALTER TABLE `{self._database}`.`{table_name}`
                    DROP COLUMN IF EXISTS `{column_name}`
                """
            )
        for column_name in self._LEGACY_DUPLICATE_STAGE_COLUMNS:
            self._execute(
                f"""
                ALTER TABLE `{self._database}`.`{table_name}`
                    DROP COLUMN IF EXISTS `{column_name}`
                """
            )

    def _ensure_datetime_columns_timezone(
        self,
        *,
        table_name: str,
        column_types: Dict[str, str],
    ) -> None:
        """Best-effort migration datetime колонок таблицы в Moscow timezone."""
        for column_name, column_type in column_types.items():
            try:
                self._execute(
                    f"""
                    ALTER TABLE `{self._database}`.`{table_name}`
                        MODIFY COLUMN `{column_name}` {column_type}
                    """
                )
            except Exception as exc:
                logger.warning(
                    "ClickHouseBenchmarkResultStore: не удалось применить timezone "
                    "для `%s`.`%s`.`%s` (%s)",
                    self._database,
                    table_name,
                    column_name,
                    exc,
                )

    def register_benchmark_run_start(
        self,
        *,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
        table_plan: TableBenchmarkPlan,
        source_table_ddl: str,
        benchmark_queries: Sequence[Query],
        total_rows: Optional[int],
        scoring: ScoringConfig,
    ) -> None:
        """Регистрирует старт run-контекста (per benchmark/table) в `benchmark_runs`."""
        if table_plan.strategy not in self._PHASED_STRATEGIES:
            return
        run_record_id = self._build_run_record_id(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            source_database=table_plan.database,
            source_table=table_plan.table,
        )
        del source_table_ddl, benchmark_queries, total_rows
        top_n_limits_json: Optional[str] = None
        run_settings_payload: Dict[str, Any] = {}
        if table_plan.sequential_top_n_limits is not None:
            run_settings_payload["sequential_top_n_limits"] = (
                table_plan.sequential_top_n_limits.model_dump(mode="json")
            )
        run_settings_payload["score_top_selection"] = str(
            getattr(scoring, "top_selection", "max") or "max"
        ).strip().lower()
        stage_selection_map: Dict[str, str] = {}
        for stage_name, stage_scoring in (scoring.by_stage or {}).items():
            normalized_stage_name = str(stage_name or "").strip().lower()
            if not normalized_stage_name:
                continue
            stage_selection_map[normalized_stage_name] = str(
                getattr(stage_scoring, "top_selection", "max") or "max"
            ).strip().lower()
        if stage_selection_map:
            run_settings_payload["score_top_selection_by_stage"] = stage_selection_map
        if run_settings_payload:
            top_n_limits_json = json.dumps(
                run_settings_payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        self._insert_run_row(
            run_record_id=run_record_id,
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            started_at=benchmark_started_at,
            finished_at=None,
            source_db_name=table_plan.database,
            source_table_name=table_plan.table,
            top_n_winners=int(table_plan.sequential_top_n),
            sequential_top_n_limits_json=top_n_limits_json,
        )

    def register_benchmark_run_finish(
        self,
        *,
        benchmark_run_id: int,
        table_plan: TableBenchmarkPlan,
        benchmark_finished_at: datetime,
    ) -> None:
        """Фиксирует `finished_at` для run-контекста в `benchmark_runs`."""
        if table_plan.strategy not in self._PHASED_STRATEGIES:
            return
        run_record_id = self._build_run_record_id(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            source_database=table_plan.database,
            source_table=table_plan.table,
        )
        latest = self._execute(
            f"""
            SELECT
                benchmark_run_id,
                benchmark_id,
                started_at,
                source_db_name,
                source_table_name,
                top_n_winners,
                sequential_top_n_limits_json
            FROM `{self._database}`.`{self._runs_table}`
            WHERE id = %(id)s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            {"id": run_record_id},
        )
        if latest:
            (
                existing_run_id,
                existing_benchmark_id,
                existing_started_at,
                existing_source_db,
                existing_source_table,
                existing_top_n,
                existing_limits_json,
            ) = latest[0]
        else:
            existing_run_id = benchmark_run_id
            existing_benchmark_id = table_plan.benchmark_id
            existing_started_at = benchmark_finished_at
            existing_source_db = table_plan.database
            existing_source_table = table_plan.table
            existing_top_n = int(table_plan.sequential_top_n)
            existing_limits_json = None

        self._insert_run_row(
            run_record_id=run_record_id,
            benchmark_run_id=int(existing_run_id),
            benchmark_id=str(existing_benchmark_id),
            started_at=self._to_aware_storage_datetime(existing_started_at),
            finished_at=benchmark_finished_at,
            source_db_name=str(existing_source_db),
            source_table_name=str(existing_source_table),
            top_n_winners=int(existing_top_n) if existing_top_n is not None else None,
            sequential_top_n_limits_json=(
                str(existing_limits_json) if existing_limits_json is not None else None
            ),
        )

    def _insert_run_row(
        self,
        *,
        run_record_id: str,
        benchmark_run_id: int,
        benchmark_id: str,
        started_at: datetime,
        finished_at: Optional[datetime],
        source_db_name: str,
        source_table_name: str,
        top_n_winners: Optional[int],
        sequential_top_n_limits_json: Optional[str],
    ) -> None:
        """Пишет snapshot run-контекста в `benchmark_runs` (upsert через ReplacingMergeTree)."""
        started_at_ch = self._to_naive_storage_datetime(started_at)
        finished_at_ch = self._to_naive_storage_datetime(finished_at)
        updated_at_ch = self._to_naive_storage_datetime(datetime.now(_RESULTS_TZ))
        self._insert_row_map(
            table_name=self._runs_table,
            row_map={
                "id": run_record_id,
                "benchmark_run_id": int(benchmark_run_id),
                "benchmark_id": str(benchmark_id),
                "started_at": started_at_ch,
                "finished_at": finished_at_ch,
                "source_db_name": str(source_db_name),
                "source_table_name": str(source_table_name),
                "top_n_winners": int(top_n_winners) if top_n_winners is not None else None,
                "sequential_top_n_limits_json": sequential_top_n_limits_json,
                "updated_at": updated_at_ch,
            },
            preferred_columns=[
                "id",
                "benchmark_run_id",
                "benchmark_id",
                "started_at",
                "finished_at",
                "source_db_name",
                "source_table_name",
                "top_n_winners",
                "sequential_top_n_limits_json",
                "updated_at",
            ],
        )

    def store_result(
        self,
        job: VariantJob,
        result: BenchmarkVariantResult,
    ) -> None:
        """Сохраняет результат варианта в ClickHouse."""
        variant_params = (
            dict(result.variant_params)
            if result.variant_params
            else build_variant_params(job.variant_meta)
        )
        record = self._build_record(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            variant_mode=result.variant_mode or job.variant_meta.mode,
            variant_params=variant_params,
            tested_table_ddl_fallback=job.variant_ddl.to_ddl(),
            source_table_ddl_fallback=(
                job.source_benchmark.source_table_ddl if job.source_benchmark else None
            ),
            result=result,
        )
        self._store_record_by_strategy(
            record=record,
            benchmark_strategy=job.benchmark_strategy,
        )

    def store_worker_result(
        self,
        *,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
        benchmark_id: str,
        benchmark_strategy: str = "types_strategy",
        source_database: str,
        source_table: str,
        variant_table: str,
        variant_mode: str,
        variant_params: Dict[str, Any],
        tested_table_ddl_fallback: str,
        source_table_ddl_fallback: Optional[str],
        result: BenchmarkVariantResult,
    ) -> None:
        """
        Сохраняет результат со стороны Celery-воркера без сборки `VariantJob`.
        """
        record = self._build_record(
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            variant_table=variant_table,
            variant_mode=result.variant_mode or variant_mode,
            variant_params=variant_params,
            tested_table_ddl_fallback=tested_table_ddl_fallback,
            source_table_ddl_fallback=source_table_ddl_fallback,
            result=result,
        )
        self._store_record_by_strategy(
            record=record,
            benchmark_strategy=benchmark_strategy,
        )

    def clone_result_for_equivalent_ddl(
        self,
        *,
        benchmark_strategy: str,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        variant_table: str,
        variant_mode: str,
        variant_params: Dict[str, Any],
        tested_table_ddl: str,
        source_table_ddl: Optional[str],
        celery_task_id: Optional[str],
        celery_worker_hostname: Optional[str],
        worker_started_at: Optional[datetime] = None,
        worker_finished_at: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Клонирует существующий результат для эквивалентного DDL без повторного прогона.

        Поиск выполняется по истории запусков (не только внутри текущего run_id):
          - benchmark_id / source_db_name / source_table_name / variant_mode;
          - сигнатура DDL;
          - runtime-сигнатуры query-plan/insert-limit/insert-ops/percentiles.
        """
        table_name = (
            self._phased_table
            if self._is_phased_strategy(benchmark_strategy)
            else self._legacy_table
        )
        normalized_variant_table = str(variant_table or "").strip()
        if not normalized_variant_table:
            return None
        normalized_variant_mode = str(variant_mode or "").strip()
        if not normalized_variant_mode:
            return None

        normalized_params = dict(variant_params or {})
        runtime_query_signature = str(
            normalized_params.get("__runtime_query_signature") or ""
        ).strip()
        runtime_insert_rows_limit = normalized_params.get("__runtime_insert_rows_limit")
        runtime_insert_operations_count = normalized_params.get(
            "__runtime_insert_operations_count"
        )
        runtime_percentiles_signature = str(
            normalized_params.get("__runtime_measured_percentiles_signature") or ""
        ).strip()

        target_ddl_formatted = self._format_ddl_or_as_is(str(tested_table_ddl or "").strip())
        target_ddl_signature = self._ddl_signature(target_ddl_formatted)
        if not target_ddl_signature:
            return None

        candidate_rows = self._execute(
            f"""
            SELECT
                id,
                benchmark_run_id,
                variant_table,
                tested_table_ddl,
                score,
                measurement_quality_flag,
                variant_params
            FROM `{self._database}`.`{table_name}`
            WHERE benchmark_id = %(benchmark_id)s
              AND source_db_name = %(source_database)s
              AND source_table_name = %(source_table)s
              AND variant_mode = %(variant_mode)s
            ORDER BY benchmark_run_id DESC, finished_at DESC, benchmark_started_at DESC, id DESC
            LIMIT 5000
            """,
            {
                "benchmark_id": str(benchmark_id),
                "source_database": str(source_database),
                "source_table": str(source_table),
                "variant_mode": normalized_variant_mode,
            },
        )
        matched_source_row: Optional[tuple[Any, Any, Any, Any, Any]] = None
        for row in candidate_rows:
            if len(row) < 7:
                continue
            (
                source_id,
                _source_run_id,
                source_variant_table,
                source_ddl,
                source_score,
                source_quality_flag,
                source_variant_params_raw,
            ) = row
            if str(source_variant_table or "").strip() == normalized_variant_table:
                continue
            if self._ddl_signature(str(source_ddl or "")) != target_ddl_signature:
                continue
            source_variant_params = self._parse_json_dict_or_empty(source_variant_params_raw)
            if runtime_query_signature:
                if str(source_variant_params.get("__runtime_query_signature") or "").strip() != runtime_query_signature:
                    continue
            if runtime_insert_rows_limit is not None:
                if source_variant_params.get("__runtime_insert_rows_limit") != runtime_insert_rows_limit:
                    continue
            if runtime_insert_operations_count is not None:
                if source_variant_params.get("__runtime_insert_operations_count") != runtime_insert_operations_count:
                    continue
            if runtime_percentiles_signature:
                if str(source_variant_params.get("__runtime_measured_percentiles_signature") or "").strip() != runtime_percentiles_signature:
                    continue
            matched_source_row = (
                source_id,
                source_variant_table,
                source_score,
                source_quality_flag,
                source_variant_params_raw,
            )
            break

        if matched_source_row is None:
            return None

        source_result_id, source_variant_table, source_score, source_quality_flag, _ = matched_source_row
        if source_result_id is None:
            return None

        parent_variant_table = self._extract_parent_variant_table(normalized_params)
        parent_id: Optional[str] = None
        if parent_variant_table:
            parent_id = self._resolve_parent_result_id(
                benchmark_run_id=benchmark_run_id,
                benchmark_id=benchmark_id,
                source_database=source_database,
                source_table=source_table,
                parent_variant_table=parent_variant_table,
            )
        variant_mode_id = self._resolve_variant_mode_id(
            variant_table=normalized_variant_table,
            variant_params=normalized_params,
        )
        execution_uuid = str(normalized_params.get("execution_uuid") or "").strip()
        result_token = execution_uuid or normalized_variant_table or str(uuid4())
        cloned_result_id = self._build_scoped_result_id(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            variant_table=normalized_variant_table,
            raw_result_token=result_token,
        )
        target_variant_params_json = json.dumps(
            normalized_params,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        target_variant_params_raw = json.dumps(
            normalized_params,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        worker_started_at_value = self._to_naive_storage_datetime(
            worker_started_at or datetime.now(_RESULTS_TZ)
        )
        worker_finished_at_value = self._to_naive_storage_datetime(
            worker_finished_at or datetime.now(_RESULTS_TZ)
        )
        benchmark_started_at_value = self._to_naive_storage_datetime(benchmark_started_at)
        source_table_ddl_formatted: Optional[str] = None
        if source_table_ddl:
            source_table_ddl_formatted = self._format_ddl_or_as_is(source_table_ddl)

        column_names = (
            list(self._PHASED_INSERT_COLUMNS)
            if table_name == self._phased_table
            else list(self._INSERT_COLUMNS)
        )
        override_values: Dict[str, Any] = {
            "benchmark_started_at": benchmark_started_at_value,
            "id": cloned_result_id,
            "parent_id": parent_id,
            "celery_task_id": str(celery_task_id).strip() if celery_task_id else None,
            "celery_worker_hostname": (
                str(celery_worker_hostname).strip() if celery_worker_hostname else None
            ),
            "started_at": worker_started_at_value,
            "finished_at": worker_finished_at_value,
            "tested_table_ddl": target_ddl_formatted,
            "variant_params_json": target_variant_params_json,
            "variant_table": normalized_variant_table,
            "variant_mode": normalized_variant_mode,
            "variant_mode_id": variant_mode_id,
            "variant_params": target_variant_params_raw,
            "rank_in_phase": None,
            "is_top_n": False,
        }
        if "source_table_ddl" in column_names and source_table_ddl_formatted is not None:
            override_values["source_table_ddl"] = source_table_ddl_formatted

        with self._record_insert_lock, self._acquire_cross_process_record_lock(
            table_name=table_name,
            record_id=cloned_result_id,
        ):
            if self._record_id_exists(table_name=table_name, record_id=cloned_result_id):
                return {
                    "source_result_id": str(source_result_id),
                    "source_variant_table": str(source_variant_table),
                    "score": (
                        float(source_score)
                        if source_score is not None
                        else None
                    ),
                    "measurement_quality_flag": (
                        str(source_quality_flag).strip()
                        if source_quality_flag is not None
                        else None
                    ),
                    "cloned_result_id": cloned_result_id,
                    "status": "already_cloned",
                }

            select_expressions: list[str] = []
            query_params: Dict[str, Any] = {
                "source_result_id": str(source_result_id),
            }
            for column_index, column_name in enumerate(column_names):
                if column_name in override_values:
                    param_name = f"ov_{column_index}"
                    query_params[param_name] = override_values[column_name]
                    select_expressions.append(f"%({param_name})s")
                else:
                    select_expressions.append(f"src.`{column_name}`")

            self._execute(
                f"""
                INSERT INTO `{self._database}`.`{table_name}` ({", ".join(f"`{column}`" for column in column_names)})
                SELECT
                    {", ".join(select_expressions)}
                FROM `{self._database}`.`{table_name}` AS src
                WHERE src.id = %(source_result_id)s
                ORDER BY src.finished_at DESC, src.benchmark_started_at DESC, src.id DESC
                LIMIT 1
                """,
                query_params,
            )

        return {
            "source_result_id": str(source_result_id),
            "source_variant_table": str(source_variant_table),
            "score": float(source_score) if source_score is not None else None,
            "measurement_quality_flag": (
                str(source_quality_flag).strip()
                if source_quality_flag is not None
                else None
            ),
            "cloned_result_id": cloned_result_id,
            "status": "cloned",
        }

    def get_top_type_variants(
        self,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        top_n: int,
    ) -> List[TopTypeVariant]:
        """Возвращает top-N type-вариантов, отсортированных по score."""
        return self.get_top_variants_from_table(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            top_n=top_n,
            variant_modes=["types"],
            table_name=self._legacy_table,
        )

    def list_variant_summaries(
        self,
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        variant_modes: Optional[Sequence[str]] = None,
    ) -> List[StoredVariantSummary]:
        """Возвращает summary результатов вариантов с фильтрацией по mode."""
        return self._list_variant_summaries_from_table(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            variant_modes=variant_modes,
            table_name=self._phased_table,
        )

    def _list_variant_summaries_from_table(
        self,
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        variant_modes: Optional[Sequence[str]],
        table_name: str,
    ) -> List[StoredVariantSummary]:
        """Возвращает summary результатов вариантов с фильтрацией по mode для указанной таблицы."""
        rows = self._execute(
            f"""
            SELECT
                variant_table,
                tested_table_ddl,
                variant_mode,
                variant_params,
                score
            FROM `{self._database}`.`{table_name}`
            WHERE benchmark_run_id = %(benchmark_run_id)s
              AND benchmark_id = %(benchmark_id)s
              AND source_db_name = %(source_database)s
              AND source_table_name = %(source_table)s
            ORDER BY finished_at DESC, benchmark_started_at DESC, id DESC
            """,
            {
                "benchmark_run_id": benchmark_run_id,
                "benchmark_id": benchmark_id,
                "source_database": source_database,
                "source_table": source_table,
            },
        )

        mode_filter = {
            str(mode).strip()
            for mode in (variant_modes or [])
            if str(mode).strip()
        }
        summaries: list[StoredVariantSummary] = []
        seen_variant_uuid_keys: set[tuple[str, str]] = set()
        seen_variant_tables_without_uuid: set[str] = set()
        for row in rows:
            if len(row) == 5:
                (
                    variant_table,
                    tested_table_ddl,
                    variant_mode,
                    variant_params_raw,
                    score,
                ) = row
            elif len(row) == 3:
                # Backward-compatible path для тестовых/fake-store ответов.
                variant_table, tested_table_ddl, score = row
                variant_mode = "types"
                variant_params_raw = "{}"
            else:
                logger.warning(
                    "ClickHouseBenchmarkResultStore: неожиданная ширина row=%d в list_variant_summaries",
                    len(row),
                )
                continue
            mode_value = str(variant_mode or "")
            if mode_filter and mode_value not in mode_filter:
                continue

            variant_params: dict[str, Any] = {}
            if isinstance(variant_params_raw, str) and variant_params_raw.strip():
                try:
                    parsed_params = json.loads(variant_params_raw)
                    if isinstance(parsed_params, dict):
                        variant_params = parsed_params
                except Exception:
                    logger.warning(
                        "ClickHouseBenchmarkResultStore: не удалось распарсить variant_params JSON "
                        "(variant=%s, mode=%s)",
                        variant_table,
                        mode_value,
                    )

            normalized_variant_table = str(variant_table)
            execution_uuid = ""
            if isinstance(variant_params, dict):
                execution_uuid = str(variant_params.get("execution_uuid") or "").strip()
            if execution_uuid:
                dedupe_key = (normalized_variant_table, execution_uuid)
                if dedupe_key in seen_variant_uuid_keys:
                    continue
                seen_variant_uuid_keys.add(dedupe_key)
            else:
                if normalized_variant_table in seen_variant_tables_without_uuid:
                    continue
                seen_variant_tables_without_uuid.add(normalized_variant_table)

            summaries.append(
                StoredVariantSummary(
                    variant_table=normalized_variant_table,
                    tested_table_ddl=str(tested_table_ddl),
                    variant_mode=mode_value,
                    score=float(score) if score is not None else None,
                    variant_params=variant_params,
                )
            )
        return summaries

    def get_top_variants(
        self,
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        top_n: int,
        variant_modes: Sequence[str],
    ) -> List[TopTypeVariant]:
        """Возвращает top-N вариантов по score для указанных mode."""
        return self.get_top_variants_from_table(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            top_n=top_n,
            variant_modes=variant_modes,
            table_name=self._phased_table,
        )

    def get_top_variants_from_table(
        self,
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        top_n: int,
        variant_modes: Sequence[str],
        table_name: str,
    ) -> List[TopTypeVariant]:
        """Возвращает top-N вариантов по score из указанной таблицы."""
        if top_n <= 0:
            return []

        summaries = self._list_variant_summaries_from_table(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            variant_modes=variant_modes,
            table_name=table_name,
        )
        variant_mode_hint: Optional[str] = None
        for mode in variant_modes:
            normalized_mode = str(mode or "").strip()
            if normalized_mode:
                variant_mode_hint = normalized_mode
                break
        score_top_selection = self._resolve_score_top_selection(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            phase=None,
            variant_mode=variant_mode_hint,
            phase_name=variant_mode_hint,
        )
        prefer_higher_score = score_top_selection != "min"
        ranked = sorted(
            summaries,
            key=lambda summary: (
                summary.score is None,
                (
                    -(summary.score if summary.score is not None else 0.0)
                    if prefer_higher_score
                    else (summary.score if summary.score is not None else 0.0)
                ),
                summary.variant_table,
            ),
        )

        top_variants: list[TopTypeVariant] = []
        for summary in ranked[:top_n]:
            parsed_name = parse_variant_name(summary.variant_table)
            variant_index = parsed_name[2] if parsed_name else 0
            try:
                variant_ddl = TableDDL.from_ddl(summary.tested_table_ddl)
            except Exception:
                logger.exception(
                    "ClickHouseBenchmarkResultStore: не удалось распарсить tested_table_ddl "
                    "(benchmark=%s, table=%s, variant=%s)",
                    benchmark_id,
                    f"{source_database}.{source_table}",
                    summary.variant_table,
                )
                continue

            top_variants.append(
                TopTypeVariant(
                    variant_index=variant_index,
                    variant_ddl=variant_ddl,
                    score=summary.score,
                )
            )
        return top_variants

    @staticmethod
    def _is_missing_ch_object_error(exc: Exception) -> bool:
        """Возвращает True для ошибок отсутствующей таблицы/БД в ClickHouse."""
        message = str(exc).lower()
        return (
            "unknown_table" in message
            or "unknown table" in message
            or "unknown_database" in message
            or "unknown database" in message
            or "doesn't exist" in message
        )

    def _table_exists(self, table_name: str) -> bool:
        """Проверяет существование таблицы результатов."""
        try:
            rows = self._execute(f"EXISTS TABLE `{self._database}`.`{table_name}`")
        except Exception as exc:
            if self._is_missing_ch_object_error(exc):
                return False
            raise

        if not rows or not rows[0]:
            return False
        raw_value = rows[0][0]
        try:
            return bool(int(raw_value or 0))
        except Exception:
            return bool(raw_value)

    def _safe_max_benchmark_run_id_for_table(self, table_name: str) -> int:
        """
        Возвращает max(benchmark_run_id) для таблицы.

        Если таблица отсутствует (например, после ручной чистки БД), пытается
        восстановить схему через ensure_schema() и повторяет проверку.
        """
        if not self._table_exists(table_name):
            logger.warning(
                "ClickHouseBenchmarkResultStore: таблица `%s`.`%s` не найдена. "
                "Пробуем восстановить схему result-store.",
                self._database,
                table_name,
            )
            self.ensure_schema()
            if not self._table_exists(table_name):
                logger.warning(
                    "ClickHouseBenchmarkResultStore: таблица `%s`.`%s` всё ещё отсутствует. "
                    "Возвращаем max benchmark_run_id = 0.",
                    self._database,
                    table_name,
                )
                return 0

        try:
            rows = self._execute(
                f"SELECT max(benchmark_run_id) FROM `{self._database}`.`{table_name}`"
            )
        except Exception as exc:
            if self._is_missing_ch_object_error(exc):
                logger.warning(
                    "ClickHouseBenchmarkResultStore: таблица `%s`.`%s` исчезла во время чтения "
                    "max(benchmark_run_id). Возвращаем 0.",
                    self._database,
                    table_name,
                )
                return 0
            raise

        if not rows or rows[0][0] is None:
            return 0
        return int(rows[0][0])

    def max_benchmark_run_id(self) -> int:
        """Возвращает максимальный `benchmark_run_id` из таблиц результатов."""
        phased_max = self._safe_max_benchmark_run_id_for_table(self._phased_table)
        if self._legacy_table == self._phased_table or not self._create_legacy_table:
            return phased_max
        legacy_max = self._safe_max_benchmark_run_id_for_table(self._legacy_table)
        return max(phased_max, legacy_max)

    def _build_record(
        self,
        *,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        variant_table: str,
        variant_mode: str,
        variant_params: Dict[str, Any],
        tested_table_ddl_fallback: str,
        source_table_ddl_fallback: Optional[str],
        result: BenchmarkVariantResult,
    ) -> StoredBenchmarkResult:
        tested_table_ddl = self._resolve_tested_table_ddl(
            result_tested_table_ddl=result.tested_table_ddl,
            tested_table_ddl_fallback=tested_table_ddl_fallback,
            expected_variant_table=variant_table,
        )
        phase, resolved_phase_name = self._resolve_phase_metadata(variant_mode)
        if isinstance(variant_params, dict):
            phase_name_from_params = variant_params.get("phase_name")
            if phase_name_from_params is not None and str(phase_name_from_params).strip():
                resolved_phase_name = str(phase_name_from_params).strip()
        parent_variant_table = self._extract_parent_variant_table(variant_params)
        parent_id: Optional[str] = None
        if parent_variant_table:
            parent_id = self._resolve_parent_result_id(
                benchmark_run_id=benchmark_run_id,
                benchmark_id=benchmark_id,
                source_database=source_database,
                source_table=source_table,
                parent_variant_table=parent_variant_table,
            )

        tested_insert_metrics_json = (
            result.tested_table_insert_metrics_json
            or self._build_insert_metrics_json(
                time_ms_measurements=result.tested_table_insert_time_ms_measurements,
                time_ms_percentiles=result.tested_table_insert_time_ms_measurements_percentiles,
                time_ms_speedup_percentiles=(
                    result.tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs
                ),
                rows_per_second_measurements=(
                    result.tested_table_insert_rows_per_second_measurements
                ),
                rows_per_second_percentiles=(
                    result.tested_table_insert_rows_per_second_measurements_percentiles
                ),
                bytes_per_second_measurements=(
                    result.tested_table_insert_bytes_per_second_measurements
                ),
                bytes_per_second_measurements_readable=(
                    result.tested_table_insert_bytes_per_second_measurements_readable
                ),
                bytes_per_second_percentiles=(
                    result.tested_table_insert_bytes_per_second_measurements_percentiles
                ),
                bytes_per_second_percentiles_readable=(
                    result.tested_table_insert_bytes_per_second_measurements_percentiles_readable
                ),
            )
        )
        source_insert_metrics_json = (
            result.source_table_insert_metrics_json
            or self._build_insert_metrics_json(
                time_ms_measurements=result.source_table_insert_time_ms_measurements,
                time_ms_percentiles=result.source_table_insert_time_ms_measurements_percentiles,
                time_ms_speedup_percentiles=[],
                rows_per_second_measurements=(
                    result.source_table_insert_rows_per_second_measurements
                ),
                rows_per_second_percentiles=(
                    result.source_table_insert_rows_per_second_measurements_percentiles
                ),
                bytes_per_second_measurements=(
                    result.source_table_insert_bytes_per_second_measurements
                ),
                bytes_per_second_measurements_readable=(
                    result.source_table_insert_bytes_per_second_measurements_readable
                ),
                bytes_per_second_percentiles=(
                    result.source_table_insert_bytes_per_second_measurements_percentiles
                ),
                bytes_per_second_percentiles_readable=(
                    result.source_table_insert_bytes_per_second_measurements_percentiles_readable
                ),
            )
        )
        tested_select_metrics_json = self._to_query_keyed_json_map(
            result.tested_table_select_metrics_by_query_json
        )
        source_select_metrics_json = self._to_query_keyed_json_map(
            result.source_table_select_metrics_by_query_json
        )
        tested_select_speedup_by_query_json = self._to_query_keyed_json_map(
            result.tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json
        )
        tested_select_read_bytes_speedup_by_query_json = self._to_query_keyed_json_map(
            result.tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json
        )
        if tested_select_read_bytes_speedup_by_query_json is None:
            tested_select_read_bytes_speedup_by_query_json = (
                self._extract_read_bytes_speedup_query_map_json(
                    tested_select_speedup_by_query_json
                )
            )
        size_bytes_total = (
            result.tested_table_consumed_compressed_size_bytes_with_indexes
            if result.tested_table_consumed_compressed_size_bytes_with_indexes is not None
            else result.tested_table_consumed_compressed_size_bytes_overall
        )
        size_bytes_by_column_json = (
            result.tested_table_consumed_compressed_size_bytes_by_each_column
            or result.tested_table_cols_sizes
        )
        source_size_bytes_overall = result.source_table_consumed_compressed_size_bytes_overall
        if source_size_bytes_overall is None:
            source_size_bytes_overall = self._extract_size_bytes_from_value_json(
                result.source_table_consumed_compressed_size_bytes_overall_json
            )
        size_bytes_indexes_json = self._build_size_bytes_indexes_json(
            tested_table_indexes_sizes=result.tested_table_indexes_sizes,
            source_table_size_bytes_overall=source_size_bytes_overall,
        )
        tested_table_size_with_indexes_json = self._build_size_bytes_value_json(
            size_bytes=result.tested_table_consumed_compressed_size_bytes_with_indexes,
            size_bytes_readable=result.tested_table_consumed_compressed_size_bytes_with_indexes_readable,
            fallback_json=result.tested_table_consumed_compressed_size_bytes_with_indexes_json,
        )
        source_table_size_overall_json = self._build_size_bytes_value_json(
            size_bytes=source_size_bytes_overall,
            size_bytes_readable=result.source_table_consumed_compressed_size_bytes_overall_readable,
            fallback_json=result.source_table_consumed_compressed_size_bytes_overall_json,
        )
        execution_uuid = ""
        if isinstance(variant_params, dict):
            execution_uuid = str(variant_params.get("execution_uuid") or "").strip()
        celery_task_id = str(result.celery_task_id or "").strip()
        if not celery_task_id and isinstance(variant_params, dict):
            celery_task_id = str(variant_params.get("celery_task_id") or "").strip()
        celery_worker_hostname = str(result.celery_worker_hostname or "").strip()
        if not celery_worker_hostname and isinstance(variant_params, dict):
            celery_worker_hostname = str(
                variant_params.get("celery_worker_hostname") or ""
            ).strip()
        result_token = (
            execution_uuid
            or str(result.id or "").strip()
            or str(variant_table or "").strip()
            or str(uuid4())
        )
        result_id = self._build_scoped_result_id(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            variant_table=variant_table,
            raw_result_token=result_token,
        )
        started_at = self._to_aware_storage_datetime(
            result.worker_started_at or benchmark_started_at
        )
        finished_at = self._to_aware_storage_datetime(
            result.worker_finished_at or datetime.now(_RESULTS_TZ)
        )
        variant_mode_id = self._resolve_variant_mode_id(
            variant_table=variant_table,
            variant_params=variant_params,
        )

        return StoredBenchmarkResult(
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
            benchmark_id=benchmark_id,
            id=result_id,
            parent_id=parent_id,
            phase=phase,
            phase_name=resolved_phase_name,
            celery_task_id=celery_task_id or None,
            celery_worker_hostname=celery_worker_hostname or None,
            started_at=started_at,
            finished_at=finished_at,
            source_db_name=source_database,
            source_table_name=source_table,
            tested_table_ddl=tested_table_ddl,
            variant_params_json=json.dumps(
                variant_params,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            ),
            source_table_ddl=result.source_table_ddl or source_table_ddl_fallback,
            is_source_table_copy=result.is_source_table_copy,
            index_params=result.index_params,
            total_n_rows_in_tested_table=result.total_n_rows_in_tested_table,
            total_n_rows_in_source_table=result.total_n_rows_in_source_table,
            measured_percentiles=list(result.measured_percentiles),
            insert_test_n_rows=result.insert_test_n_rows,
            tested_table_insert_time_ms_measurements=list(
                result.tested_table_insert_time_ms_measurements
            ),
            source_table_insert_time_ms_measurements=list(
                result.source_table_insert_time_ms_measurements
            ),
            tested_table_insert_time_ms_measurements_percentiles=list(
                result.tested_table_insert_time_ms_measurements_percentiles
            ),
            source_table_insert_time_ms_measurements_percentiles=list(
                result.source_table_insert_time_ms_measurements_percentiles
            ),
            tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs=list(
                result.tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs
            ),
            tested_table_insert_rows_per_second_measurements=list(
                result.tested_table_insert_rows_per_second_measurements
            ),
            source_table_insert_rows_per_second_measurements=list(
                result.source_table_insert_rows_per_second_measurements
            ),
            tested_table_insert_rows_per_second_measurements_percentiles=list(
                result.tested_table_insert_rows_per_second_measurements_percentiles
            ),
            source_table_insert_rows_per_second_measurements_percentiles=list(
                result.source_table_insert_rows_per_second_measurements_percentiles
            ),
            tested_table_insert_bytes_per_second_measurements=list(
                result.tested_table_insert_bytes_per_second_measurements
            ),
            tested_table_insert_bytes_per_second_measurements_readable=list(
                result.tested_table_insert_bytes_per_second_measurements_readable
            ),
            source_table_insert_bytes_per_second_measurements=list(
                result.source_table_insert_bytes_per_second_measurements
            ),
            source_table_insert_bytes_per_second_measurements_readable=list(
                result.source_table_insert_bytes_per_second_measurements_readable
            ),
            tested_table_insert_bytes_per_second_measurements_percentiles=list(
                result.tested_table_insert_bytes_per_second_measurements_percentiles
            ),
            tested_table_insert_bytes_per_second_measurements_percentiles_readable=list(
                result.tested_table_insert_bytes_per_second_measurements_percentiles_readable
            ),
            source_table_insert_bytes_per_second_measurements_percentiles=list(
                result.source_table_insert_bytes_per_second_measurements_percentiles
            ),
            source_table_insert_bytes_per_second_measurements_percentiles_readable=list(
                result.source_table_insert_bytes_per_second_measurements_percentiles_readable
            ),
            tested_table_insert_metrics_json=tested_insert_metrics_json,
            source_table_insert_metrics_json=source_insert_metrics_json,
            insert_metrics_json=tested_insert_metrics_json,
            tested_table_select_test_query=result.tested_table_select_test_query,
            source_table_select_test_query=result.source_table_select_test_query,
            select_metrics_json=tested_select_metrics_json,
            tested_table_select_metrics_by_query_json=tested_select_metrics_json,
            source_table_select_metrics_by_query_json=source_select_metrics_json,
            tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json=(
                tested_select_speedup_by_query_json
            ),
            tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json=(
                tested_select_read_bytes_speedup_by_query_json
            ),
            tested_table_select_time_ms_percentiles_speed_up_coefs_vs_source_by_query_json=(
                tested_select_speedup_by_query_json
            ),
            tested_table_consumed_compressed_size_bytes_by_each_column=(
                result.tested_table_consumed_compressed_size_bytes_by_each_column
            ),
            source_table_consumed_compressed_size_bytes_by_each_column=(
                result.source_table_consumed_compressed_size_bytes_by_each_column
            ),
            tested_table_consumed_compressed_size_bytes_overall=(
                result.tested_table_consumed_compressed_size_bytes_overall
            ),
            tested_table_consumed_compressed_size_bytes_overall_readable=(
                result.tested_table_consumed_compressed_size_bytes_overall_readable
            ),
            tested_table_consumed_compressed_size_bytes_with_indexes=(
                result.tested_table_consumed_compressed_size_bytes_with_indexes
            ),
            tested_table_consumed_compressed_size_bytes_with_indexes_readable=(
                result.tested_table_consumed_compressed_size_bytes_with_indexes_readable
            ),
            tested_table_consumed_compressed_size_bytes_with_indexes_json=(
                tested_table_size_with_indexes_json
            ),
            tested_table_primary_index_size_json=(
                result.tested_table_primary_index_size_json
            ),
            source_table_consumed_compressed_size_bytes_overall=(
                source_size_bytes_overall
            ),
            source_table_consumed_compressed_size_bytes_overall_readable=(
                result.source_table_consumed_compressed_size_bytes_overall_readable
            ),
            source_table_consumed_compressed_size_bytes_overall_json=(
                source_table_size_overall_json
            ),
            tested_table_compression_overall_coef=result.tested_table_compression_overall_coef,
            tested_table_compression_by_each_column_coef=(
                result.tested_table_compression_by_each_column_coef
            ),
            source_table_n_rows_in_size_test=result.source_table_n_rows_in_size_test,
            tested_table_n_rows_in_size_test=result.tested_table_n_rows_in_size_test,
            size_bytes_total=size_bytes_total,
            size_bytes_by_column_json=size_bytes_by_column_json,
            size_bytes_indexes_json=size_bytes_indexes_json,
            tested_table_cols_sizes=result.tested_table_cols_sizes,
            tested_table_indexes_sizes=result.tested_table_indexes_sizes,
            extra_json=result.extra_json,
            variant_table=variant_table,
            variant_mode=variant_mode,
            variant_mode_id=variant_mode_id,
            variant_params=variant_params,
            rank_in_phase=None,
            is_top_n=False,
            measurement_quality_flag=result.measurement_quality_flag,
            measurement_quality_details_json=result.measurement_quality_details_json,
            score_calculation_json=result.score_calculation_json,
            score=result.score,
        )

    @classmethod
    def _extract_table_name_from_ddl(cls, ddl_text: str) -> Optional[str]:
        """Извлекает имя таблицы из CREATE TABLE DDL."""
        cleaned = str(ddl_text or "").strip()
        if not cleaned:
            return None
        try:
            parsed = TableDDL.from_ddl(cleaned)
        except Exception:
            return None
        raw_name = str(parsed.name or "").strip().replace("`", "")
        if not raw_name:
            return None
        if "." in raw_name:
            return raw_name.rsplit(".", 1)[-1].strip() or None
        return raw_name

    @classmethod
    def _resolve_tested_table_ddl(
        cls,
        *,
        result_tested_table_ddl: Optional[str],
        tested_table_ddl_fallback: str,
        expected_variant_table: str,
    ) -> str:
        """
        Возвращает корректный tested_table_ddl для записи результата.

        Если воркер вернул DDL с именем таблицы, не совпадающим с `variant_table`,
        используем fallback из payload job, чтобы избежать склейки таблиц между
        разными source-планами.
        """
        fallback_ddl = str(tested_table_ddl_fallback or "").strip()
        candidate_ddl = str(result_tested_table_ddl or "").strip()
        if not candidate_ddl:
            return fallback_ddl

        expected_table = str(expected_variant_table or "").strip().replace("`", "")
        candidate_table = cls._extract_table_name_from_ddl(candidate_ddl)
        if candidate_table and expected_table and candidate_table != expected_table:
            logger.warning(
                "ClickHouseBenchmarkResultStore: mismatch tested_table_ddl/table "
                "(expected=%s, got=%s). Using fallback DDL.",
                expected_table,
                candidate_table,
            )
            if fallback_ddl:
                return fallback_ddl
        return candidate_ddl

    @classmethod
    def _to_query_keyed_json_map(cls, value: Optional[str]) -> Optional[str]:
        """
        Преобразует per-query JSON в map-формат `query_id -> metrics`.

        Поддерживает вход как list[dict] (runtime-формат) и dict.
        """
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        if not value.strip():
            return value

        try:
            parsed = json.loads(value)
        except Exception:
            return value

        if isinstance(parsed, dict):
            return json.dumps(
                parsed,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            )

        if not isinstance(parsed, list):
            return value

        query_map: dict[str, Dict[str, Any]] = {}
        for fallback_index, entry in enumerate(parsed):
            if not isinstance(entry, dict):
                continue
            query_index = cls._safe_int(entry.get("query_index"), default=fallback_index)
            query_id = cls._safe_str(
                entry.get("query_id"),
                default=f"query_{query_index}",
            )
            key = query_id
            if key in query_map:
                suffix = 1
                while f"{query_id}_{suffix}" in query_map:
                    suffix += 1
                key = f"{query_id}_{suffix}"
            query_map[key] = entry

        return json.dumps(
            query_map,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )

    @classmethod
    def _extract_read_bytes_speedup_query_map_json(cls, value: Optional[str]) -> Optional[str]:
        """
        Извлекает из map/list per-query speedup только `read_bytes_*` коэффициенты.
        """
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        if not value.strip():
            return value
        try:
            parsed = json.loads(value)
        except Exception:
            return None

        if isinstance(parsed, list):
            map_json = cls._to_query_keyed_json_map(value)
            if not isinstance(map_json, str):
                return None
            try:
                parsed = json.loads(map_json)
            except Exception:
                return None

        if not isinstance(parsed, dict):
            return None

        read_bytes_map: dict[str, Dict[str, Any]] = {}
        for query_id, payload in parsed.items():
            if not isinstance(payload, dict):
                continue
            read_bytes_speedup = payload.get("read_bytes_percentiles_speed_up_coefs")
            if not isinstance(read_bytes_speedup, list):
                read_bytes_speedup = []
            query_index = cls._safe_int(payload.get("query_index"), default=0)
            query = payload.get("query")
            source_query = payload.get("source_query")
            read_bytes_map[str(query_id)] = {
                "query_index": query_index,
                "query_id": str(query_id),
                "query": query,
                "source_query": source_query,
                "read_bytes_percentiles_speed_up_coefs": read_bytes_speedup,
            }
        if not read_bytes_map:
            return None
        return json.dumps(
            read_bytes_map,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )

    @classmethod
    def _build_size_bytes_indexes_json(
        cls,
        *,
        tested_table_indexes_sizes: Optional[str],
        source_table_size_bytes_overall: Optional[float],
    ) -> Optional[str]:
        """
        Строит JSON размеров skip-индексов для `size_bytes_indexes_json`.

        Добавляет только в этот JSON поле
        `data_skipping_index_size_percent_from_source_table`,
        рассчитанное как `index_size_bytes / source_table_size_bytes_overall * 100`.
        """
        if tested_table_indexes_sizes is None:
            return None
        if not isinstance(tested_table_indexes_sizes, str):
            return tested_table_indexes_sizes
        if not tested_table_indexes_sizes.strip():
            return tested_table_indexes_sizes

        try:
            parsed = json.loads(tested_table_indexes_sizes)
        except Exception:
            return tested_table_indexes_sizes
        if not isinstance(parsed, dict):
            return tested_table_indexes_sizes

        try:
            source_size_bytes = float(source_table_size_bytes_overall or 0.0)
        except Exception:
            source_size_bytes = 0.0
        if source_size_bytes <= 0:
            return tested_table_indexes_sizes

        for _, index_stats in parsed.items():
            if not isinstance(index_stats, dict):
                continue
            try:
                index_size_bytes = float(index_stats.get("size_compressed_bytes", 0.0) or 0.0)
            except Exception:
                index_size_bytes = 0.0
            if index_size_bytes <= 0:
                continue
            index_stats["data_skipping_index_size_percent_from_source_table"] = round(
                (index_size_bytes / source_size_bytes) * 100.0,
                6,
            )

        return json.dumps(
            parsed,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

    @classmethod
    def _extract_size_bytes_from_value_json(cls, value: Any) -> Optional[float]:
        """Достаёт `size_bytes` из JSON-колонки вида `{\"size_bytes\": ..., ...}`."""
        if value is None:
            return None
        parsed: Any = value
        if isinstance(value, str):
            if not value.strip():
                return None
            try:
                parsed = json.loads(value)
            except Exception:
                return None
        if not isinstance(parsed, dict):
            return None
        try:
            return float(parsed.get("size_bytes"))
        except Exception:
            return None

    @classmethod
    def _build_size_bytes_value_json(
        cls,
        *,
        size_bytes: Optional[float],
        size_bytes_readable: Optional[str],
        fallback_json: Optional[str] = None,
    ) -> Optional[str]:
        """
        Строит JSON размера в формате:
        `{\"size_bytes\": <float>, \"size_bytes_readable\": <str>}`.
        """
        fallback_payload: Optional[Dict[str, Any]] = None
        if isinstance(fallback_json, str) and fallback_json.strip():
            try:
                parsed_fallback = json.loads(fallback_json)
            except Exception:
                parsed_fallback = None
            if isinstance(parsed_fallback, dict):
                fallback_payload = dict(parsed_fallback)

        try:
            numeric_size = float(size_bytes) if size_bytes is not None else None
        except Exception:
            numeric_size = None

        if numeric_size is None and isinstance(fallback_json, str) and fallback_json.strip():
            return fallback_json
        if numeric_size is None:
            return None

        readable_value = str(size_bytes_readable or "").strip() or make_readable_bytes(numeric_size)
        payload: Dict[str, Any] = {
            "size_bytes": numeric_size,
            "size_bytes_readable": readable_value,
        }
        if fallback_payload:
            # Сохраняем дополнительные поля из fallback JSON
            # (например, bytes_on_disk_sum), но не перезаписываем base-ключи.
            for key, value in fallback_payload.items():
                if key in {"size_bytes", "size_bytes_readable"}:
                    continue
                payload[key] = value
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

    @classmethod
    def _build_insert_metrics_json(
        cls,
        *,
        time_ms_measurements: List[float],
        time_ms_percentiles: List[float],
        time_ms_speedup_percentiles: List[float],
        rows_per_second_measurements: List[float],
        rows_per_second_percentiles: List[float],
        bytes_per_second_measurements: List[float],
        bytes_per_second_measurements_readable: List[str],
        bytes_per_second_percentiles: List[float],
        bytes_per_second_percentiles_readable: List[str],
    ) -> Optional[str]:
        """Собирает компактный JSON-снимок insert-метрик."""
        payload = {
            "insert_main": {
                "time_ms_measurements": list(time_ms_measurements),
                "time_ms_percentiles": list(time_ms_percentiles),
                "time_ms_percentiles_speed_up_coefs": list(time_ms_speedup_percentiles),
                "rows_per_second_measurements": list(rows_per_second_measurements),
                "rows_per_second_percentiles": list(rows_per_second_percentiles),
                "bytes_per_second_measurements": list(bytes_per_second_measurements),
                "bytes_per_second_measurements_readable": list(
                    bytes_per_second_measurements_readable
                ),
                "bytes_per_second_percentiles": list(bytes_per_second_percentiles),
                "bytes_per_second_percentiles_readable": list(
                    bytes_per_second_percentiles_readable
                ),
            }
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )

    @staticmethod
    def _safe_int(value: Any, *, default: int) -> int:
        """Безопасно приводит значение к int с fallback."""
        try:
            return int(value)
        except Exception:
            return int(default)

    @staticmethod
    def _parse_json_dict_or_empty(raw_value: Any) -> Dict[str, Any]:
        """Парсит JSON-словарь из строки/объекта, иначе возвращает пустой dict."""
        if isinstance(raw_value, dict):
            return dict(raw_value)
        if not isinstance(raw_value, str):
            return {}
        if not raw_value.strip():
            return {}
        try:
            parsed = json.loads(raw_value)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return parsed
        return {}

    @staticmethod
    def _safe_str(value: Any, *, default: str) -> str:
        """Безопасно приводит значение к непустой строке с fallback."""
        if value is None:
            return default
        normalized = str(value).strip()
        if not normalized:
            return default
        return normalized

    @classmethod
    def _ddl_signature(cls, ddl_text: str) -> str:
        """
        Строит стабильную сигнатуру DDL без учёта имени таблицы.

        Нужна для дедупликации вариантов, у которых структура совпадает, но
        `CREATE TABLE` содержит разное временное имя (`variant_table`).
        """
        cleaned = str(ddl_text or "").strip()
        if not cleaned:
            return ""
        normalized = cleaned
        try:
            parsed = TableDDL.from_ddl(cleaned)
            parsed.name = "__dedupe__.__signature__"
            normalized = parsed.to_ddl()
        except Exception:
            # Fallback: если парсер DDL не справился, сравниваем по whitespace-normalized SQL.
            normalized = re.sub(r"\s+", " ", cleaned).strip()
        return sha256(normalized.encode("utf-8")).hexdigest()

    @classmethod
    def _resolve_phase_metadata(cls, variant_mode: str) -> tuple[Optional[int], Optional[str]]:
        """Определяет phase/phase_name по `variant_mode`."""
        normalized_mode = str(variant_mode or "").strip()
        if not normalized_mode:
            return None, None
        phase = cls._PHASE_BY_VARIANT_MODE.get(normalized_mode)
        phase_name = cls._PHASE_NAME_BY_VARIANT_MODE.get(normalized_mode, normalized_mode)
        return phase, phase_name

    @staticmethod
    def _extract_parent_variant_table(variant_params: Dict[str, Any]) -> Optional[str]:
        """Пытается извлечь parent variant table из `variant_params`."""
        if not isinstance(variant_params, dict):
            return None
        for key in ("parent_variant_table", "parent_variant", "parent_table"):
            value = variant_params.get(key)
            if value is None:
                continue
            normalized = str(value).strip()
            if normalized:
                return normalized
        return None

    @staticmethod
    def _resolve_variant_mode_id(
        *,
        variant_table: str,
        variant_params: Dict[str, Any],
    ) -> Optional[int]:
        """
        Возвращает числовой последовательный id варианта для сортировки.

        Приоритет:
          1) индекс из `variant_table` (паттерн `...__bench__...__0007`);
          2) `variant_params.global_index` (если присутствует);
          3) `None`.
        """
        parsed = parse_variant_name(str(variant_table or ""))
        if parsed is not None:
            try:
                return int(parsed[2])
            except Exception:
                pass

        if isinstance(variant_params, dict):
            raw_global_index = variant_params.get("global_index")
            if raw_global_index is not None:
                try:
                    return int(raw_global_index)
                except Exception:
                    pass
        return None

    def _resolve_parent_result_id(
        self,
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        parent_variant_table: str,
    ) -> Optional[str]:
        """Ищет `id` parent-результата по `parent_variant_table` в рамках того же run/table."""
        rows = self._execute(
            f"""
            SELECT id
            FROM `{self._database}`.`{self._table}`
            WHERE benchmark_run_id = %(benchmark_run_id)s
              AND benchmark_id = %(benchmark_id)s
              AND source_db_name = %(source_database)s
              AND source_table_name = %(source_table)s
              AND variant_table = %(parent_variant_table)s
            ORDER BY finished_at DESC, benchmark_started_at DESC, id DESC
            LIMIT 1
            """,
            {
                "benchmark_run_id": benchmark_run_id,
                "benchmark_id": benchmark_id,
                "source_database": source_database,
                "source_table": source_table,
                "parent_variant_table": parent_variant_table,
            },
        )
        if not rows:
            return None
        value = rows[0][0]
        return str(value) if value is not None else None

    def _resolve_top_n_winners(
        self,
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        phase: Optional[int] = None,
        variant_mode: Optional[str] = None,
        phase_name: Optional[str] = None,
    ) -> int:
        """Возвращает top-N победителей для указанной фазы (fallback=1)."""
        rows = self._execute(
            f"""
            SELECT top_n_winners, sequential_top_n_limits_json
            FROM `{self._database}`.`{self._phased_runs_table}`
            WHERE benchmark_run_id = %(benchmark_run_id)s
              AND benchmark_id = %(benchmark_id)s
              AND source_db_name = %(source_database)s
              AND source_table_name = %(source_table)s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            {
                "benchmark_run_id": benchmark_run_id,
                "benchmark_id": benchmark_id,
                "source_database": source_database,
                "source_table": source_table,
            },
        )
        if not rows:
            return 1
        top_n_winners_raw = rows[0][0]
        limits_json_raw = rows[0][1] if len(rows[0]) > 1 else None
        default_top_n = 1
        try:
            if top_n_winners_raw is not None:
                default_top_n = max(1, int(top_n_winners_raw))
        except Exception:
            default_top_n = 1

        if not isinstance(limits_json_raw, str) or not limits_json_raw.strip():
            return default_top_n
        try:
            parsed_limits = json.loads(limits_json_raw)
        except Exception:
            return default_top_n
        if not isinstance(parsed_limits, dict):
            return default_top_n

        raw_limits = parsed_limits.get("sequential_top_n_limits", parsed_limits)
        if not isinstance(raw_limits, dict):
            return default_top_n

        resolved_keys = self._resolve_stage_keys_for_scope(
            phase=phase,
            variant_mode=variant_mode,
            phase_name=phase_name,
        )

        for key in resolved_keys:
            value = raw_limits.get(key)
            if value is None:
                continue
            try:
                return max(1, int(value))
            except Exception:
                continue

        sequential_value = raw_limits.get("sequential")
        if sequential_value is not None:
            try:
                return max(1, int(sequential_value))
            except Exception:
                pass
        return default_top_n

    @staticmethod
    def _normalize_stage_key(value: Optional[str]) -> Optional[str]:
        """Нормализует ключ стадии для map-lookup."""
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if not normalized:
            return None
        normalized = re.sub(r"\s+", "_", normalized)
        normalized = normalized.replace("-", "_")
        if normalized == "order by":
            return "order_by"
        return normalized

    @classmethod
    def _resolve_stage_keys_for_scope(
        cls,
        *,
        phase: Optional[int],
        variant_mode: Optional[str],
        phase_name: Optional[str],
    ) -> list[str]:
        """Возвращает список ключей стадии для scope в порядке приоритета."""
        stage_keys: list[str] = []
        mode_key = cls._normalize_stage_key(variant_mode)
        if mode_key is not None:
            stage_keys.append(mode_key)
            if mode_key.endswith("_validation"):
                stage_keys.append(mode_key[: -len("_validation")])
        phase_name_key = cls._normalize_stage_key(phase_name)
        if phase_name_key is not None:
            stage_keys.append(phase_name_key)
            if phase_name_key.endswith("_validation"):
                stage_keys.append(phase_name_key[: -len("_validation")])
        if phase is not None:
            phase_key_by_number = {
                1: "order_by",
                2: "types",
                3: "codecs",
                4: "index_granularity",
                5: "indexes",
                6: "final_validation",
            }
            phase_key = phase_key_by_number.get(int(phase))
            if phase_key is not None:
                stage_keys.append(phase_key)

        resolved_keys: list[str] = []
        seen_keys: set[str] = set()
        for key in stage_keys:
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            resolved_keys.append(key)
        return resolved_keys

    def _resolve_score_top_selection(
        self,
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        phase: Optional[int] = None,
        variant_mode: Optional[str] = None,
        phase_name: Optional[str] = None,
    ) -> str:
        """Возвращает направление top-selection: `max` или `min` (fallback=`max`)."""
        rows = self._execute(
            f"""
            SELECT sequential_top_n_limits_json
            FROM `{self._database}`.`{self._phased_runs_table}`
            WHERE benchmark_run_id = %(benchmark_run_id)s
              AND benchmark_id = %(benchmark_id)s
              AND source_db_name = %(source_database)s
              AND source_table_name = %(source_table)s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            {
                "benchmark_run_id": benchmark_run_id,
                "benchmark_id": benchmark_id,
                "source_database": source_database,
                "source_table": source_table,
            },
        )
        if not rows:
            return "max"
        limits_json_raw = rows[0][0] if rows[0] else None
        if not isinstance(limits_json_raw, str) or not limits_json_raw.strip():
            return "max"
        try:
            parsed_limits = json.loads(limits_json_raw)
        except Exception:
            return "max"
        if not isinstance(parsed_limits, dict):
            return "max"

        selection_by_stage = parsed_limits.get("score_top_selection_by_stage")
        if isinstance(selection_by_stage, dict):
            for stage_key in self._resolve_stage_keys_for_scope(
                phase=phase,
                variant_mode=variant_mode,
                phase_name=phase_name,
            ):
                raw = selection_by_stage.get(stage_key)
                normalized = str(raw or "").strip().lower()
                if normalized in {"max", "min"}:
                    return normalized

        raw_global_selection = parsed_limits.get("score_top_selection")
        normalized_global_selection = str(raw_global_selection or "").strip().lower()
        if normalized_global_selection in {"max", "min"}:
            return normalized_global_selection
        return "max"

    def _recalculate_phase_ranking(
        self,
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        phase: Optional[int],
        variant_mode: Optional[str] = None,
        phase_name: Optional[str] = None,
    ) -> None:
        """Пересчитывает `rank_in_phase`/`is_top_n` для выбранной phase."""
        if phase is None and not variant_mode and not phase_name:
            return
        scope_where_clause, scope_params = self._build_phase_scope_clause(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            phase=phase,
            variant_mode=variant_mode,
            phase_name=phase_name,
        )

        rows = self._execute(
            f"""
            SELECT id, score
            FROM `{self._database}`.`{self._table}`
            WHERE {scope_where_clause}
            """,
            scope_params,
        )
        if not rows:
            return

        top_n_winners = self._resolve_top_n_winners(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            phase=phase,
            variant_mode=variant_mode,
            phase_name=phase_name,
        )
        score_top_selection = self._resolve_score_top_selection(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            phase=phase,
            variant_mode=variant_mode,
            phase_name=phase_name,
        )
        prefer_higher_score = score_top_selection != "min"
        ranked_rows = sorted(
            rows,
            key=lambda row: (
                row[1] is None,
                (
                    -(float(row[1]) if row[1] is not None else 0.0)
                    if prefer_higher_score
                    else (float(row[1]) if row[1] is not None else 0.0)
                ),
                str(row[0]),
            ),
        )
        for rank_index, (row_id, _) in enumerate(ranked_rows, start=1):
            self._execute(
                f"""
                ALTER TABLE `{self._database}`.`{self._table}`
                UPDATE
                    rank_in_phase = %(rank_in_phase)s,
                    is_top_n = %(is_top_n)s
                WHERE {scope_where_clause}
                  AND id = %(id)s
                SETTINGS mutations_sync = 1
                """,
                {
                    **scope_params,
                    "rank_in_phase": rank_index,
                    "is_top_n": rank_index <= top_n_winners,
                    "id": str(row_id),
                },
            )
        self._recalculate_stage_column_ranking(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            phase=phase,
            variant_mode=variant_mode,
            phase_name=phase_name,
            top_n_winners=top_n_winners,
        )

    def _recalculate_stage_column_ranking(
        self,
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        phase: Optional[int],
        variant_mode: Optional[str],
        phase_name: Optional[str],
        top_n_winners: int,
    ) -> None:
        """
        Пересчитывает rank/top-N внутри stage-колонки (`stage_column_name`) в phase-scope.

        Источник stage-колонки — `variant_params.stage_column_name`.
        Для фаз без `stage_column_name` поля остаются пустыми/false.
        """
        if phase is None and not variant_mode and not phase_name:
            return
        scope_where_clause, scope_params = self._build_phase_scope_clause(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            phase=phase,
            variant_mode=variant_mode,
            phase_name=phase_name,
        )
        rows = self._execute(
            f"""
            SELECT
                id,
                score,
                JSONExtractString(variant_params, 'stage_column_name') AS stage_column_name
            FROM `{self._database}`.`{self._table}`
            WHERE {scope_where_clause}
            """,
            scope_params,
        )
        if not rows:
            return

        rows_by_stage_column: Dict[str, List[tuple[str, Optional[float]]]] = {}
        for row in rows:
            if not row:
                continue
            row_id = str(row[0] or "")
            if not row_id:
                continue
            score_value = row[1] if len(row) > 1 else None
            stage_column_raw = row[2] if len(row) > 2 else None
            stage_column_name = str(stage_column_raw or "").strip()
            if not stage_column_name:
                continue
            rows_by_stage_column.setdefault(stage_column_name, []).append((row_id, score_value))

        if not rows_by_stage_column:
            return

        self._execute(
            f"""
            ALTER TABLE `{self._database}`.`{self._table}`
            UPDATE
                rank_in_stage_column = NULL,
                is_top_n_in_stage_column = 0
            WHERE {scope_where_clause}
            SETTINGS mutations_sync = 1
            """,
            scope_params,
        )

        stage_top_n = max(1, int(top_n_winners))
        score_top_selection = self._resolve_score_top_selection(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            phase=phase,
            variant_mode=variant_mode,
            phase_name=phase_name,
        )
        prefer_higher_score = score_top_selection != "min"
        for ranked_rows in rows_by_stage_column.values():
            ranked_rows_sorted = sorted(
                ranked_rows,
                key=lambda item: (
                    item[1] is None,
                    (
                        -(float(item[1]) if item[1] is not None else 0.0)
                        if prefer_higher_score
                        else (float(item[1]) if item[1] is not None else 0.0)
                    ),
                    item[0],
                ),
            )
            for rank_index, (row_id, _) in enumerate(ranked_rows_sorted, start=1):
                self._execute(
                    f"""
                    ALTER TABLE `{self._database}`.`{self._table}`
                    UPDATE
                        rank_in_stage_column = %(rank_in_stage_column)s,
                        is_top_n_in_stage_column = %(is_top_n_in_stage_column)s
                    WHERE {scope_where_clause}
                      AND id = %(id)s
                    SETTINGS mutations_sync = 1
                    """,
                    {
                        **scope_params,
                        "rank_in_stage_column": rank_index,
                        "is_top_n_in_stage_column": rank_index <= stage_top_n,
                        "id": row_id,
                    },
                )

    @staticmethod
    def _build_phase_scope_clause(
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        phase: Optional[int],
        variant_mode: Optional[str],
        phase_name: Optional[str],
    ) -> tuple[str, Dict[str, Any]]:
        """Строит WHERE-клаузу и параметры для stage-scope операций по `variant_mode`."""
        scope_conditions = [
            "benchmark_run_id = %(benchmark_run_id)s",
            "benchmark_id = %(benchmark_id)s",
            "source_db_name = %(source_database)s",
            "source_table_name = %(source_table)s",
        ]
        scope_params: Dict[str, Any] = {
            "benchmark_run_id": benchmark_run_id,
            "benchmark_id": benchmark_id,
            "source_database": source_database,
            "source_table": source_table,
        }
        resolved_mode: Optional[str] = None
        if variant_mode is not None and str(variant_mode).strip():
            resolved_mode = str(variant_mode).strip()
        elif phase_name is not None and str(phase_name).strip():
            resolved_mode = str(phase_name).strip()
        elif phase is not None:
            phase_to_mode = {
                0: "source_baseline",
                1: "order_by",
                2: "types",
                3: "codecs",
                4: "index_granularity",
                5: "indexes",
                6: "final_validation",
            }
            resolved_mode = phase_to_mode.get(int(phase))

        if resolved_mode is not None:
            scope_conditions.append("variant_mode = %(variant_mode)s")
            scope_params["variant_mode"] = resolved_mode
        return " AND\n              ".join(scope_conditions), scope_params

    def recalculate_phase_ranking(
        self,
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        phase: Optional[int] = None,
        variant_mode: Optional[str] = None,
        phase_name: Optional[str] = None,
    ) -> None:
        """Явно пересчитывает rank/top-N для указанного phase-scope."""
        self._recalculate_phase_ranking(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            phase=phase,
            variant_mode=variant_mode,
            phase_name=phase_name,
        )

    def mark_top_n_variant_tables(
        self,
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        winner_variant_tables: Sequence[str],
        phase: Optional[int] = None,
        variant_mode: Optional[str] = None,
        phase_name: Optional[str] = None,
    ) -> None:
        """
        Явно выставляет флаг `is_top_n=1` только у переданных победителей фазы.

        Используется стратегиями, где top-N формируется как результат
        поэтапного отбора кандидатов для перехода в следующую фазу.
        """
        if phase is None and not variant_mode and not phase_name:
            return
        scope_where_clause, scope_params = self._build_phase_scope_clause(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            phase=phase,
            variant_mode=variant_mode,
            phase_name=phase_name,
        )

        # Сначала сбрасываем флаг в scope, затем проставляем только у победителей.
        self._execute(
            f"""
            ALTER TABLE `{self._database}`.`{self._table}`
            UPDATE is_top_n = 0
            WHERE {scope_where_clause}
            SETTINGS mutations_sync = 1
            """,
            scope_params,
        )

        unique_variant_tables: list[str] = []
        seen_variant_tables: set[str] = set()
        for variant_table in winner_variant_tables:
            normalized = str(variant_table or "").strip()
            if not normalized or normalized in seen_variant_tables:
                continue
            seen_variant_tables.add(normalized)
            unique_variant_tables.append(normalized)

        for variant_table in unique_variant_tables:
            self._execute(
                f"""
                ALTER TABLE `{self._database}`.`{self._table}`
                UPDATE is_top_n = 1
                WHERE {scope_where_clause}
                  AND variant_table = %(winner_variant_table)s
                SETTINGS mutations_sync = 1
                """,
                {
                    **scope_params,
                    "winner_variant_table": variant_table,
                },
            )

        # Fail-safe: если winners переданы, но ни одна строка в scope не помечена,
        # откатываемся на ranking-based top-N, чтобы не оставлять фазу без winner-флага.
        if unique_variant_tables:
            scope_rows_data = self._execute(
                f"""
                SELECT count()
                FROM `{self._database}`.`{self._table}`
                WHERE {scope_where_clause}
                """,
                scope_params,
            )
            scope_rows = (
                int(scope_rows_data[0][0])
                if scope_rows_data and scope_rows_data[0] and scope_rows_data[0][0] is not None
                else 0
            )
            marked_rows_data = self._execute(
                f"""
                SELECT count()
                FROM `{self._database}`.`{self._table}`
                WHERE {scope_where_clause}
                  AND is_top_n = 1
                """,
                scope_params,
            )
            marked_rows = (
                int(marked_rows_data[0][0])
                if marked_rows_data and marked_rows_data[0] and marked_rows_data[0][0] is not None
                else 0
            )
            expected_marked_rows = min(
                scope_rows,
                self._resolve_top_n_winners(
                    benchmark_run_id=benchmark_run_id,
                    benchmark_id=benchmark_id,
                    source_database=source_database,
                    source_table=source_table,
                    phase=phase,
                    variant_mode=variant_mode,
                    phase_name=phase_name,
                ),
            )
            if scope_rows > 0 and marked_rows < expected_marked_rows:
                logger.warning(
                    "mark_top_n_variant_tables: winners не совпали со scope "
                    "(run_id=%s, benchmark=%s, table=%s.%s, phase=%s, mode=%s); "
                    "fallback на recalculate_phase_ranking",
                    benchmark_run_id,
                    benchmark_id,
                    source_database,
                    source_table,
                    phase,
                    variant_mode or phase_name,
                )
                self._recalculate_phase_ranking(
                    benchmark_run_id=benchmark_run_id,
                    benchmark_id=benchmark_id,
                    source_database=source_database,
                    source_table=source_table,
                    phase=phase,
                    variant_mode=variant_mode,
                    phase_name=phase_name,
                )

    @classmethod
    def _extract_expression_context_from_score_calculation_json(
        cls,
        raw_json: Any,
    ) -> Optional[Dict[str, Any]]:
        """Извлекает expression-context из `score_calculation_json`."""
        if not isinstance(raw_json, str) or not raw_json.strip():
            return None
        try:
            payload = json.loads(raw_json)
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None

        context = payload.get("context")
        if isinstance(context, dict):
            return context

        # Backward-compatible fallback: если контекст был сохранен в root-json.
        fallback_context = {
            key: payload[key]
            for key in cls._CUSTOM_SCORE_CONTEXT_FALLBACK_KEYS
            if key in payload
        }
        return fallback_context or None

    def _select_custom_score_target_rows(
        self,
        *,
        table_name: str,
        benchmark_id: str,
        benchmark_run_id: Optional[int],
        source_database: Optional[str],
        source_table: Optional[str],
    ) -> List[tuple[str, Any]]:
        """Читает `(id, score_calculation_json)` для пересчета custom-score."""
        where_conditions = ["benchmark_id = %(benchmark_id)s"]
        params: Dict[str, Any] = {"benchmark_id": benchmark_id}
        if benchmark_run_id is not None:
            where_conditions.append("benchmark_run_id = %(benchmark_run_id)s")
            params["benchmark_run_id"] = int(benchmark_run_id)
        if source_database is not None and str(source_database).strip():
            where_conditions.append("source_db_name = %(source_database)s")
            params["source_database"] = str(source_database).strip()
        if source_table is not None and str(source_table).strip():
            where_conditions.append("source_table_name = %(source_table)s")
            params["source_table"] = str(source_table).strip()

        where_clause = " AND ".join(where_conditions)
        rows = self._execute(
            f"""
            SELECT id, score_calculation_json
            FROM `{self._database}`.`{table_name}`
            WHERE {where_clause}
            ORDER BY benchmark_run_id DESC, id DESC
            """,
            params,
        )
        normalized_rows: list[tuple[str, Any]] = []
        for row in rows:
            if not row:
                continue
            row_id = str(row[0] or "").strip()
            if not row_id:
                continue
            score_calc_json = row[1] if len(row) > 1 else None
            normalized_rows.append((row_id, score_calc_json))
        return normalized_rows

    def _update_custom_score_for_row(
        self,
        *,
        table_name: str,
        row_id: str,
        score_custom: Optional[float],
    ) -> None:
        """Обновляет `score_custom` у одной записи результата."""
        self._execute(
            f"""
            ALTER TABLE `{self._database}`.`{table_name}`
            UPDATE score_custom = %(score_custom)s
            WHERE id = %(id)s
            SETTINGS mutations_sync = 1
            """,
            {
                "score_custom": score_custom,
                "id": row_id,
            },
        )

    def _recalculate_custom_score_for_table(
        self,
        *,
        table_name: str,
        benchmark_id: str,
        expression: str,
        benchmark_run_id: Optional[int],
        source_database: Optional[str],
        source_table: Optional[str],
    ) -> Dict[str, int]:
        """Пересчитывает `score_custom` для одной таблицы результатов."""
        rows = self._select_custom_score_target_rows(
            table_name=table_name,
            benchmark_id=benchmark_id,
            benchmark_run_id=benchmark_run_id,
            source_database=source_database,
            source_table=source_table,
        )
        total_rows = len(rows)
        updated_rows = 0
        failed_rows = 0

        for row_id, score_calculation_json in rows:
            expression_context = self._extract_expression_context_from_score_calculation_json(
                score_calculation_json
            )
            if not isinstance(expression_context, dict):
                failed_rows += 1
                self._update_custom_score_for_row(
                    table_name=table_name,
                    row_id=row_id,
                    score_custom=None,
                )
                continue

            try:
                score_custom = evaluate_score_expression(expression, expression_context)
            except ScoreEvaluationError as exc:
                failed_rows += 1
                logger.warning(
                    "Custom-score recalc skipped row id=%s in `%s`.`%s`: %s",
                    row_id,
                    self._database,
                    table_name,
                    exc,
                )
                self._update_custom_score_for_row(
                    table_name=table_name,
                    row_id=row_id,
                    score_custom=None,
                )
                continue

            updated_rows += 1
            self._update_custom_score_for_row(
                table_name=table_name,
                row_id=row_id,
                score_custom=float(score_custom),
            )

        return {
            "total_rows": total_rows,
            "updated_rows": updated_rows,
            "failed_rows": failed_rows,
        }

    def recalculate_custom_score_for_benchmark(
        self,
        *,
        benchmark_id: str,
        expression: str,
        benchmark_run_id: Optional[int] = None,
        source_database: Optional[str] = None,
        source_table: Optional[str] = None,
        target_tables: str = "phased",
    ) -> Dict[str, Dict[str, int]]:
        """
        Пересчитывает `score_custom` по новой формуле для выбранного benchmark scope.

        Основной `score` при этом не изменяется.
        """
        normalized_benchmark_id = str(benchmark_id or "").strip()
        if not normalized_benchmark_id:
            raise ValueError("benchmark_id не должен быть пустым")
        normalized_expression = str(expression or "").strip()
        if not normalized_expression:
            raise ValueError("expression не должна быть пустой")

        issues = validate_score_expression(normalized_expression)
        if issues:
            raise ValueError(
                "Некорректная expression для custom-score:\n- " + "\n- ".join(issues)
            )

        scope = str(target_tables or "").strip().lower() or "phased"
        if scope not in {"phased", "legacy", "both"}:
            raise ValueError(
                "target_tables должен быть одним из: phased, legacy, both"
            )
        table_names: list[str] = []
        if scope in {"phased", "both"}:
            table_names.append(self._phased_table)
        if scope in {"legacy", "both"}:
            if self._create_legacy_table or self._legacy_table == self._phased_table:
                table_names.append(self._legacy_table)
            elif scope == "legacy":
                raise ValueError(
                    "legacy result-table отключена (create_legacy_table=False), "
                    "target_tables=legacy недоступен"
                )
        resolved_table_names: list[str] = []
        seen_table_names: set[str] = set()
        for table_name in table_names:
            normalized = str(table_name or "").strip()
            if not normalized or normalized in seen_table_names:
                continue
            seen_table_names.add(normalized)
            resolved_table_names.append(normalized)

        result: Dict[str, Dict[str, int]] = {}
        for table_name in resolved_table_names:
            result[table_name] = self._recalculate_custom_score_for_table(
                table_name=table_name,
                benchmark_id=normalized_benchmark_id,
                expression=normalized_expression,
                benchmark_run_id=benchmark_run_id,
                source_database=source_database,
                source_table=source_table,
            )
        return result

    @staticmethod
    def _build_run_record_id(
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
    ) -> str:
        """Строит стабильный идентификатор строки benchmark_runs."""
        return (
            f"{benchmark_run_id}:{benchmark_id}:"
            f"{source_database}.{source_table}"
        )

    @staticmethod
    def _build_scoped_result_id(
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        variant_table: str,
        raw_result_token: str,
    ) -> str:
        """
        Строит контекстный устойчивый id результата варианта.

        Идентификатор включает scope run/table/variant и исходный токен
        (`execution_uuid`/`result.id`), чтобы записи разных вариантов
        не могли конфликтовать даже при одинаковом external-id.
        """
        token = str(raw_result_token or "").strip() or str(uuid4())
        payload = json.dumps(
            {
                "benchmark_run_id": int(benchmark_run_id),
                "benchmark_id": str(benchmark_id),
                "source_database": str(source_database),
                "source_table": str(source_table),
                "variant_table": str(variant_table),
                "raw_result_token": token,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _to_naive_storage_datetime(value: Optional[datetime]) -> Optional[datetime]:
        """Приводит datetime к naive storage-timezone для ClickHouse DateTime64."""
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=_RESULTS_TZ)
        return value.astimezone(_RESULTS_TZ).replace(tzinfo=None)

    @staticmethod
    def _to_aware_storage_datetime(value: Any) -> datetime:
        """Нормализует дату/время из ClickHouse к aware storage-timezone datetime."""
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=_RESULTS_TZ)
            return value.astimezone(_RESULTS_TZ)
        return datetime.now(_RESULTS_TZ)

    def _store_record_by_strategy(
        self,
        *,
        record: StoredBenchmarkResult,
        benchmark_strategy: str,
    ) -> None:
        """Роутит запись результата в нужную таблицу в зависимости от strategy."""
        if self._is_phased_strategy(benchmark_strategy):
            if self._legacy_table == self._phased_table:
                self._insert_record(
                    record=record,
                    table_name=self._phased_table,
                    recalculate_phase_ranking=False,
                )
            else:
                self._insert_phased_record(record)
            return
        if not self._create_legacy_table:
            raise ValueError(
                "legacy result table отключена (create_legacy_table=False), "
                "но получен результат non-phased strategy"
            )
        self._insert_record(
            record=record,
            table_name=self._legacy_table,
            recalculate_phase_ranking=False,
        )

    @classmethod
    def _is_phased_strategy(cls, strategy: str) -> bool:
        """Проверяет, что strategy относится к phased-линейке."""
        normalized = str(strategy or "").strip()
        return normalized in cls._PHASED_STRATEGIES

    def _insert_record(
        self,
        *,
        record: StoredBenchmarkResult,
        table_name: str,
        recalculate_phase_ranking: bool,
    ) -> None:
        with self._record_insert_lock, self._acquire_cross_process_record_lock(
            table_name=table_name,
            record_id=record.id,
        ):
            if self._record_id_exists(table_name=table_name, record_id=record.id):
                self._assert_duplicate_record_identity_matches(
                    table_name=table_name,
                    record=record,
                )
                logger.warning(
                    "ClickHouseBenchmarkResultStore: duplicate record id=%s в `%s`.`%s` "
                    "(run_id=%d, benchmark=%s, table=%s.%s, mode=%s) — пропускаем insert",
                    record.id,
                    self._database,
                    table_name,
                    record.benchmark_run_id,
                    record.benchmark_id,
                    record.source_db_name,
                    record.source_table_name,
                    record.variant_mode,
                )
                return
            row_map = self._record_to_clickhouse_map(record)
            self._insert_row_map(
                table_name=table_name,
                row_map=row_map,
                preferred_columns=self._INSERT_COLUMNS,
            )
        if recalculate_phase_ranking and record.phase is not None:
            self._recalculate_phase_ranking(
                benchmark_run_id=record.benchmark_run_id,
                benchmark_id=record.benchmark_id,
                source_database=record.source_db_name,
                source_table=record.source_table_name,
                phase=int(record.phase),
                variant_mode=record.variant_mode,
                phase_name=record.phase_name,
            )

    def _insert_phased_record(self, record: StoredBenchmarkResult) -> None:
        """Сохраняет результат phased-стратегии в компактную phased-таблицу."""
        with self._record_insert_lock, self._acquire_cross_process_record_lock(
            table_name=self._phased_table,
            record_id=record.id,
        ):
            if self._record_id_exists(table_name=self._phased_table, record_id=record.id):
                self._assert_duplicate_record_identity_matches(
                    table_name=self._phased_table,
                    record=record,
                )
                logger.warning(
                    "ClickHouseBenchmarkResultStore: duplicate phased record id=%s в `%s`.`%s` "
                    "(run_id=%d, benchmark=%s, table=%s.%s, mode=%s) — пропускаем insert",
                    record.id,
                    self._database,
                    self._phased_table,
                    record.benchmark_run_id,
                    record.benchmark_id,
                    record.source_db_name,
                    record.source_table_name,
                    record.variant_mode,
                )
                return
            row_map = self._record_to_phased_clickhouse_map(record)
            self._insert_row_map(
                table_name=self._phased_table,
                row_map=row_map,
                preferred_columns=self._PHASED_INSERT_COLUMNS,
            )

    @staticmethod
    def _normalize_record_id(record_id: str) -> str:
        """Возвращает нормализованный record id."""
        return str(record_id or "").strip()

    @staticmethod
    def _parse_float_env(env_name: str, *, default: float) -> float:
        """Читает float-параметр из env; при ошибке возвращает default."""
        raw = str(os.getenv(env_name, "") or "").strip()
        if not raw:
            return float(default)
        try:
            return max(0.0, float(raw))
        except Exception:
            logger.warning(
                "ClickHouseBenchmarkResultStore: env `%s=%s` не float, используем default=%s",
                env_name,
                raw,
                default,
            )
            return float(default)

    @staticmethod
    def _is_redis_url(value: str) -> bool:
        """Проверяет, что строка похожа на redis URL."""
        lowered = str(value or "").strip().lower()
        return lowered.startswith("redis://") or lowered.startswith("rediss://")

    def _resolve_redis_lock_url(self) -> str:
        """Определяет URL Redis для dedup-lock."""
        explicit = str(os.getenv("BENCH_RESULT_STORE_REDIS_URL", "") or "").strip()
        if explicit:
            return explicit

        # Фоллбек на общий Celery backend, если это Redis.
        celery_backend = str(os.getenv("BENCH_CELERY_BACKEND_URL", "") or "").strip()
        if self._is_redis_url(celery_backend):
            return celery_backend
        # Локальный fallback для dev/локальных прогонов.
        return "redis://localhost:6379/0"

    def _init_redis_lock_client(self) -> None:
        """Инициализирует Redis-клиент для межпроцессного lock."""
        redis_url = str(self._record_lock_redis_url or "").strip()
        if not redis_url:
            raise RuntimeError(
                "ClickHouseBenchmarkResultStore: Redis обязателен для запуска. "
                "Задай BENCH_RESULT_STORE_REDIS_URL "
                "(или BENCH_CELERY_BACKEND_URL с redis:// / rediss://)."
            )
        if redis_module is None:
            raise RuntimeError(
                "ClickHouseBenchmarkResultStore: пакет `redis` не установлен, "
                "но Redis lock обязателен для запуска."
            )
        try:
            client = redis_module.Redis.from_url(redis_url)
            client.ping()
            self._record_lock_redis_client = client
            logger.info(
                "ClickHouseBenchmarkResultStore: включен Redis dedup-lock "
                "(prefix=%s, ttl_sec=%.1f, blocking_timeout_sec=%.1f)",
                self._record_lock_redis_prefix,
                self._record_lock_redis_ttl_sec,
                self._record_lock_redis_blocking_timeout_sec,
            )
        except Exception as exc:
            self._record_lock_redis_client = None
            raise RuntimeError(
                "ClickHouseBenchmarkResultStore: не удалось инициализировать Redis dedup-lock "
                f"(url={redis_url}): {exc}"
            ) from exc

    @contextmanager
    def _acquire_cross_process_record_lock(self, *, table_name: str, record_id: str):
        """
        Межпроцессный Redis lock для `(table_name, record_id)`.

        Нужен, чтобы check->insert дедуп работал корректно между несколькими worker-процессами.
        """
        normalized_id = self._normalize_record_id(record_id)
        if not normalized_id:
            yield
            return

        redis_client = self._record_lock_redis_client
        if redis_client is None:
            raise RuntimeError(
                "ClickHouseBenchmarkResultStore: Redis dedup-lock client не инициализирован"
            )

        lock_key = f"{self._database}.{table_name}:{normalized_id}"
        lock_name = (
            f"{self._record_lock_redis_prefix}:"
            f"{sha256(lock_key.encode('utf-8')).hexdigest()}"
        )
        lock = redis_client.lock(
            name=lock_name,
            timeout=self._record_lock_redis_ttl_sec,
            blocking_timeout=self._record_lock_redis_blocking_timeout_sec,
        )

        acquired = False
        try:
            acquired = bool(lock.acquire(blocking=True))
            if not acquired:
                raise TimeoutError(
                    "ClickHouseBenchmarkResultStore: timeout acquiring Redis dedup-lock "
                    f"for `{self._database}`.`{table_name}` id={normalized_id}"
                )
            yield
        finally:
            if acquired:
                try:
                    lock.release()
                except Exception:
                    pass

    def _insert_row_map(
        self,
        *,
        table_name: str,
        row_map: Dict[str, Any],
        preferred_columns: Sequence[str],
    ) -> None:
        """Вставляет запись в таблицу в соответствии с текущей runtime-схемой."""
        column_names = list(preferred_columns)
        row = tuple(row_map[column_name] for column_name in column_names)
        self._client.insert(
            table=f"{self._database}.{table_name}",
            data=[row],
            column_names=column_names,
        )

    def _record_id_exists(self, *, table_name: str, record_id: str) -> bool:
        """Проверяет наличие записи с указанным `id` в таблице результатов."""
        normalized_id = self._normalize_record_id(record_id)
        if not normalized_id:
            return False
        rows = self._execute(
            f"""
            SELECT 1
            FROM `{self._database}`.`{table_name}`
            WHERE id = %(id)s
            LIMIT 1
            """,
            {"id": normalized_id},
        )
        return bool(rows)

    def _fetch_record_identity_by_id(
        self,
        *,
        table_name: str,
        record_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Возвращает identity-слепок записи по `id` для anti-conflict проверки."""
        normalized_id = self._normalize_record_id(record_id)
        if not normalized_id:
            return None
        try:
            rows = self._execute(
                f"""
                SELECT
                    benchmark_run_id,
                    benchmark_id,
                    source_db_name,
                    source_table_name,
                    variant_table,
                    variant_mode
                FROM `{self._database}`.`{table_name}`
                WHERE id = %(id)s
                ORDER BY finished_at DESC, benchmark_started_at DESC
                LIMIT 1
                """,
                {"id": normalized_id},
            )
        except Exception:
            logger.exception(
                "ClickHouseBenchmarkResultStore: не удалось прочитать identity по id=%s "
                "из `%s`.`%s`",
                normalized_id,
                self._database,
                table_name,
            )
            return None
        if not rows:
            return None
        (
            benchmark_run_id,
            benchmark_id,
            source_db_name,
            source_table_name,
            variant_table,
            variant_mode,
        ) = rows[0]
        return {
            "benchmark_run_id": int(benchmark_run_id),
            "benchmark_id": str(benchmark_id),
            "source_db_name": str(source_db_name),
            "source_table_name": str(source_table_name),
            "variant_table": str(variant_table),
            "variant_mode": str(variant_mode),
        }

    def _assert_duplicate_record_identity_matches(
        self,
        *,
        table_name: str,
        record: StoredBenchmarkResult,
    ) -> None:
        """
        Проверяет, что duplicate `id` принадлежит тому же logical-variant.

        Если `id` уже существует, но identity отличается, это жёсткая
        коллизия: запись одного варианта может затереть/замаскировать другой.
        """
        existing = self._fetch_record_identity_by_id(
            table_name=table_name,
            record_id=record.id,
        )
        if existing is None:
            return

        expected = {
            "benchmark_run_id": int(record.benchmark_run_id),
            "benchmark_id": str(record.benchmark_id),
            "source_db_name": str(record.source_db_name),
            "source_table_name": str(record.source_table_name),
            "variant_table": str(record.variant_table),
            "variant_mode": str(record.variant_mode),
        }
        mismatches = [
            key
            for key, expected_value in expected.items()
            if existing.get(key) != expected_value
        ]
        if not mismatches:
            return
        raise RuntimeError(
            "ClickHouseBenchmarkResultStore: record id collision between different variants "
            f"in `{self._database}`.`{table_name}` for id={record.id}. "
            f"mismatched_fields={mismatches}, existing={existing}, expected={expected}"
        )

    def _record_to_clickhouse_map(self, record: StoredBenchmarkResult) -> Dict[str, Any]:
        benchmark_started_at_utc = self._to_naive_storage_datetime(record.benchmark_started_at)
        started_at_utc = self._to_naive_storage_datetime(record.started_at)
        finished_at_utc = self._to_naive_storage_datetime(record.finished_at)

        row_map = {
            **record.model_dump(),
            "benchmark_started_at": benchmark_started_at_utc,
            "started_at": started_at_utc,
            "finished_at": finished_at_utc,
            "variant_params": json.dumps(
                record.variant_params,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            ),
        }
        for column_name in self._SQL_TEXT_COLUMNS:
            row_map[column_name] = self._format_sql_text_column(
                column_name=column_name,
                value=row_map.get(column_name),
            )
        for column_name in self._SQL_JSON_COLUMNS:
            row_map[column_name] = self._format_sql_json_string_or_as_is(
                row_map.get(column_name)
            )
        for column_name in self._PRETTY_JSON_STRING_COLUMNS:
            row_map[column_name] = self._pretty_json_string_or_as_is(
                row_map.get(column_name)
            )
        return row_map

    def _record_to_phased_clickhouse_map(self, record: StoredBenchmarkResult) -> Dict[str, Any]:
        """Преобразует запись результата в map для phased-таблицы."""
        benchmark_started_at_utc = self._to_naive_storage_datetime(record.benchmark_started_at)
        started_at_utc = self._to_naive_storage_datetime(record.started_at)
        finished_at_utc = self._to_naive_storage_datetime(record.finished_at)

        variant_params_json = record.variant_params_json or json.dumps(
            record.variant_params,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        variant_params = json.dumps(
            record.variant_params,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        tested_table_ddl = self._format_ddl_or_as_is(record.tested_table_ddl)

        select_metrics_json = self._pretty_json_string_or_as_is(
            self._format_sql_json_string_or_as_is(record.select_metrics_json)
        )
        tested_select_speedup_by_query_json = self._pretty_json_string_or_as_is(
            self._format_sql_json_string_or_as_is(
                record.tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json
            )
        )
        tested_select_read_bytes_speedup_by_query_json = self._pretty_json_string_or_as_is(
            self._format_sql_json_string_or_as_is(
                record.tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json
            )
        )
        if tested_select_read_bytes_speedup_by_query_json is None:
            tested_select_read_bytes_speedup_by_query_json = self._pretty_json_string_or_as_is(
                self._extract_read_bytes_speedup_query_map_json(
                    tested_select_speedup_by_query_json
                )
            )
        tested_select_speedup_vs_source_by_query_json = self._pretty_json_string_or_as_is(
            self._format_sql_json_string_or_as_is(
                record.tested_table_select_time_ms_percentiles_speed_up_coefs_vs_source_by_query_json
            )
        )
        if tested_select_speedup_vs_source_by_query_json is None:
            tested_select_speedup_vs_source_by_query_json = (
                tested_select_speedup_by_query_json
            )
        insert_metrics_json = self._pretty_json_string_or_as_is(
            self._format_sql_json_string_or_as_is(record.insert_metrics_json)
        )
        size_bytes_by_column_json = self._pretty_json_string_or_as_is(
            record.size_bytes_by_column_json
        )
        size_bytes_indexes_json = self._pretty_json_string_or_as_is(
            record.size_bytes_indexes_json
        )
        score_calculation_json = self._pretty_json_string_or_as_is(
            record.score_calculation_json
        )
        tested_size_with_indexes = self._extract_size_bytes_from_value_json(
            record.tested_table_consumed_compressed_size_bytes_with_indexes_json
        )
        if tested_size_with_indexes is None:
            tested_size_with_indexes = record.tested_table_consumed_compressed_size_bytes_with_indexes
        if tested_size_with_indexes is None:
            tested_size_with_indexes = record.size_bytes_total
        source_size_overall = self._extract_size_bytes_from_value_json(
            record.source_table_consumed_compressed_size_bytes_overall_json
        )
        if source_size_overall is None:
            source_size_overall = record.source_table_consumed_compressed_size_bytes_overall
        tested_size_with_indexes_json = self._pretty_json_string_or_as_is(
            record.tested_table_consumed_compressed_size_bytes_with_indexes_json
        )
        if tested_size_with_indexes_json is None:
            tested_size_with_indexes_json = self._build_size_bytes_value_json(
                size_bytes=tested_size_with_indexes,
                size_bytes_readable=(
                    record.tested_table_consumed_compressed_size_bytes_with_indexes_readable
                ),
            )
            tested_size_with_indexes_json = self._pretty_json_string_or_as_is(
                tested_size_with_indexes_json
            )
        source_size_overall_json = self._pretty_json_string_or_as_is(
            record.source_table_consumed_compressed_size_bytes_overall_json
        )
        if source_size_overall_json is None:
            source_size_overall_json = self._build_size_bytes_value_json(
                size_bytes=source_size_overall,
                size_bytes_readable=record.source_table_consumed_compressed_size_bytes_overall_readable,
            )
            source_size_overall_json = self._pretty_json_string_or_as_is(
                source_size_overall_json
            )
        compression_coef = record.tested_table_compression_overall_coef
        variant_mode_normalized = str(record.variant_mode or "").strip().lower()
        is_source_baseline_mode = variant_mode_normalized == "source_baseline"
        if compression_coef is None and not is_source_baseline_mode:
            try:
                source_size_numeric = float(source_size_overall or 0.0)
                tested_size_numeric = float(tested_size_with_indexes or 0.0)
            except Exception:
                source_size_numeric = 0.0
                tested_size_numeric = 0.0
            if source_size_numeric > 0 and tested_size_numeric > 0:
                compression_coef = source_size_numeric / tested_size_numeric

        return {
            "benchmark_run_id": int(record.benchmark_run_id),
            "benchmark_started_at": benchmark_started_at_utc,
            "benchmark_id": str(record.benchmark_id),
            "id": str(record.id),
            "parent_id": record.parent_id,
            "celery_task_id": record.celery_task_id,
            "celery_worker_hostname": record.celery_worker_hostname,
            "started_at": started_at_utc,
            "finished_at": finished_at_utc,
            "source_db_name": str(record.source_db_name),
            "source_table_name": str(record.source_table_name),
            "tested_table_ddl": tested_table_ddl,
            "variant_params_json": self._pretty_json_string_or_as_is(variant_params_json),
            "variant_table": str(record.variant_table),
            "variant_mode": str(record.variant_mode),
            "variant_mode_id": record.variant_mode_id,
            "variant_params": variant_params,
            "total_n_rows_in_tested_table": record.total_n_rows_in_tested_table,
            "size_bytes_total": record.size_bytes_total,
            "size_bytes_by_column_json": size_bytes_by_column_json,
            "size_bytes_indexes_json": size_bytes_indexes_json,
            "tested_table_consumed_compressed_size_bytes_with_indexes_json": (
                tested_size_with_indexes_json
            ),
            "tested_table_primary_index_size_json": self._pretty_json_string_or_as_is(
                record.tested_table_primary_index_size_json
            ),
            "source_table_consumed_compressed_size_bytes_overall_json": source_size_overall_json,
            "tested_table_compression_overall_coef": compression_coef,
            "select_metrics_json": select_metrics_json,
            "tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json": (
                tested_select_read_bytes_speedup_by_query_json
            ),
            "tested_table_select_time_ms_percentiles_speed_up_coefs_vs_source_by_query_json": (
                tested_select_speedup_vs_source_by_query_json
            ),
            "insert_metrics_json": insert_metrics_json,
            "score_calculation_json": score_calculation_json,
            "score": record.score,
            "rank_in_phase": record.rank_in_phase,
            "is_top_n": bool(record.is_top_n),
            "measurement_quality_flag": record.measurement_quality_flag,
            "measurement_quality_details_json": self._pretty_json_string_or_as_is(
                record.measurement_quality_details_json
            ),
        }

    @classmethod
    def _format_sql_text_column(cls, *, column_name: str, value: Any) -> Any:
        """Форматирует SQL-строки в scalar-колонках перед сохранением."""
        if not isinstance(value, str):
            return value
        if column_name.endswith("_ddl"):
            return cls._format_ddl_or_as_is(value)
        return cls._format_query_or_as_is(value)

    @classmethod
    def _format_sql_json_string_or_as_is(cls, value: Any) -> Any:
        """Форматирует SQL-поля внутри JSON-строки, оставляя не-JSON как есть."""
        if not isinstance(value, str):
            return value
        try:
            payload = json.loads(value)
        except Exception:
            return value
        normalized = cls._format_sql_in_json_payload(payload)
        return json.dumps(
            normalized,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )

    @classmethod
    def _format_sql_in_json_payload(
        cls,
        value: Any,
        *,
        parent_key: Optional[str] = None,
    ) -> Any:
        """Рекурсивно форматирует SQL-строки в JSON-структуре."""
        if isinstance(value, dict):
            return {
                key: cls._format_sql_in_json_payload(item, parent_key=str(key))
                for key, item in value.items()
            }

        if isinstance(value, list):
            if parent_key and cls._is_sql_queries_list_key(parent_key):
                return [
                    cls._format_query_or_as_is(item) if isinstance(item, str)
                    else cls._format_sql_in_json_payload(item)
                    for item in value
                ]
            return [cls._format_sql_in_json_payload(item) for item in value]

        if isinstance(value, str) and parent_key and cls._is_sql_scalar_key(parent_key):
            key_lower = parent_key.strip().lower()
            if key_lower.endswith("_ddl") or key_lower == "ddl":
                return cls._format_ddl_or_as_is(value)
            return cls._format_query_or_as_is(value)
        return value

    @staticmethod
    def _is_sql_scalar_key(key: str) -> bool:
        """Определяет, что ключ JSON содержит scalar SQL-строку."""
        key_lower = key.strip().lower()
        if key_lower in {"query", "source_query", "tested_query", "ddl"}:
            return True
        if key_lower.endswith("_query") or key_lower.endswith("_ddl"):
            return True
        return False

    @staticmethod
    def _is_sql_queries_list_key(key: str) -> bool:
        """Определяет, что ключ JSON содержит список SQL-запросов."""
        key_lower = key.strip().lower()
        return key_lower in {"warmup_queries", "test_queries"} or key_lower.endswith(
            "_queries"
        )

    @classmethod
    def _format_ddl_or_as_is(cls, value: str) -> str:
        """Форматирует DDL. При неудаче возвращает query-стиль форматирования."""
        cleaned = value.strip()
        if not cleaned:
            return cleaned
        try:
            return TableDDL.from_ddl(cleaned).to_ddl()
        except Exception:
            return cls._format_query_or_as_is(cleaned)

    @classmethod
    def _format_query_or_as_is(cls, value: str) -> str:
        """Форматирует SQL-query в читабельный вид."""
        cleaned = value.strip()
        if not cleaned:
            return cleaned
        if sqlparse is not None:
            try:
                return sqlparse.format(
                    cleaned,
                    reindent=True,
                    keyword_case="upper",
                ).strip()
            except Exception:
                pass
        return cls._basic_query_format(cleaned)

    @classmethod
    def _basic_query_format(cls, value: str) -> str:
        """
        Упрощённый SQL форматтер без внешних зависимостей.

        Ставит переносы на главные клаузы, сохраняя строковые литералы.
        """
        tokens = cls._split_sql_tokens_preserving_literals(value)
        if not tokens:
            return value.strip()

        clause_words = {
            "WITH",
            "SELECT",
            "FROM",
            "WHERE",
            "PREWHERE",
            "HAVING",
            "LIMIT",
            "SETTINGS",
            "UNION",
            "JOIN",
            "ENGINE",
            "TTL",
        }
        clause_pairs = {
            ("CREATE", "TABLE"),
            ("GROUP", "BY"),
            ("ORDER", "BY"),
            ("PARTITION", "BY"),
            ("PRIMARY", "KEY"),
            ("SAMPLE", "BY"),
            ("LEFT", "JOIN"),
            ("RIGHT", "JOIN"),
            ("FULL", "JOIN"),
            ("INNER", "JOIN"),
            ("CROSS", "JOIN"),
        }

        lines: list[str] = []
        current_line: list[str] = []
        idx = 0
        while idx < len(tokens):
            token = tokens[idx]
            token_upper = token.upper()

            matched_pair: Optional[tuple[str, str]] = None
            if idx + 1 < len(tokens):
                pair = (token_upper, tokens[idx + 1].upper())
                if pair in clause_pairs:
                    matched_pair = pair

            if matched_pair is not None:
                if current_line:
                    lines.append(" ".join(current_line).strip())
                current_line = [f"{matched_pair[0]} {matched_pair[1]}"]
                idx += 2
                continue

            if token_upper in clause_words:
                if current_line:
                    lines.append(" ".join(current_line).strip())
                current_line = [token_upper]
                idx += 1
                continue

            current_line.append(token)
            idx += 1

        if current_line:
            lines.append(" ".join(current_line).strip())

        return "\n".join(line for line in lines if line)

    @staticmethod
    def _split_sql_tokens_preserving_literals(sql: str) -> List[str]:
        """Делит SQL на токены по whitespace вне литералов/бэктиков."""
        tokens: list[str] = []
        buffer: list[str] = []
        quote_char: Optional[str] = None
        escaped = False

        for ch in sql:
            if quote_char is not None:
                buffer.append(ch)
                if escaped:
                    escaped = False
                    continue
                if ch == "\\" and quote_char in {"'", '"'}:
                    escaped = True
                    continue
                if ch == quote_char:
                    quote_char = None
                continue

            if ch in {"'", '"', "`"}:
                quote_char = ch
                buffer.append(ch)
                continue

            if ch.isspace():
                if buffer:
                    tokens.append("".join(buffer))
                    buffer = []
                continue

            buffer.append(ch)

        if buffer:
            tokens.append("".join(buffer))
        return tokens

    @staticmethod
    def _pretty_json_string_or_as_is(value: Any) -> Any:
        """
        Нормализует JSON-строку в pretty-формат для удобства чтения в UI.

        Если значение не строка или невалидный JSON, возвращает как есть.
        """
        if not isinstance(value, str):
            return value
        try:
            parsed = json.loads(value)
        except Exception:
            return value
        return json.dumps(
            parsed,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )

    def _build_client(self):
        try:
            import clickhouse_connect
        except ImportError as exc:
            raise RuntimeError(
                "clickhouse-connect не установлен. Установи зависимости из requirements.txt"
            ) from exc

        return clickhouse_connect.get_client(
            host=self._connection.host,
            port=self._connection.port,
            username=self._connection.login,
            password=self._connection.password,
        )

    def _execute(self, query: str, params: Optional[Any] = None):
        rendered_query = self._bind_query_params(query, params)
        logger.debug(
            "ClickHouseBenchmarkResultStore SQL: %s",
            rendered_query.strip().splitlines()[0],
        )
        if self._is_read_query(rendered_query):
            result = self._client.query(rendered_query)
            return list(result.result_rows or [])
        self._client.command(rendered_query)
        return []

    @classmethod
    def _bind_query_params(cls, query: str, params: Optional[Any]) -> str:
        """
        Подставляет `%(name)s` параметры в SQL как литералы.

        Поддерживает только dict-параметры, что покрывает текущие use-case store.
        """
        if params is None:
            return query
        if not isinstance(params, dict):
            raise ValueError("ResultStore поддерживает только dict SQL-параметры")

        pattern = re.compile(r"%\((?P<key>[A-Za-z_][A-Za-z0-9_]*)\)s")

        def _replace(match: re.Match[str]) -> str:
            key = match.group("key")
            if key not in params:
                raise ValueError(f"Не найден SQL-параметр: {key}")
            return cls._sql_literal(params[key])

        return pattern.sub(_replace, query)

    @staticmethod
    def _sql_literal(value: Any) -> str:
        """Преобразует Python-значение в SQL-литерал ClickHouse."""
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return str(value)
        escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"

    @staticmethod
    def _strip_leading_sql_comments(query: str) -> str:
        """Удаляет ведущие block comments и пробелы."""
        stripped = query.lstrip()
        while stripped.startswith("/*"):
            end_pos = stripped.find("*/")
            if end_pos == -1:
                break
            stripped = stripped[end_pos + 2 :].lstrip()
        return stripped

    @classmethod
    def _is_read_query(cls, query: str) -> bool:
        """Определяет, что запрос возвращает строки."""
        normalized = cls._strip_leading_sql_comments(query).lower()
        return normalized.startswith(
            ("select", "with", "show", "describe", "desc", "explain", "exists")
        )
