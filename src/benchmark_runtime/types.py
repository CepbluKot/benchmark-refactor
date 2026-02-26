"""Runtime immutable DTOs used across planner/engine/runner layers."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from src.clickhouse_ddl import TableDDL
from src.combiner import VariantMeta
from src.models import (
    BenchmarkMode,
    BenchmarkStrategy,
    CeleryConfig,
    ColumnOrderMode,
    InsertRowsLimitsConfig,
    QueriesConfig,
    ScoringConfig,
)
from src.resolver import ResolvedRules


class _FrozenModel(BaseModel):
    """Shared immutable base for runtime DTOs."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        arbitrary_types_allowed=True,
    )


class TableTarget(_FrozenModel):
    """Concrete table target (`database.table`) after selector expansion."""

    database: str
    table: str


class Query(_FrozenModel):
    """Benchmark SQL query descriptor."""

    query_id: str
    query: str
    cache_mode: str = "warm"
    select_operations_count: Optional[int] = None
    warmup_queries: List[str] = Field(default_factory=list)


class QueryPlan(_FrozenModel):
    """Test query set prepared for a variant table."""

    test_queries: List[Query]


class TableBenchmarkPlan(_FrozenModel):
    """Table-level plan produced by planner before variant generation."""

    benchmark_id: str
    connection_id: str
    connection_dbms: str
    database: str
    test_database: Optional[str] = None
    table: str
    strategy: BenchmarkStrategy
    mode: BenchmarkMode
    max_iterations: int
    sequential_top_n: int
    insert_rows_limit: Optional[int]
    source_insert_rows_limit: Optional[int] = None
    source_insert_rows_limits: Optional[InsertRowsLimitsConfig] = None
    insert_rows_limits: Optional[InsertRowsLimitsConfig]
    max_benchmarks_limits: Optional[InsertRowsLimitsConfig] = None
    max_type_benchmarks: Optional[int] = None
    max_index_benchmarks: Optional[int] = None
    index_granularity_values: Optional[List[int]] = None
    column_order_mode: Optional[ColumnOrderMode]
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    rules: ResolvedRules
    queries: QueriesConfig
    celery: CeleryConfig


class VariantJob(_FrozenModel):
    """Full execution unit for one DDL variant."""

    benchmark_run_id: int
    benchmark_started_at: datetime
    benchmark_id: str
    connection_id: str
    connection_dbms: str
    source_database: str
    variant_database: str
    source_table: str
    variant_table: str
    variant_meta: VariantMeta
    mode: BenchmarkMode
    max_iterations: int
    insert_rows_limit: Optional[int]
    total_variants: int
    variant_ddl: TableDDL
    source_benchmark: Optional["SourceBenchmarkResult"] = None
    query_plan: QueryPlan
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    celery: CeleryConfig


class SourceBenchmarkJob(_FrozenModel):
    """Execution unit for baseline benchmark on source (original) DDL."""

    benchmark_run_id: int
    benchmark_started_at: datetime
    benchmark_id: str
    connection_id: str
    connection_dbms: str
    source_database: str
    test_database: Optional[str] = None
    source_table: str
    source_table_ddl: TableDDL
    query_plan: QueryPlan
    max_iterations: int
    insert_rows_limit: Optional[int]
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    celery: CeleryConfig


class SourceBenchmarkResult(_FrozenModel):
    """Baseline benchmark result for source DDL, propagated to all variant jobs."""

    baseline_id: str = Field(default_factory=lambda: str(uuid4()))
    benchmark_run_id: int
    benchmark_started_at: Optional[datetime] = None
    benchmark_id: str
    source_database: str
    source_table: str
    source_table_ddl: str
    score_calculation_json: Optional[str] = None
    score: Optional[float] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)


