"""In-memory result store implementation."""

from __future__ import annotations

import json
from typing import List
from uuid import uuid4

from ...contracts.result_store import BenchmarkResultStore
from ...types import (
    BenchmarkVariantResult,
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
        payload = dict(result.payload)
        payload_mode = payload.get("variant_mode")
        variant_mode = (
            payload_mode if isinstance(payload_mode, str) and payload_mode else job.variant_meta.mode
        )
        index_params = _payload_str(payload, "index_params")
        if index_params is None:
            index_choices = variant_params.get("index_choices")
            if index_choices is not None:
                index_params = json.dumps(index_choices, ensure_ascii=False, default=str)
        extra_json = _payload_str(payload, "extra_json")
        if extra_json is None and payload:
            extra_json = json.dumps(payload, ensure_ascii=False, default=str)

        self._records.append(
            StoredBenchmarkResult(
                benchmark_run_id=job.benchmark_run_id,
                benchmark_started_at=job.benchmark_started_at,
                benchmark_id=job.benchmark_id,
                id=_payload_str(payload, "id")
                or _payload_str(payload, "result_id")
                or str(uuid4()),
                source_db_name=job.source_database,
                source_table_name=job.source_table,
                variant_table=job.variant_table,
                variant_index=result.variant_index,
                variant_mode=variant_mode,
                variant_params=variant_params,
                source_table_ddl=result.source_table_ddl or _payload_str(payload, "source_table_ddl"),
                tested_table_ddl=tested_table_ddl,
                is_source_table_copy=_payload_bool(payload, "is_source_table_copy"),
                index_params=index_params,
                total_n_rows_in_tested_table=_payload_int(payload, "total_n_rows_in_tested_table"),
                total_n_rows_in_source_table=_payload_int(payload, "total_n_rows_in_source_table"),
                measured_percentiles=_payload_list(payload, "measured_percentiles", int),
                insert_test_n_rows=_payload_int(payload, "insert_test_n_rows"),
                tested_table_insert_time_ms_measurements=_payload_list(
                    payload,
                    "tested_table_insert_time_ms_measurements",
                    float,
                ),
                source_table_insert_time_ms_measurements=_payload_list(
                    payload,
                    "source_table_insert_time_ms_measurements",
                    float,
                ),
                tested_table_insert_time_ms_measurements_percentiles=_payload_list(
                    payload,
                    "tested_table_insert_time_ms_measurements_percentiles",
                    float,
                ),
                source_table_insert_time_ms_measurements_percentiles=_payload_list(
                    payload,
                    "source_table_insert_time_ms_measurements_percentiles",
                    float,
                ),
                tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs=_payload_list(
                    payload,
                    "tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs",
                    float,
                ),
                tested_table_insert_rows_per_second_measurements=_payload_list(
                    payload,
                    "tested_table_insert_rows_per_second_measurements",
                    float,
                ),
                source_table_insert_rows_per_second_measurements=_payload_list(
                    payload,
                    "source_table_insert_rows_per_second_measurements",
                    float,
                ),
                tested_table_insert_rows_per_second_measurements_percentiles=_payload_list(
                    payload,
                    "tested_table_insert_rows_per_second_measurements_percentiles",
                    float,
                ),
                source_table_insert_rows_per_second_measurements_percentiles=_payload_list(
                    payload,
                    "source_table_insert_rows_per_second_measurements_percentiles",
                    float,
                ),
                tested_table_insert_bytes_per_second_measurements=_payload_list(
                    payload,
                    "tested_table_insert_bytes_per_second_measurements",
                    float,
                ),
                tested_table_insert_bytes_per_second_measurements_readable=_payload_list(
                    payload,
                    "tested_table_insert_bytes_per_second_measurements_readable",
                    str,
                ),
                source_table_insert_bytes_per_second_measurements=_payload_list(
                    payload,
                    "source_table_insert_bytes_per_second_measurements",
                    float,
                ),
                source_table_insert_bytes_per_second_measurements_readable=_payload_list(
                    payload,
                    "source_table_insert_bytes_per_second_measurements_readable",
                    str,
                ),
                tested_table_insert_bytes_per_second_measurements_percentiles=_payload_list(
                    payload,
                    "tested_table_insert_bytes_per_second_measurements_percentiles",
                    float,
                ),
                tested_table_insert_bytes_per_second_measurements_percentiles_readable=_payload_list(
                    payload,
                    "tested_table_insert_bytes_per_second_measurements_percentiles_readable",
                    str,
                ),
                source_table_insert_bytes_per_second_measurements_percentiles=_payload_list(
                    payload,
                    "source_table_insert_bytes_per_second_measurements_percentiles",
                    float,
                ),
                source_table_insert_bytes_per_second_measurements_percentiles_readable=_payload_list(
                    payload,
                    "source_table_insert_bytes_per_second_measurements_percentiles_readable",
                    str,
                ),
                tested_table_select_test_query=_payload_str(payload, "tested_table_select_test_query"),
                source_table_select_test_query=_payload_str(payload, "source_table_select_test_query"),
                tested_table_select_time_ms_measurements=_payload_list(
                    payload,
                    "tested_table_select_time_ms_measurements",
                    float,
                ),
                source_table_select_time_ms_measurements=_payload_list(
                    payload,
                    "source_table_select_time_ms_measurements",
                    float,
                ),
                tested_table_select_time_ms_measurements_percentiles=_payload_list(
                    payload,
                    "tested_table_select_time_ms_measurements_percentiles",
                    float,
                ),
                source_table_select_time_ms_measurements_percentiles=_payload_list(
                    payload,
                    "source_table_select_time_ms_measurements_percentiles",
                    float,
                ),
                tested_table_select_time_ms_measurements_percentiles_speed_up_coefs=_payload_list(
                    payload,
                    "tested_table_select_time_ms_measurements_percentiles_speed_up_coefs",
                    float,
                ),
                tested_table_select_rows_per_second_measurements=_payload_list(
                    payload,
                    "tested_table_select_rows_per_second_measurements",
                    float,
                ),
                source_table_select_rows_per_second_measurements=_payload_list(
                    payload,
                    "source_table_select_rows_per_second_measurements",
                    float,
                ),
                tested_table_select_rows_per_second_measurements_percentiles=_payload_list(
                    payload,
                    "tested_table_select_rows_per_second_measurements_percentiles",
                    float,
                ),
                source_table_select_rows_per_second_measurements_percentiles=_payload_list(
                    payload,
                    "source_table_select_rows_per_second_measurements_percentiles",
                    float,
                ),
                tested_table_select_bytes_per_second_measurements=_payload_list(
                    payload,
                    "tested_table_select_bytes_per_second_measurements",
                    float,
                ),
                tested_table_select_bytes_per_second_measurements_readable=_payload_list(
                    payload,
                    "tested_table_select_bytes_per_second_measurements_readable",
                    str,
                ),
                source_table_select_bytes_per_second_measurements=_payload_list(
                    payload,
                    "source_table_select_bytes_per_second_measurements",
                    float,
                ),
                source_table_select_bytes_per_second_measurements_readable=_payload_list(
                    payload,
                    "source_table_select_bytes_per_second_measurements_readable",
                    str,
                ),
                tested_table_select_bytes_per_second_measurements_percentiles=_payload_list(
                    payload,
                    "tested_table_select_bytes_per_second_measurements_percentiles",
                    float,
                ),
                tested_table_select_bytes_per_second_measurements_percentiles_readable=_payload_list(
                    payload,
                    "tested_table_select_bytes_per_second_measurements_percentiles_readable",
                    str,
                ),
                source_table_select_bytes_per_second_measurements_percentiles=_payload_list(
                    payload,
                    "source_table_select_bytes_per_second_measurements_percentiles",
                    float,
                ),
                source_table_select_bytes_per_second_measurements_percentiles_readable=_payload_list(
                    payload,
                    "source_table_select_bytes_per_second_measurements_percentiles_readable",
                    str,
                ),
                tested_table_consumed_compressed_size_bytes_by_each_column=_payload_str(
                    payload,
                    "tested_table_consumed_compressed_size_bytes_by_each_column",
                ),
                source_table_consumed_compressed_size_bytes_by_each_column=_payload_str(
                    payload,
                    "source_table_consumed_compressed_size_bytes_by_each_column",
                ),
                tested_table_consumed_compressed_size_bytes_overall=_payload_float(
                    payload,
                    "tested_table_consumed_compressed_size_bytes_overall",
                ),
                tested_table_consumed_compressed_size_bytes_overall_readable=_payload_str(
                    payload,
                    "tested_table_consumed_compressed_size_bytes_overall_readable",
                ),
                source_table_consumed_compressed_size_bytes_overall=_payload_float(
                    payload,
                    "source_table_consumed_compressed_size_bytes_overall",
                ),
                source_table_consumed_compressed_size_bytes_overall_readable=_payload_str(
                    payload,
                    "source_table_consumed_compressed_size_bytes_overall_readable",
                ),
                tested_table_compression_overall_coef=_payload_float(
                    payload,
                    "tested_table_compression_overall_coef",
                ),
                tested_table_compression_by_each_column_coef=_payload_str(
                    payload,
                    "tested_table_compression_by_each_column_coef",
                ),
                source_table_n_rows_in_size_test=_payload_int(
                    payload,
                    "source_table_n_rows_in_size_test",
                ),
                tested_table_n_rows_in_size_test=_payload_int(
                    payload,
                    "tested_table_n_rows_in_size_test",
                ),
                tested_table_cols_sizes=_payload_str(payload, "tested_table_cols_sizes"),
                tested_table_indexes_sizes=_payload_str(payload, "tested_table_indexes_sizes"),
                tested_table_indexes_sizes_percent_from_col_size=_payload_str(
                    payload,
                    "tested_table_indexes_sizes_percent_from_col_size",
                ),
                extra_json=extra_json,
                score=result.score,
                variant_ddl=job.variant_ddl.copy(),
                payload=payload,
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
        if top_n <= 0:
            return []

        candidates = [
            record
            for record in self._records
            if record.benchmark_run_id == benchmark_run_id
            and record.benchmark_id == benchmark_id
            and record.source_database == source_database
            and record.source_table == source_table
            and record.variant_mode == "types"
        ]
        ranked = sorted(
            candidates,
            key=lambda record: (
                record.score is None,
                -(record.score if record.score is not None else 0.0),
                record.variant_index,
            ),
        )
        return [
            TopTypeVariant(
                variant_index=record.variant_index,
                variant_ddl=record.variant_ddl.copy(),
                score=record.score,
            )
            for record in ranked[:top_n]
        ]


def _payload_str(payload: dict, key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _payload_int(payload: dict, key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _payload_float(payload: dict, key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _payload_bool(payload: dict, key: str) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y"}:
            return True
        if normalized in {"0", "false", "no", "n"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _payload_list(payload: dict, key: str, cast_type):
    raw = payload.get(key)
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        try:
            out.append(cast_type(item))
        except (TypeError, ValueError):
            continue
    return out
