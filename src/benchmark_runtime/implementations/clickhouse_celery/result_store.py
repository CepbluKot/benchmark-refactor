"""ClickHouse-backed result store для benchmark runtime."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from src.clickhouse_ddl import TableDDL
from src.models import ConnectionConfig
from src.naming import parse_variant_name

from ...contracts.result_store import BenchmarkResultStore
from ...types import (
    BenchmarkVariantResult,
    StoredBenchmarkResult,
    TopTypeVariant,
    VariantJob,
    build_legacy_index_params,
    build_variant_params,
)
from .common import json_dumps

logger = logging.getLogger(__name__)


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

    _INSERT_COLUMNS: list[str] = [
        "benchmark_run_id",
        "benchmark_started_at",
        "benchmark_id",
        "id",
        "source_db_name",
        "source_table_name",
        "tested_table_ddl",
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
        "tested_table_insert_memory_usage_measurements",
        "tested_table_insert_memory_usage_measurements_readable",
        "source_table_insert_memory_usage_measurements",
        "source_table_insert_memory_usage_measurements_readable",
        "tested_table_insert_memory_usage_measurements_percentiles",
        "tested_table_insert_memory_usage_measurements_percentiles_readable",
        "source_table_insert_memory_usage_measurements_percentiles",
        "source_table_insert_memory_usage_measurements_percentiles_readable",
        "tested_table_select_test_query",
        "source_table_select_test_query",
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
        "tested_table_select_memory_usage_measurements",
        "tested_table_select_memory_usage_measurements_readable",
        "source_table_select_memory_usage_measurements",
        "source_table_select_memory_usage_measurements_readable",
        "tested_table_select_memory_usage_measurements_percentiles",
        "tested_table_select_memory_usage_measurements_percentiles_readable",
        "source_table_select_memory_usage_measurements_percentiles",
        "source_table_select_memory_usage_measurements_percentiles_readable",
        "tested_table_select_metrics_by_query_json",
        "source_table_select_metrics_by_query_json",
        "tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json",
        "tested_table_consumed_compressed_size_bytes_by_each_column",
        "source_table_consumed_compressed_size_bytes_by_each_column",
        "tested_table_consumed_compressed_size_bytes_overall",
        "tested_table_consumed_compressed_size_bytes_overall_readable",
        "source_table_consumed_compressed_size_bytes_overall",
        "source_table_consumed_compressed_size_bytes_overall_readable",
        "tested_table_compression_overall_coef",
        "tested_table_compression_by_each_column_coef",
        "source_table_n_rows_in_size_test",
        "tested_table_n_rows_in_size_test",
        "tested_table_cols_sizes",
        "tested_table_indexes_sizes",
        "tested_table_indexes_sizes_percent_from_col_size",
        "extra_json",
        "variant_table",
        "variant_mode",
        "variant_params",
        "score_calculation_json",
        "score",
    ]
    _PRETTY_JSON_STRING_COLUMNS: tuple[str, ...] = (
        "tested_table_select_metrics_by_query_json",
        "source_table_select_metrics_by_query_json",
        "tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json",
        "tested_table_consumed_compressed_size_bytes_by_each_column",
        "source_table_consumed_compressed_size_bytes_by_each_column",
        "tested_table_compression_by_each_column_coef",
        "tested_table_cols_sizes",
        "score_calculation_json",
    )

    def __init__(
        self,
        connection: ConnectionConfig | ClickHouseConnectionParams,
        database: str = "benchmark_results",
        table: str = "combined_benchmark_results",
        *,
        create_table_if_missing: bool = True,
    ) -> None:
        if isinstance(connection, ConnectionConfig):
            self._connection = ClickHouseConnectionParams.from_connection_config(connection)
        else:
            self._connection = connection
        self._database = database
        self._table = table
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
        return self._table

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
            CREATE TABLE IF NOT EXISTS `{self._database}`.`{self._table}`
            (
                `benchmark_run_id` Int32,
                `benchmark_started_at` DateTime64(3, 'UTC'),
                `benchmark_id` String,
                `id` String,
                `source_db_name` String,
                `source_table_name` String,
                `tested_table_ddl` String,
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
                `tested_table_insert_memory_usage_measurements` Array(Float64),
                `tested_table_insert_memory_usage_measurements_readable` Array(String),
                `source_table_insert_memory_usage_measurements` Array(Float64),
                `source_table_insert_memory_usage_measurements_readable` Array(String),
                `tested_table_insert_memory_usage_measurements_percentiles` Array(Float64),
                `tested_table_insert_memory_usage_measurements_percentiles_readable` Array(String),
                `source_table_insert_memory_usage_measurements_percentiles` Array(Float64),
                `source_table_insert_memory_usage_measurements_percentiles_readable` Array(String),
                `tested_table_select_test_query` Nullable(String),
                `source_table_select_test_query` Nullable(String),
                `tested_table_select_time_ms_measurements` Array(Float64),
                `source_table_select_time_ms_measurements` Array(Float64),
                `tested_table_select_time_ms_measurements_percentiles` Array(Float64),
                `source_table_select_time_ms_measurements_percentiles` Array(Float64),
                `tested_table_select_time_ms_measurements_percentiles_speed_up_coefs` Array(Float64),
                `tested_table_select_rows_per_second_measurements` Array(Float64),
                `source_table_select_rows_per_second_measurements` Array(Float64),
                `tested_table_select_rows_per_second_measurements_percentiles` Array(Float64),
                `source_table_select_rows_per_second_measurements_percentiles` Array(Float64),
                `tested_table_select_bytes_per_second_measurements` Array(Float64),
                `tested_table_select_bytes_per_second_measurements_readable` Array(String),
                `source_table_select_bytes_per_second_measurements` Array(Float64),
                `source_table_select_bytes_per_second_measurements_readable` Array(String),
                `tested_table_select_bytes_per_second_measurements_percentiles` Array(Float64),
                `tested_table_select_bytes_per_second_measurements_percentiles_readable` Array(String),
                `source_table_select_bytes_per_second_measurements_percentiles` Array(Float64),
                `source_table_select_bytes_per_second_measurements_percentiles_readable` Array(String),
                `tested_table_select_memory_usage_measurements` Array(Float64),
                `tested_table_select_memory_usage_measurements_readable` Array(String),
                `source_table_select_memory_usage_measurements` Array(Float64),
                `source_table_select_memory_usage_measurements_readable` Array(String),
                `tested_table_select_memory_usage_measurements_percentiles` Array(Float64),
                `tested_table_select_memory_usage_measurements_percentiles_readable` Array(String),
                `source_table_select_memory_usage_measurements_percentiles` Array(Float64),
                `source_table_select_memory_usage_measurements_percentiles_readable` Array(String),
                `tested_table_select_metrics_by_query_json` Nullable(String),
                `source_table_select_metrics_by_query_json` Nullable(String),
                `tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json` Nullable(String),
                `tested_table_consumed_compressed_size_bytes_by_each_column` Nullable(String),
                `source_table_consumed_compressed_size_bytes_by_each_column` Nullable(String),
                `tested_table_consumed_compressed_size_bytes_overall` Nullable(Float64),
                `tested_table_consumed_compressed_size_bytes_overall_readable` Nullable(String),
                `source_table_consumed_compressed_size_bytes_overall` Nullable(Float64),
                `source_table_consumed_compressed_size_bytes_overall_readable` Nullable(String),
                `tested_table_compression_overall_coef` Nullable(Float64),
                `tested_table_compression_by_each_column_coef` Nullable(String),
                `source_table_n_rows_in_size_test` Nullable(Int64),
                `tested_table_n_rows_in_size_test` Nullable(Int64),
                `tested_table_cols_sizes` Nullable(String),
                `tested_table_indexes_sizes` Nullable(String),
                `tested_table_indexes_sizes_percent_from_col_size` Nullable(String),
                `extra_json` Nullable(String),
                `variant_table` String,
                `variant_mode` String,
                `variant_params` String,
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
            ALTER TABLE `{self._database}`.`{self._table}`
                ADD COLUMN IF NOT EXISTS `tested_table_select_metrics_by_query_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `source_table_select_metrics_by_query_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json` Nullable(String),
                ADD COLUMN IF NOT EXISTS `tested_table_insert_memory_usage_measurements` Array(Float64),
                ADD COLUMN IF NOT EXISTS `tested_table_insert_memory_usage_measurements_readable` Array(String),
                ADD COLUMN IF NOT EXISTS `source_table_insert_memory_usage_measurements` Array(Float64),
                ADD COLUMN IF NOT EXISTS `source_table_insert_memory_usage_measurements_readable` Array(String),
                ADD COLUMN IF NOT EXISTS `tested_table_insert_memory_usage_measurements_percentiles` Array(Float64),
                ADD COLUMN IF NOT EXISTS `tested_table_insert_memory_usage_measurements_percentiles_readable` Array(String),
                ADD COLUMN IF NOT EXISTS `source_table_insert_memory_usage_measurements_percentiles` Array(Float64),
                ADD COLUMN IF NOT EXISTS `source_table_insert_memory_usage_measurements_percentiles_readable` Array(String),
                ADD COLUMN IF NOT EXISTS `tested_table_select_memory_usage_measurements` Array(Float64),
                ADD COLUMN IF NOT EXISTS `tested_table_select_memory_usage_measurements_readable` Array(String),
                ADD COLUMN IF NOT EXISTS `source_table_select_memory_usage_measurements` Array(Float64),
                ADD COLUMN IF NOT EXISTS `source_table_select_memory_usage_measurements_readable` Array(String),
                ADD COLUMN IF NOT EXISTS `tested_table_select_memory_usage_measurements_percentiles` Array(Float64),
                ADD COLUMN IF NOT EXISTS `tested_table_select_memory_usage_measurements_percentiles_readable` Array(String),
                ADD COLUMN IF NOT EXISTS `source_table_select_memory_usage_measurements_percentiles` Array(Float64),
                ADD COLUMN IF NOT EXISTS `source_table_select_memory_usage_measurements_percentiles_readable` Array(String),
                ADD COLUMN IF NOT EXISTS `score_calculation_json` Nullable(String)
            """
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
        self._insert_record(record)

    def store_worker_result(
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
        self._insert_record(record)

    def get_top_type_variants(
        self,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        top_n: int,
    ) -> List[TopTypeVariant]:
        """Возвращает top-N type-вариантов, отсортированных по score."""
        if top_n <= 0:
            return []

        rows = self._execute(
            f"""
            SELECT
                variant_table,
                tested_table_ddl,
                score
            FROM `{self._database}`.`{self._table}`
            WHERE benchmark_run_id = %(benchmark_run_id)s
              AND benchmark_id = %(benchmark_id)s
              AND source_db_name = %(source_database)s
              AND source_table_name = %(source_table)s
              AND variant_mode = 'types'
            ORDER BY isNull(score) ASC, score DESC, variant_table ASC
            LIMIT %(top_n)s
            """,
            {
                "benchmark_run_id": benchmark_run_id,
                "benchmark_id": benchmark_id,
                "source_database": source_database,
                "source_table": source_table,
                "top_n": top_n,
            },
        )

        top_variants: list[TopTypeVariant] = []
        for variant_table, tested_table_ddl, score in rows:
            parsed_name = parse_variant_name(variant_table)
            variant_index = parsed_name[2] if parsed_name else 0
            try:
                variant_ddl = TableDDL.from_ddl(tested_table_ddl)
            except Exception:
                logger.exception(
                    "ClickHouseBenchmarkResultStore: не удалось распарсить tested_table_ddl "
                    "(benchmark=%s, table=%s, variant=%s)",
                    benchmark_id,
                    f"{source_database}.{source_table}",
                    variant_table,
                )
                continue

            top_variants.append(
                TopTypeVariant(
                    variant_index=variant_index,
                    variant_ddl=variant_ddl,
                    score=float(score) if score is not None else None,
                )
            )
        return top_variants

    def max_benchmark_run_id(self) -> int:
        """Возвращает максимальный `benchmark_run_id` из таблицы результатов."""
        rows = self._execute(
            f"SELECT max(benchmark_run_id) FROM `{self._database}`.`{self._table}`"
        )
        if not rows or rows[0][0] is None:
            return 0
        return int(rows[0][0])

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

        index_params = result.index_params
        if index_params is None:
            index_choices = variant_params.get("index_choices")
            if index_choices is not None:
                index_params = build_legacy_index_params(index_choices)

        return StoredBenchmarkResult(
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
            benchmark_id=benchmark_id,
            id=result.id or str(uuid4()),
            source_db_name=source_database,
            source_table_name=source_table,
            tested_table_ddl=tested_table_ddl,
            source_table_ddl=result.source_table_ddl or source_table_ddl_fallback,
            is_source_table_copy=result.is_source_table_copy,
            index_params=index_params,
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
            tested_table_insert_memory_usage_measurements=list(
                result.tested_table_insert_memory_usage_measurements
            ),
            tested_table_insert_memory_usage_measurements_readable=list(
                result.tested_table_insert_memory_usage_measurements_readable
            ),
            source_table_insert_memory_usage_measurements=list(
                result.source_table_insert_memory_usage_measurements
            ),
            source_table_insert_memory_usage_measurements_readable=list(
                result.source_table_insert_memory_usage_measurements_readable
            ),
            tested_table_insert_memory_usage_measurements_percentiles=list(
                result.tested_table_insert_memory_usage_measurements_percentiles
            ),
            tested_table_insert_memory_usage_measurements_percentiles_readable=list(
                result.tested_table_insert_memory_usage_measurements_percentiles_readable
            ),
            source_table_insert_memory_usage_measurements_percentiles=list(
                result.source_table_insert_memory_usage_measurements_percentiles
            ),
            source_table_insert_memory_usage_measurements_percentiles_readable=list(
                result.source_table_insert_memory_usage_measurements_percentiles_readable
            ),
            tested_table_select_test_query=result.tested_table_select_test_query,
            source_table_select_test_query=result.source_table_select_test_query,
            tested_table_select_time_ms_measurements=list(
                result.tested_table_select_time_ms_measurements
            ),
            source_table_select_time_ms_measurements=list(
                result.source_table_select_time_ms_measurements
            ),
            tested_table_select_time_ms_measurements_percentiles=list(
                result.tested_table_select_time_ms_measurements_percentiles
            ),
            source_table_select_time_ms_measurements_percentiles=list(
                result.source_table_select_time_ms_measurements_percentiles
            ),
            tested_table_select_time_ms_measurements_percentiles_speed_up_coefs=list(
                result.tested_table_select_time_ms_measurements_percentiles_speed_up_coefs
            ),
            tested_table_select_rows_per_second_measurements=list(
                result.tested_table_select_rows_per_second_measurements
            ),
            source_table_select_rows_per_second_measurements=list(
                result.source_table_select_rows_per_second_measurements
            ),
            tested_table_select_rows_per_second_measurements_percentiles=list(
                result.tested_table_select_rows_per_second_measurements_percentiles
            ),
            source_table_select_rows_per_second_measurements_percentiles=list(
                result.source_table_select_rows_per_second_measurements_percentiles
            ),
            tested_table_select_bytes_per_second_measurements=list(
                result.tested_table_select_bytes_per_second_measurements
            ),
            tested_table_select_bytes_per_second_measurements_readable=list(
                result.tested_table_select_bytes_per_second_measurements_readable
            ),
            source_table_select_bytes_per_second_measurements=list(
                result.source_table_select_bytes_per_second_measurements
            ),
            source_table_select_bytes_per_second_measurements_readable=list(
                result.source_table_select_bytes_per_second_measurements_readable
            ),
            tested_table_select_bytes_per_second_measurements_percentiles=list(
                result.tested_table_select_bytes_per_second_measurements_percentiles
            ),
            tested_table_select_bytes_per_second_measurements_percentiles_readable=list(
                result.tested_table_select_bytes_per_second_measurements_percentiles_readable
            ),
            source_table_select_bytes_per_second_measurements_percentiles=list(
                result.source_table_select_bytes_per_second_measurements_percentiles
            ),
            source_table_select_bytes_per_second_measurements_percentiles_readable=list(
                result.source_table_select_bytes_per_second_measurements_percentiles_readable
            ),
            tested_table_select_memory_usage_measurements=list(
                result.tested_table_select_memory_usage_measurements
            ),
            tested_table_select_memory_usage_measurements_readable=list(
                result.tested_table_select_memory_usage_measurements_readable
            ),
            source_table_select_memory_usage_measurements=list(
                result.source_table_select_memory_usage_measurements
            ),
            source_table_select_memory_usage_measurements_readable=list(
                result.source_table_select_memory_usage_measurements_readable
            ),
            tested_table_select_memory_usage_measurements_percentiles=list(
                result.tested_table_select_memory_usage_measurements_percentiles
            ),
            tested_table_select_memory_usage_measurements_percentiles_readable=list(
                result.tested_table_select_memory_usage_measurements_percentiles_readable
            ),
            source_table_select_memory_usage_measurements_percentiles=list(
                result.source_table_select_memory_usage_measurements_percentiles
            ),
            source_table_select_memory_usage_measurements_percentiles_readable=list(
                result.source_table_select_memory_usage_measurements_percentiles_readable
            ),
            tested_table_select_metrics_by_query_json=(
                result.tested_table_select_metrics_by_query_json
            ),
            source_table_select_metrics_by_query_json=(
                result.source_table_select_metrics_by_query_json
            ),
            tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json=(
                result.tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json
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
            tested_table_cols_sizes=result.tested_table_cols_sizes,
            tested_table_indexes_sizes=result.tested_table_indexes_sizes,
            tested_table_indexes_sizes_percent_from_col_size=(
                result.tested_table_indexes_sizes_percent_from_col_size
            ),
            extra_json=result.extra_json,
            variant_table=variant_table,
            variant_mode=variant_mode,
            variant_params=variant_params,
            score_calculation_json=result.score_calculation_json,
            score=result.score,
        )

    def _insert_record(self, record: StoredBenchmarkResult) -> None:
        row_map = self._record_to_clickhouse_map(record)
        row = tuple(row_map[column] for column in self._INSERT_COLUMNS)
        self._client.insert(
            table=f"{self._database}.{self._table}",
            data=[row],
            column_names=self._INSERT_COLUMNS,
        )

    def _record_to_clickhouse_map(self, record: StoredBenchmarkResult) -> Dict[str, Any]:
        started_at_utc = record.benchmark_started_at
        if started_at_utc.tzinfo is not None:
            started_at_utc = started_at_utc.astimezone(timezone.utc).replace(tzinfo=None)

        row_map = {
            **record.model_dump(),
            "benchmark_started_at": started_at_utc,
            "variant_params": json.dumps(
                record.variant_params,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            ),
        }
        for column_name in self._PRETTY_JSON_STRING_COLUMNS:
            row_map[column_name] = self._pretty_json_string_or_as_is(
                row_map.get(column_name)
            )
        return row_map

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
