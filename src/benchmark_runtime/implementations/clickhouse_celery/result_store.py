"""ClickHouse-backed result store для benchmark runtime."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

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
from .common import json_dumps

logger = logging.getLogger(__name__)

try:
    import sqlparse  # type: ignore
except ImportError:  # pragma: no cover - опциональная зависимость для красивого SQL-format.
    sqlparse = None


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
        "indexes": 4,
        "indexes_validation": 4,
        "final_validation": 5,
    }
    _PHASE_NAME_BY_VARIANT_MODE: dict[str, str] = {
        "source_baseline": "source_baseline",
        "order_by": "order_by",
        "types": "types",
        "types_validation": "types_validation",
        "codecs": "codecs",
        "codecs_validation": "codecs_validation",
        "indexes": "indexes",
        "indexes_validation": "indexes_validation",
        "final_validation": "final_validation",
    }

    _LEGACY_DUPLICATE_SIZE_COLUMNS: tuple[str, ...] = (
        "tested_table_total_size_bytes_with_indexes",
        "tested_table_total_size_bytes_with_indexes_readable",
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

    _INSERT_COLUMNS: list[str] = [
        "benchmark_run_id",
        "benchmark_started_at",
        "benchmark_id",
        "id",
        "parent_id",
        "phase",
        "phase_name",
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
        "tested_table_consumed_compressed_size_bytes_by_each_column",
        "source_table_consumed_compressed_size_bytes_by_each_column",
        "tested_table_consumed_compressed_size_bytes_overall",
        "tested_table_consumed_compressed_size_bytes_overall_readable",
        "tested_table_consumed_compressed_size_bytes_with_indexes",
        "tested_table_consumed_compressed_size_bytes_with_indexes_readable",
        "source_table_consumed_compressed_size_bytes_overall",
        "source_table_consumed_compressed_size_bytes_overall_readable",
        "tested_table_compression_overall_coef",
        "tested_table_compression_by_each_column_coef",
        "source_table_n_rows_in_size_test",
        "tested_table_n_rows_in_size_test",
        "size_bytes_total",
        "size_bytes_by_column_json",
        "size_bytes_indexes_json",
        "tested_table_cols_sizes",
        "tested_table_indexes_sizes",
        "tested_table_indexes_sizes_percent_from_col_size",
        "insert_metrics_json",
        "extra_json",
        "variant_table",
        "variant_mode",
        "variant_params",
        "rank_in_phase",
        "is_top_n",
        "score_calculation_json",
        "score",
    ]
    _PHASED_INSERT_COLUMNS: list[str] = [
        "benchmark_run_id",
        "benchmark_started_at",
        "benchmark_id",
        "id",
        "parent_id",
        "phase",
        "phase_name",
        "started_at",
        "finished_at",
        "source_db_name",
        "source_table_name",
        "tested_table_ddl",
        "variant_params_json",
        "variant_table",
        "variant_mode",
        "variant_params",
        "size_bytes_total",
        "size_bytes_by_column_json",
        "size_bytes_indexes_json",
        "select_metrics_json",
        "insert_metrics_json",
        "score_calculation_json",
        "score",
        "rank_in_phase",
        "is_top_n",
    ]
    _PRETTY_JSON_STRING_COLUMNS: tuple[str, ...] = (
        "index_params",
        "variant_params_json",
        "tested_table_select_metrics_by_query_json",
        "source_table_select_metrics_by_query_json",
        "tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json",
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
        # Backward-compat properties for legacy call-sites/tests.
        self._table = self._phased_table
        self._runs_table = self._phased_runs_table
        self._client = self._build_client()

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
                `started_at` Nullable(DateTime64(3, 'UTC')),
                `finished_at` Nullable(DateTime64(3, 'UTC')),
                `source_db_name` String,
                `source_table_name` String,
                `source_table_ddl` Nullable(String),
                `total_rows` Nullable(Int64),
                `data_path` Nullable(String),
                `benchmark_queries` Nullable(String),
                `score_weights` Nullable(String),
                `top_n_winners` Nullable(Int32),
                `config_json` Nullable(String),
                `updated_at` DateTime64(3, 'UTC')
            )
            ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY (id)
            """
        )
        if self._legacy_table == self._phased_table:
            self._ensure_results_table_schema(self._phased_table)
            return
        self._ensure_phased_results_table_schema(self._phased_table)
        self._ensure_results_table_schema(self._legacy_table)

    def _ensure_phased_results_table_schema(self, table_name: str) -> None:
        """Создаёт/мигрирует таблицу phased-стратегии (новая компактная схема)."""
        self._execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self._database}`.`{table_name}`
            (
                `benchmark_run_id` Int32,
                `benchmark_started_at` DateTime64(3, 'UTC'),
                `benchmark_id` String,
                `id` String,
                `parent_id` Nullable(String),
                `phase` Nullable(Int32),
                `phase_name` Nullable(String),
                `started_at` DateTime64(3, 'UTC'),
                `finished_at` Nullable(DateTime64(3, 'UTC')),
                `source_db_name` String,
                `source_table_name` String,
                `tested_table_ddl` String,
                `variant_params_json` Nullable(String),
                `variant_table` String,
                `variant_mode` String,
                `variant_params` String,
                `size_bytes_total` Nullable(Float64),
                `size_bytes_by_column_json` Nullable(String),
                `size_bytes_indexes_json` Nullable(String),
                `select_metrics_json` Nullable(String),
                `insert_metrics_json` Nullable(String),
                `score_calculation_json` Nullable(String),
                `score` Nullable(Float64),
                `rank_in_phase` Nullable(Int32),
                `is_top_n` Bool DEFAULT 0
            )
            ENGINE = MergeTree
            ORDER BY (benchmark_id, benchmark_run_id, source_db_name, source_table_name, id)
            """
        )
        self._execute(
            f"""
            ALTER TABLE `{self._database}`.`{table_name}`
                ADD COLUMN IF NOT EXISTS `parent_id` Nullable(String),
                ADD COLUMN IF NOT EXISTS `phase` Nullable(Int32),
                ADD COLUMN IF NOT EXISTS `phase_name` Nullable(String),
                ADD COLUMN IF NOT EXISTS `started_at` Nullable(DateTime64(3, 'UTC')),
                ADD COLUMN IF NOT EXISTS `finished_at` Nullable(DateTime64(3, 'UTC')),
                ADD COLUMN IF NOT EXISTS `variant_params_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `size_bytes_total` Nullable(Float64),
                ADD COLUMN IF NOT EXISTS `size_bytes_by_column_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `size_bytes_indexes_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `select_metrics_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `insert_metrics_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `score_calculation_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `rank_in_phase` Nullable(Int32),
                ADD COLUMN IF NOT EXISTS `is_top_n` Bool DEFAULT 0
            """
        )

    def _ensure_results_table_schema(self, table_name: str) -> None:
        """Создаёт/мигрирует целевую таблицу результатов."""
        self._execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self._database}`.`{table_name}`
            (
                `benchmark_run_id` Int32,
                `benchmark_started_at` DateTime64(3, 'UTC'),
                `benchmark_id` String,
                `id` String,
                `parent_id` Nullable(String),
                `phase` Nullable(Int32),
                `phase_name` Nullable(String),
                `started_at` DateTime64(3, 'UTC'),
                `finished_at` Nullable(DateTime64(3, 'UTC')),
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
                `tested_table_consumed_compressed_size_bytes_by_each_column` Nullable(String),
                `source_table_consumed_compressed_size_bytes_by_each_column` Nullable(String),
                `tested_table_consumed_compressed_size_bytes_overall` Nullable(Float64),
                `tested_table_consumed_compressed_size_bytes_overall_readable` Nullable(String),
                `tested_table_consumed_compressed_size_bytes_with_indexes` Nullable(Float64),
                `tested_table_consumed_compressed_size_bytes_with_indexes_readable` Nullable(String),
                `source_table_consumed_compressed_size_bytes_overall` Nullable(Float64),
                `source_table_consumed_compressed_size_bytes_overall_readable` Nullable(String),
                `tested_table_compression_overall_coef` Nullable(Float64),
                `tested_table_compression_by_each_column_coef` Nullable(String),
                `source_table_n_rows_in_size_test` Nullable(Int64),
                `tested_table_n_rows_in_size_test` Nullable(Int64),
                `size_bytes_total` Nullable(Float64),
                `size_bytes_by_column_json` Nullable(String),
                `size_bytes_indexes_json` Nullable(String),
                `tested_table_cols_sizes` Nullable(String),
                `tested_table_indexes_sizes` Nullable(String),
                `tested_table_indexes_sizes_percent_from_col_size` Nullable(String),
                `extra_json` Nullable(String),
                `variant_table` String,
                `variant_mode` String,
                `variant_params` String,
                `rank_in_phase` Nullable(Int32),
                `is_top_n` Bool DEFAULT 0,
                `score_calculation_json` Nullable(String),
                `score` Nullable(Float64)
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
                ADD COLUMN IF NOT EXISTS `tested_table_insert_metrics_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `source_table_insert_metrics_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `insert_metrics_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `select_metrics_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `tested_table_consumed_compressed_size_bytes_with_indexes` Nullable(Float64),
                ADD COLUMN IF NOT EXISTS `tested_table_consumed_compressed_size_bytes_with_indexes_readable` Nullable(String),
                ADD COLUMN IF NOT EXISTS `score_calculation_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `parent_id` Nullable(String),
                ADD COLUMN IF NOT EXISTS `phase` Nullable(Int32),
                ADD COLUMN IF NOT EXISTS `phase_name` Nullable(String),
                ADD COLUMN IF NOT EXISTS `started_at` Nullable(DateTime64(3, 'UTC')),
                ADD COLUMN IF NOT EXISTS `finished_at` Nullable(DateTime64(3, 'UTC')),
                ADD COLUMN IF NOT EXISTS `variant_params_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `size_bytes_total` Nullable(Float64),
                ADD COLUMN IF NOT EXISTS `size_bytes_by_column_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `size_bytes_indexes_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `rank_in_phase` Nullable(Int32),
                ADD COLUMN IF NOT EXISTS `is_top_n` Bool DEFAULT 0
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
        benchmark_queries_payload = [
            {
                "query_id": query.query_id,
                "query": query.query,
                "cache_mode": query.cache_mode,
                "select_operations_count": query.select_operations_count,
                "warmup_queries": list(query.warmup_queries),
            }
            for query in benchmark_queries
        ]
        scoring_payload = {
            "mode": scoring.mode,
            "expression": scoring.expression,
            "on_error_score": scoring.on_error_score,
        }
        self._insert_run_row(
            run_record_id=run_record_id,
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            started_at=benchmark_started_at,
            finished_at=None,
            source_db_name=table_plan.database,
            source_table_name=table_plan.table,
            source_table_ddl=source_table_ddl,
            total_rows=total_rows,
            data_path=None,
            benchmark_queries_json=json.dumps(
                benchmark_queries_payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            score_weights_json=json.dumps(
                scoring_payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            top_n_winners=int(table_plan.sequential_top_n),
            config_json=json.dumps(
                table_plan.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            ),
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
                source_table_ddl,
                total_rows,
                data_path,
                benchmark_queries,
                score_weights,
                top_n_winners,
                config_json
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
                existing_source_ddl,
                existing_total_rows,
                existing_data_path,
                existing_queries_json,
                existing_score_weights_json,
                existing_top_n,
                existing_config_json,
            ) = latest[0]
        else:
            existing_run_id = benchmark_run_id
            existing_benchmark_id = table_plan.benchmark_id
            existing_started_at = benchmark_finished_at
            existing_source_db = table_plan.database
            existing_source_table = table_plan.table
            existing_source_ddl = None
            existing_total_rows = None
            existing_data_path = None
            existing_queries_json = None
            existing_score_weights_json = None
            existing_top_n = int(table_plan.sequential_top_n)
            existing_config_json = None

        self._insert_run_row(
            run_record_id=run_record_id,
            benchmark_run_id=int(existing_run_id),
            benchmark_id=str(existing_benchmark_id),
            started_at=self._to_aware_utc_datetime(existing_started_at),
            finished_at=benchmark_finished_at,
            source_db_name=str(existing_source_db),
            source_table_name=str(existing_source_table),
            source_table_ddl=(
                str(existing_source_ddl) if existing_source_ddl is not None else None
            ),
            total_rows=(
                int(existing_total_rows)
                if existing_total_rows is not None
                else None
            ),
            data_path=str(existing_data_path) if existing_data_path is not None else None,
            benchmark_queries_json=(
                str(existing_queries_json) if existing_queries_json is not None else None
            ),
            score_weights_json=(
                str(existing_score_weights_json)
                if existing_score_weights_json is not None
                else None
            ),
            top_n_winners=int(existing_top_n) if existing_top_n is not None else None,
            config_json=str(existing_config_json) if existing_config_json is not None else None,
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
        source_table_ddl: Optional[str],
        total_rows: Optional[int],
        data_path: Optional[str],
        benchmark_queries_json: Optional[str],
        score_weights_json: Optional[str],
        top_n_winners: Optional[int],
        config_json: Optional[str],
    ) -> None:
        """Пишет snapshot run-контекста в `benchmark_runs` (upsert через ReplacingMergeTree)."""
        started_at_ch = self._to_naive_utc_datetime(started_at)
        finished_at_ch = self._to_naive_utc_datetime(finished_at)
        updated_at_ch = self._to_naive_utc_datetime(datetime.now(timezone.utc))
        row = (
            run_record_id,
            int(benchmark_run_id),
            str(benchmark_id),
            started_at_ch,
            finished_at_ch,
            str(source_db_name),
            str(source_table_name),
            source_table_ddl,
            int(total_rows) if total_rows is not None else None,
            data_path,
            benchmark_queries_json,
            score_weights_json,
            int(top_n_winners) if top_n_winners is not None else None,
            config_json,
            updated_at_ch,
        )
        self._client.insert(
            table=f"{self._database}.{self._runs_table}",
            data=[row],
            column_names=[
                "id",
                "benchmark_run_id",
                "benchmark_id",
                "started_at",
                "finished_at",
                "source_db_name",
                "source_table_name",
                "source_table_ddl",
                "total_rows",
                "data_path",
                "benchmark_queries",
                "score_weights",
                "top_n_winners",
                "config_json",
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

            summaries.append(
                StoredVariantSummary(
                    variant_table=str(variant_table),
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
        ranked = sorted(
            summaries,
            key=lambda summary: (
                summary.score is None,
                -(summary.score if summary.score is not None else 0.0),
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

    def max_benchmark_run_id(self) -> int:
        """Возвращает максимальный `benchmark_run_id` из таблицы результатов."""
        phased_rows = self._execute(
            f"SELECT max(benchmark_run_id) FROM `{self._database}`.`{self._phased_table}`"
        )
        phased_max = int(phased_rows[0][0]) if phased_rows and phased_rows[0][0] is not None else 0
        if self._legacy_table == self._phased_table:
            return phased_max
        legacy_rows = self._execute(
            f"SELECT max(benchmark_run_id) FROM `{self._database}`.`{self._legacy_table}`"
        )
        legacy_max = int(legacy_rows[0][0]) if legacy_rows and legacy_rows[0][0] is not None else 0
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
        tested_table_ddl = result.tested_table_ddl or tested_table_ddl_fallback
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
        size_bytes_total = (
            result.tested_table_consumed_compressed_size_bytes_with_indexes
            if result.tested_table_consumed_compressed_size_bytes_with_indexes is not None
            else result.tested_table_consumed_compressed_size_bytes_overall
        )
        size_bytes_by_column_json = (
            result.tested_table_consumed_compressed_size_bytes_by_each_column
            or result.tested_table_cols_sizes
        )
        size_bytes_indexes_json = result.tested_table_indexes_sizes

        return StoredBenchmarkResult(
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
            benchmark_id=benchmark_id,
            id=result.id or str(uuid4()),
            parent_id=parent_id,
            phase=phase,
            phase_name=resolved_phase_name,
            started_at=benchmark_started_at,
            finished_at=datetime.now(timezone.utc),
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
            source_table_consumed_compressed_size_bytes_overall=(
                result.source_table_consumed_compressed_size_bytes_overall
            ),
            source_table_consumed_compressed_size_bytes_overall_readable=(
                result.source_table_consumed_compressed_size_bytes_overall_readable
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
            tested_table_indexes_sizes_percent_from_col_size=(
                result.tested_table_indexes_sizes_percent_from_col_size
            ),
            extra_json=result.extra_json,
            variant_table=variant_table,
            variant_mode=variant_mode,
            variant_params=variant_params,
            rank_in_phase=None,
            is_top_n=False,
            score_calculation_json=result.score_calculation_json,
            score=result.score,
        )

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
    def _safe_str(value: Any, *, default: str) -> str:
        """Безопасно приводит значение к непустой строке с fallback."""
        if value is None:
            return default
        normalized = str(value).strip()
        if not normalized:
            return default
        return normalized

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
    ) -> int:
        """Возвращает top_n_winners из benchmark_runs (fallback=1)."""
        rows = self._execute(
            f"""
            SELECT top_n_winners
            FROM `{self._database}`.`{self._runs_table}`
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
        if not rows or rows[0][0] is None:
            return 1
        try:
            value = int(rows[0][0])
        except Exception:
            return 1
        return max(1, value)

    def _recalculate_phase_ranking(
        self,
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        phase: int,
    ) -> None:
        """Пересчитывает `rank_in_phase`/`is_top_n` для выбранной phase."""
        rows = self._execute(
            f"""
            SELECT id, score
            FROM `{self._database}`.`{self._table}`
            WHERE benchmark_run_id = %(benchmark_run_id)s
              AND benchmark_id = %(benchmark_id)s
              AND source_db_name = %(source_database)s
              AND source_table_name = %(source_table)s
              AND phase = %(phase)s
            """,
            {
                "benchmark_run_id": benchmark_run_id,
                "benchmark_id": benchmark_id,
                "source_database": source_database,
                "source_table": source_table,
                "phase": int(phase),
            },
        )
        if not rows:
            return

        top_n_winners = self._resolve_top_n_winners(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
        )
        ranked_rows = sorted(
            rows,
            key=lambda row: (
                row[1] is None,
                -(float(row[1]) if row[1] is not None else 0.0),
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
                WHERE benchmark_run_id = %(benchmark_run_id)s
                  AND benchmark_id = %(benchmark_id)s
                  AND source_db_name = %(source_database)s
                  AND source_table_name = %(source_table)s
                  AND phase = %(phase)s
                  AND id = %(id)s
                SETTINGS mutations_sync = 1
                """,
                {
                    "rank_in_phase": rank_index,
                    "is_top_n": rank_index <= top_n_winners,
                    "benchmark_run_id": benchmark_run_id,
                    "benchmark_id": benchmark_id,
                    "source_database": source_database,
                    "source_table": source_table,
                    "phase": int(phase),
                    "id": str(row_id),
                },
            )

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
    def _to_naive_utc_datetime(value: Optional[datetime]) -> Optional[datetime]:
        """Приводит datetime к naive UTC для ClickHouse DateTime64."""
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _to_aware_utc_datetime(value: Any) -> datetime:
        """Нормализует дату/время из ClickHouse к aware UTC datetime."""
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return datetime.now(timezone.utc)

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
                    recalculate_phase_ranking=True,
                )
            else:
                self._insert_phased_record(record)
            return
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
        row_map = self._record_to_clickhouse_map(record)
        row = tuple(row_map[column] for column in self._INSERT_COLUMNS)
        self._client.insert(
            table=f"{self._database}.{table_name}",
            data=[row],
            column_names=self._INSERT_COLUMNS,
        )
        if recalculate_phase_ranking and record.phase is not None:
            self._recalculate_phase_ranking(
                benchmark_run_id=record.benchmark_run_id,
                benchmark_id=record.benchmark_id,
                source_database=record.source_db_name,
                source_table=record.source_table_name,
                phase=int(record.phase),
            )

    def _insert_phased_record(self, record: StoredBenchmarkResult) -> None:
        """Сохраняет результат phased-стратегии в компактную phased-таблицу."""
        row_map = self._record_to_phased_clickhouse_map(record)
        row = tuple(row_map[column] for column in self._PHASED_INSERT_COLUMNS)
        self._client.insert(
            table=f"{self._database}.{self._phased_table}",
            data=[row],
            column_names=self._PHASED_INSERT_COLUMNS,
        )
        if record.phase is not None:
            self._recalculate_phase_ranking(
                benchmark_run_id=record.benchmark_run_id,
                benchmark_id=record.benchmark_id,
                source_database=record.source_db_name,
                source_table=record.source_table_name,
                phase=int(record.phase),
            )

    def _record_to_clickhouse_map(self, record: StoredBenchmarkResult) -> Dict[str, Any]:
        benchmark_started_at_utc = self._to_naive_utc_datetime(record.benchmark_started_at)
        started_at_utc = self._to_naive_utc_datetime(record.started_at)
        finished_at_utc = self._to_naive_utc_datetime(record.finished_at)

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
        benchmark_started_at_utc = self._to_naive_utc_datetime(record.benchmark_started_at)
        started_at_utc = self._to_naive_utc_datetime(record.started_at)
        finished_at_utc = self._to_naive_utc_datetime(record.finished_at)

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

        return {
            "benchmark_run_id": int(record.benchmark_run_id),
            "benchmark_started_at": benchmark_started_at_utc,
            "benchmark_id": str(record.benchmark_id),
            "id": str(record.id),
            "parent_id": record.parent_id,
            "phase": record.phase,
            "phase_name": record.phase_name,
            "started_at": started_at_utc,
            "finished_at": finished_at_utc,
            "source_db_name": str(record.source_db_name),
            "source_table_name": str(record.source_table_name),
            "tested_table_ddl": tested_table_ddl,
            "variant_params_json": self._pretty_json_string_or_as_is(variant_params_json),
            "variant_table": str(record.variant_table),
            "variant_mode": str(record.variant_mode),
            "variant_params": variant_params,
            "size_bytes_total": record.size_bytes_total,
            "size_bytes_by_column_json": size_bytes_by_column_json,
            "size_bytes_indexes_json": size_bytes_indexes_json,
            "select_metrics_json": select_metrics_json,
            "insert_metrics_json": insert_metrics_json,
            "score_calculation_json": score_calculation_json,
            "score": record.score,
            "rank_in_phase": record.rank_in_phase,
            "is_top_n": bool(record.is_top_n),
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
            ("select", "with", "show", "describe", "desc", "explain")
        )