class BenchmarkVariantResult(_FrozenModel):
    """Result returned by execution adapter for a single variant."""

    benchmark_run_id: int
    benchmark_started_at: Optional[datetime] = None
    benchmark_id: str
    source_database: str
    source_table: str
    variant_table: str
    variant_mode: Optional[str] = None
    variant_params: Dict[str, Any] = Field(default_factory=dict)
    source_table_ddl: Optional[str] = None
    tested_table_ddl: Optional[str] = None
    id: Optional[str] = None
    is_source_table_copy: Optional[bool] = None
    index_params: Optional[str] = None
    total_n_rows_in_tested_table: Optional[int] = None
    total_n_rows_in_source_table: Optional[int] = None
    measured_percentiles: List[int] = Field(default_factory=list)
    insert_test_n_rows: Optional[int] = None
    tested_table_insert_time_ms_measurements: List[float] = Field(default_factory=list)
    source_table_insert_time_ms_measurements: List[float] = Field(default_factory=list)
    tested_table_insert_time_ms_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    source_table_insert_time_ms_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs: List[float] = (
        Field(default_factory=list)
    )
    tested_table_insert_rows_per_second_measurements: List[float] = Field(
        default_factory=list
    )
    source_table_insert_rows_per_second_measurements: List[float] = Field(
        default_factory=list
    )
    tested_table_insert_rows_per_second_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    source_table_insert_rows_per_second_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    tested_table_insert_bytes_per_second_measurements: List[float] = Field(
        default_factory=list
    )
    tested_table_insert_bytes_per_second_measurements_readable: List[str] = Field(
        default_factory=list
    )
    source_table_insert_bytes_per_second_measurements: List[float] = Field(
        default_factory=list
    )
    source_table_insert_bytes_per_second_measurements_readable: List[str] = Field(
        default_factory=list
    )
    tested_table_insert_bytes_per_second_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    tested_table_insert_bytes_per_second_measurements_percentiles_readable: List[str] = (
        Field(default_factory=list)
    )
    source_table_insert_bytes_per_second_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    source_table_insert_bytes_per_second_measurements_percentiles_readable: List[str] = (
        Field(default_factory=list)
    )
    tested_table_insert_memory_usage_measurements: List[float] = Field(
        default_factory=list
    )
    tested_table_insert_memory_usage_measurements_readable: List[str] = Field(
        default_factory=list
    )
    source_table_insert_memory_usage_measurements: List[float] = Field(
        default_factory=list
    )
    source_table_insert_memory_usage_measurements_readable: List[str] = Field(
        default_factory=list
    )
    tested_table_insert_memory_usage_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    tested_table_insert_memory_usage_measurements_percentiles_readable: List[str] = Field(
        default_factory=list
    )
    source_table_insert_memory_usage_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    source_table_insert_memory_usage_measurements_percentiles_readable: List[str] = Field(
        default_factory=list
    )
    tested_table_select_test_query: Optional[str] = None
    source_table_select_test_query: Optional[str] = None
    tested_table_select_time_ms_measurements: List[float] = Field(default_factory=list)
    source_table_select_time_ms_measurements: List[float] = Field(default_factory=list)
    tested_table_select_time_ms_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    source_table_select_time_ms_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    tested_table_select_time_ms_measurements_percentiles_speed_up_coefs: List[float] = (
        Field(default_factory=list)
    )
    tested_table_select_rows_per_second_measurements: List[float] = Field(
        default_factory=list
    )
    source_table_select_rows_per_second_measurements: List[float] = Field(
        default_factory=list
    )
    tested_table_select_rows_per_second_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    source_table_select_rows_per_second_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    tested_table_select_bytes_per_second_measurements: List[float] = Field(
        default_factory=list
    )
    tested_table_select_bytes_per_second_measurements_readable: List[str] = Field(
        default_factory=list
    )
    source_table_select_bytes_per_second_measurements: List[float] = Field(
        default_factory=list
    )
    source_table_select_bytes_per_second_measurements_readable: List[str] = Field(
        default_factory=list
    )
    tested_table_select_bytes_per_second_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    tested_table_select_bytes_per_second_measurements_percentiles_readable: List[str] = (
        Field(default_factory=list)
    )
    source_table_select_bytes_per_second_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    source_table_select_bytes_per_second_measurements_percentiles_readable: List[str] = (
        Field(default_factory=list)
    )
    tested_table_select_memory_usage_measurements: List[float] = Field(
        default_factory=list
    )
    tested_table_select_memory_usage_measurements_readable: List[str] = Field(
        default_factory=list
    )
    source_table_select_memory_usage_measurements: List[float] = Field(
        default_factory=list
    )
    source_table_select_memory_usage_measurements_readable: List[str] = Field(
        default_factory=list
    )
    tested_table_select_memory_usage_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    tested_table_select_memory_usage_measurements_percentiles_readable: List[str] = Field(
        default_factory=list
    )
    source_table_select_memory_usage_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    source_table_select_memory_usage_measurements_percentiles_readable: List[str] = Field(
        default_factory=list
    )
    tested_table_select_metrics_by_query_json: Optional[str] = None
    source_table_select_metrics_by_query_json: Optional[str] = None
    tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json: Optional[str] = None
    tested_table_consumed_compressed_size_bytes_by_each_column: Optional[str] = None
    source_table_consumed_compressed_size_bytes_by_each_column: Optional[str] = None
    tested_table_consumed_compressed_size_bytes_overall: Optional[float] = None
    tested_table_consumed_compressed_size_bytes_overall_readable: Optional[str] = None
    tested_table_consumed_compressed_size_bytes_with_indexes: Optional[float] = Field(
        default=None,
        validation_alias=AliasChoices(
            "tested_table_consumed_compressed_size_bytes_with_indexes",
            "tested_table_total_size_bytes_with_indexes",
        ),
        serialization_alias="tested_table_consumed_compressed_size_bytes_with_indexes",
    )
    tested_table_consumed_compressed_size_bytes_with_indexes_readable: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "tested_table_consumed_compressed_size_bytes_with_indexes_readable",
            "tested_table_total_size_bytes_with_indexes_readable",
        ),
        serialization_alias="tested_table_consumed_compressed_size_bytes_with_indexes_readable",
    )
    source_table_consumed_compressed_size_bytes_overall: Optional[float] = None
    source_table_consumed_compressed_size_bytes_overall_readable: Optional[str] = None
    tested_table_compression_overall_coef: Optional[float] = None
    tested_table_compression_by_each_column_coef: Optional[str] = None
    source_table_n_rows_in_size_test: Optional[int] = None
    tested_table_n_rows_in_size_test: Optional[int] = None
    tested_table_cols_sizes: Optional[str] = None
    tested_table_indexes_sizes: Optional[str] = None
    tested_table_indexes_sizes_percent_from_col_size: Optional[str] = None
    extra_json: Optional[str] = None
    score_calculation_json: Optional[str] = None
    score: Optional[float] = None


