"""In-memory result store implementation."""

from __future__ import annotations

from typing import List, Optional, Sequence
from uuid import uuid4

from src.naming import parse_variant_name
from src.clickhouse_ddl import TableDDL

from ...contracts.result_store import BenchmarkResultStore
from ...types import (
    BenchmarkVariantResult,
    StoredVariantSummary,
    StoredBenchmarkResult,
    TopTypeVariant,
    VariantJob,
    build_variant_params,
)


class InMemoryBenchmarkResultStore(BenchmarkResultStore):
    """In-memory result store implementation for tests and dry-run flows."""

    def __init__(self) -> None:
        self._records: List[StoredBenchmarkResult] = []

    @property
    def records(self) -> List[StoredBenchmarkResult]:
        """Returns a copy of persisted records."""
        return list(self._records)

    def store_result(
        self,
        job: VariantJob,
        result: BenchmarkVariantResult,
    ) -> None:
        """Stores result and the effective variant DDL snapshot."""
        if result.benchmark_run_id != job.benchmark_run_id:
            raise ValueError(
                "result.benchmark_run_id не совпадает с job.benchmark_run_id"
            )
        if (
            result.benchmark_started_at is not None
            and result.benchmark_started_at != job.benchmark_started_at
        ):
            raise ValueError(
                "result.benchmark_started_at не совпадает с job.benchmark_started_at"
            )
        if result.benchmark_id != job.benchmark_id:
            raise ValueError("result.benchmark_id не совпадает с job.benchmark_id")

        variant_params = (
            dict(result.variant_params)
            if result.variant_params
            else build_variant_params(job.variant_meta)
        )
        tested_table_ddl = result.tested_table_ddl or job.variant_ddl.to_ddl()
        variant_mode = result.variant_mode or job.variant_meta.mode

        self._records.append(
            StoredBenchmarkResult(
                benchmark_run_id=job.benchmark_run_id,
                benchmark_started_at=job.benchmark_started_at,
                benchmark_id=job.benchmark_id,
                started_at=job.benchmark_started_at,
                id=result.id or str(uuid4()),
                source_db_name=job.source_database,
                source_table_name=job.source_table,
                tested_table_ddl=tested_table_ddl,
                variant_params_json=None,
                source_table_ddl=result.source_table_ddl,
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
                tested_table_insert_metrics_json=result.tested_table_insert_metrics_json,
                source_table_insert_metrics_json=result.source_table_insert_metrics_json,
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
                tested_table_select_metrics_by_query_json=(
                    result.tested_table_select_metrics_by_query_json
                ),
                source_table_select_metrics_by_query_json=(
                    result.source_table_select_metrics_by_query_json
                ),
                tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json=(
                    result.tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json
                ),
                select_metrics_json=result.tested_table_select_metrics_by_query_json,
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
                size_bytes_total=(
                    result.tested_table_consumed_compressed_size_bytes_with_indexes
                    if result.tested_table_consumed_compressed_size_bytes_with_indexes is not None
                    else result.tested_table_consumed_compressed_size_bytes_overall
                ),
                size_bytes_by_column_json=(
                    result.tested_table_consumed_compressed_size_bytes_by_each_column
                    or result.tested_table_cols_sizes
                ),
                size_bytes_indexes_json=result.tested_table_indexes_sizes,
                tested_table_cols_sizes=result.tested_table_cols_sizes,
                tested_table_indexes_sizes=result.tested_table_indexes_sizes,
                tested_table_indexes_sizes_percent_from_col_size=(
                    result.tested_table_indexes_sizes_percent_from_col_size
                ),
                insert_metrics_json=result.tested_table_insert_metrics_json,
                extra_json=result.extra_json,
                variant_table=job.variant_table,
                variant_mode=variant_mode,
                variant_params=variant_params,
                score_calculation_json=result.score_calculation_json,
                score=result.score,
            )
        )

    def get_top_type_variants(
        self,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        top_n: int,
    ) -> List[TopTypeVariant]:
        """Ranks and returns top-N type variants."""
        return self.get_top_variants(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            top_n=top_n,
            variant_modes=["types"],
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
        """Возвращает summary записей по фильтрам run/benchmark/table/mode."""
        mode_filter = {
            str(mode).strip()
            for mode in (variant_modes or [])
            if str(mode).strip()
        }
        records = [
            record
            for record in self._records
            if record.benchmark_run_id == benchmark_run_id
            and record.benchmark_id == benchmark_id
            and record.source_database == source_database
            and record.source_table == source_table
            and (not mode_filter or record.variant_mode in mode_filter)
        ]
        return [
            StoredVariantSummary(
                variant_table=record.variant_table,
                tested_table_ddl=record.tested_table_ddl,
                variant_mode=record.variant_mode,
                score=record.score,
                variant_params=dict(record.variant_params),
            )
            for record in records
        ]

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
        """Ranks and returns top-N variants for requested variant modes."""
        if top_n <= 0:
            return []

        summaries = self.list_variant_summaries(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            variant_modes=variant_modes,
        )
        ranked = sorted(
            summaries,
            key=lambda record: (
                record.score is None,
                -(record.score if record.score is not None else 0.0),
                _variant_index_from_variant_table(record.variant_table),
            ),
        )
        return [
            TopTypeVariant(
                variant_index=_variant_index_from_variant_table(summary.variant_table),
                variant_ddl=TableDDL.from_ddl(summary.tested_table_ddl),
                score=summary.score,
            )
            for summary in ranked[:top_n]
        ]


def _variant_index_from_variant_table(name: str) -> int:
    parsed = parse_variant_name(name)
    if parsed is None:
        return 0
    return parsed[2]