class StoredBenchmarkResult(_FrozenModel):
    """
    Storage DTO aligned with CombinedBenchmarkResults-like schema.

    Includes run-level metadata (`benchmark_run_id`, `benchmark_started_at`,
    `benchmark_id`) and additional runtime fields used by top-N orchestration.
    """

    # ---------------------------  Run Metadata  ----------------------------
    benchmark_run_id: int
    benchmark_started_at: datetime
    benchmark_id: str

    # ---------------------------  Metadata  ----------------------------
    id: str = Field(default_factory=lambda: str(uuid4()))
    source_db_name: str
    source_table_name: str
    tested_table_ddl: str
    source_table_ddl: Optional[str] = None
    is_source_table_copy: Optional[bool] = None
    index_params: Optional[str] = None
    total_n_rows_in_tested_table: Optional[int] = None
    total_n_rows_in_source_table: Optional[int] = None
    measured_percentiles: List[int] = Field(default_factory=list)

    # ---------------------------  Insert test results  ----------------------------
    insert_test_n_rows: Optional[int] = None
    tested_table_insert_time_ms_measurements: List[float] = Field(default_factory=list)
    source_table_insert_time_ms_measurements: List[float] = Field(default_factory=list)
    tested_table_insert_time_ms_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    source_table_insert_time_ms_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs: List[float] = (
        Field(default_factory=list)
    )
    tested_table_insert_rows_per_second_measurements: List[float] = Field(
        default_factory=list
    )
    source_table_insert_rows_per_second_measurements: List[float] = Field(
        default_factory=list
    )
    tested_table_insert_rows_per_second_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    source_table_insert_rows_per_second_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    tested_table_insert_bytes_per_second_measurements: List[float] = Field(
        default_factory=list
    )
    tested_table_insert_bytes_per_second_measurements_readable: List[str] = Field(
        default_factory=list
    )
    source_table_insert_bytes_per_second_measurements: List[float] = Field(
        default_factory=list
    )
    source_table_insert_bytes_per_second_measurements_readable: List[str] = Field(
        default_factory=list
    )
    tested_table_insert_bytes_per_second_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    tested_table_insert_bytes_per_second_measurements_percentiles_readable: List[str] = (
        Field(default_factory=list)
    )
    source_table_insert_bytes_per_second_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    source_table_insert_bytes_per_second_measurements_percentiles_readable: List[str] = (
        Field(default_factory=list)
    )
    tested_table_insert_memory_usage_measurements: List[float] = Field(
        default_factory=list
    )
    tested_table_insert_memory_usage_measurements_readable: List[str] = Field(
        default_factory=list
    )
    source_table_insert_memory_usage_measurements: List[float] = Field(
        default_factory=list
    )
    source_table_insert_memory_usage_measurements_readable: List[str] = Field(
        default_factory=list
    )
    tested_table_insert_memory_usage_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    tested_table_insert_memory_usage_measurements_percentiles_readable: List[str] = Field(
        default_factory=list
    )
    source_table_insert_memory_usage_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    source_table_insert_memory_usage_measurements_percentiles_readable: List[str] = Field(
        default_factory=list
    )

    # ---------------------------  Select test results  ----------------------------
    tested_table_select_test_query: Optional[str] = None
    source_table_select_test_query: Optional[str] = None
    tested_table_select_time_ms_measurements: List[float] = Field(default_factory=list)
    source_table_select_time_ms_measurements: List[float] = Field(default_factory=list)
    tested_table_select_time_ms_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    source_table_select_time_ms_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    tested_table_select_time_ms_measurements_percentiles_speed_up_coefs: List[float] = (
        Field(default_factory=list)
    )
    tested_table_select_rows_per_second_measurements: List[float] = Field(
        default_factory=list
    )
    source_table_select_rows_per_second_measurements: List[float] = Field(
        default_factory=list
    )
    tested_table_select_rows_per_second_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    source_table_select_rows_per_second_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    tested_table_select_bytes_per_second_measurements: List[float] = Field(
        default_factory=list
    )
    tested_table_select_bytes_per_second_measurements_readable: List[str] = Field(
        default_factory=list
    )
    source_table_select_bytes_per_second_measurements: List[float] = Field(
        default_factory=list
    )
    source_table_select_bytes_per_second_measurements_readable: List[str] = Field(
        default_factory=list
    )
    tested_table_select_bytes_per_second_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    tested_table_select_bytes_per_second_measurements_percentiles_readable: List[str] = (
        Field(default_factory=list)
    )
    source_table_select_bytes_per_second_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    source_table_select_bytes_per_second_measurements_percentiles_readable: List[str] = (
        Field(default_factory=list)
    )
    tested_table_select_memory_usage_measurements: List[float] = Field(
        default_factory=list
    )
    tested_table_select_memory_usage_measurements_readable: List[str] = Field(
        default_factory=list
    )
    source_table_select_memory_usage_measurements: List[float] = Field(
        default_factory=list
    )
    source_table_select_memory_usage_measurements_readable: List[str] = Field(
        default_factory=list
    )
    tested_table_select_memory_usage_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    tested_table_select_memory_usage_measurements_percentiles_readable: List[str] = Field(
        default_factory=list
    )
    source_table_select_memory_usage_measurements_percentiles: List[float] = Field(
        default_factory=list
    )
    source_table_select_memory_usage_measurements_percentiles_readable: List[str] = Field(
        default_factory=list
    )
    tested_table_select_metrics_by_query_json: Optional[str] = None
    source_table_select_metrics_by_query_json: Optional[str] = None
    tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json: Optional[str] = None

    # ---------------------------  Compression results  ----------------------------
    tested_table_consumed_compressed_size_bytes_by_each_column: Optional[str] = None
    source_table_consumed_compressed_size_bytes_by_each_column: Optional[str] = None
    tested_table_consumed_compressed_size_bytes_overall: Optional[float] = None
    tested_table_consumed_compressed_size_bytes_overall_readable: Optional[str] = None
    tested_table_consumed_compressed_size_bytes_with_indexes: Optional[float] = Field(
        default=None,
        validation_alias=AliasChoices(
            "tested_table_consumed_compressed_size_bytes_with_indexes",
            "tested_table_total_size_bytes_with_indexes",
        ),
        serialization_alias="tested_table_consumed_compressed_size_bytes_with_indexes",
    )
    tested_table_consumed_compressed_size_bytes_with_indexes_readable: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "tested_table_consumed_compressed_size_bytes_with_indexes_readable",
            "tested_table_total_size_bytes_with_indexes_readable",
        ),
        serialization_alias="tested_table_consumed_compressed_size_bytes_with_indexes_readable",
    )
    source_table_consumed_compressed_size_bytes_overall: Optional[float] = None
    source_table_consumed_compressed_size_bytes_overall_readable: Optional[str] = None
    tested_table_compression_overall_coef: Optional[float] = None
    tested_table_compression_by_each_column_coef: Optional[str] = None
    source_table_n_rows_in_size_test: Optional[int] = None
    tested_table_n_rows_in_size_test: Optional[int] = None

    # ---------------------------  Indexes results  ----------------------------
    tested_table_cols_sizes: Optional[str] = None
    tested_table_indexes_sizes: Optional[str] = None
    tested_table_indexes_sizes_percent_from_col_size: Optional[str] = None

    # ---------------------------  Additional / Compatibility  ----------------------------
    extra_json: Optional[str] = None
    variant_table: str
    variant_mode: str
    variant_params: Dict[str, Any] = Field(default_factory=dict)
    score_calculation_json: Optional[str] = None
    score: Optional[float] = None

    @property
    def source_database(self) -> str:
        """Backward-compatible alias for previous DTO field name."""
        return self.source_db_name

    @property
    def source_table(self) -> str:
        """Backward-compatible alias for previous DTO field name."""
        return self.source_table_name


class TopTypeVariant(_FrozenModel):
    """Top-N candidate from type stage for sequential index stage."""

    variant_index: int
    variant_ddl: TableDDL
    score: Optional[float] = None


def build_variant_params(variant_meta: VariantMeta) -> Dict[str, Any]:
    """
    Builds stable JSON-like params for the currently tested variant.

    The params dict is intended for result stores (e.g. ClickHouse) and is
    based on normalized `VariantMeta` content.
    """
    column_choices: Dict[str, Dict[str, Optional[str]]] = {}
    for column_name, choice in variant_meta.column_choices.items():
        selected_type: Optional[str]
        selected_codec: Optional[str]
        if isinstance(choice, tuple):
            selected_type, selected_codec = choice
        else:
            selected_type = None
            selected_codec = None
        column_choices[column_name] = {
            "type": selected_type,
            "codec": selected_codec,
        }

    index_choices: Dict[str, Optional[Dict[str, Optional[str]]]] = {}
    for column_name, index_def in variant_meta.index_choices.items():
        if index_def is None:
            index_choices[column_name] = None
            continue
        index_choices[column_name] = {
            "name": index_def.name,
            "expr": index_def.expr,
            "index_type": index_def.index_type,
            "granularity": index_def.granularity,
        }

    return {
        "mode": variant_meta.mode,
        "global_index": variant_meta.global_index,
        "table_index_granularity": variant_meta.table_index_granularity,
        "column_choices": column_choices,
        "index_choices": index_choices,
    }


def _extract_ordered_index_params(index_choices: Any) -> List[str]:
    """Извлекает уникальные index params в стабильном порядке из `index_choices`."""
    if not isinstance(index_choices, dict):
        return []

    seen: set[str] = set()
    ordered_params: list[str] = []

    for index_payload in index_choices.values():
        if not isinstance(index_payload, dict):
            continue
        index_type = index_payload.get("index_type") or index_payload.get("type")
        if index_type is None:
            continue
        index_type_str = str(index_type).strip()
        if not index_type_str:
            continue

        granularity = index_payload.get("granularity")
        if granularity is None or str(granularity).strip() == "":
            candidate = index_type_str
        else:
            candidate = f"{index_type_str} GRANULARITY {granularity}"

        if candidate in seen:
            continue
        seen.add(candidate)
        ordered_params.append(candidate)
    return ordered_params


def build_legacy_index_params(index_choices: Any) -> Optional[str]:
    """
    Формирует legacy-строку `index_params` из `index_choices`.

    Формат совместим с первой версией:
    `"<index_type> GRANULARITY <n>"`.
    Если в варианте несколько разных индексов, строки объединяются через `; `.
    """
    ordered_params = _extract_ordered_index_params(index_choices)
    if not ordered_params:
        return None
    return "; ".join(ordered_params)


def build_index_params_json(
    variant_table: str,
    index_choices: Any,
) -> Optional[str]:
    """
    Формирует `index_params` в JSON-формате для хранения в БД.

    Формат:
      - `{ "<variant_table>": "<index>" }` для одного индекса;
      - `{ "<variant_table>": ["<index1>", "<index2>", ...] }` для нескольких.
    """
    ordered_params = _extract_ordered_index_params(index_choices)
    if not ordered_params:
        return None
    value: str | List[str]
    if len(ordered_params) == 1:
        value = ordered_params[0]
    else:
        value = ordered_params
    return json.dumps(
        {variant_table: value},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=str,
    )
