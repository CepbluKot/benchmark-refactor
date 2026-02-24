"""Runtime immutable DTOs used across planner/engine/runner layers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.clickhouse_ddl import TableDDL
from src.combiner import VariantMeta
from src.models import (
    BenchmarkMode,
    BenchmarkStrategy,
    CeleryConfig,
    ColumnOrderMode,
    InsertRowsLimitsConfig,
    QueriesConfig,
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

    query: str


class QueryPlan(_FrozenModel):
    """Warmup/test query set prepared for a variant table."""

    warmup_queries: List[str]
    test_queries: List[Query]


class TableBenchmarkPlan(_FrozenModel):
    """Table-level plan produced by planner before variant generation."""

    benchmark_id: str
    connection_id: str
    connection_dbms: str
    database: str
    table: str
    strategy: BenchmarkStrategy
    mode: BenchmarkMode
    max_iterations: int
    sequential_top_n: int
    insert_rows_limit: Optional[int]
    insert_rows_limits: Optional[InsertRowsLimitsConfig]
    column_order_mode: Optional[ColumnOrderMode]
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
    source_table: str
    variant_table: str
    variant_meta: VariantMeta
    mode: BenchmarkMode
    max_iterations: int
    insert_rows_limit: Optional[int]
    total_variants: int
    variant_ddl: TableDDL
    query_plan: QueryPlan
    celery: CeleryConfig


class BenchmarkVariantResult(_FrozenModel):
    """Result returned by execution adapter for a single variant."""

    benchmark_run_id: int
    benchmark_started_at: Optional[datetime] = None
    benchmark_id: str
    source_database: str
    source_table: str
    variant_table: str
    variant_index: int
    variant_params: Dict[str, Any] = Field(default_factory=dict)
    source_table_ddl: Optional[str] = None
    tested_table_ddl: Optional[str] = None
    score: Optional[float] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


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

    # ---------------------------  Compression results  ----------------------------
    tested_table_consumed_compressed_size_bytes_by_each_column: Optional[str] = None
    source_table_consumed_compressed_size_bytes_by_each_column: Optional[str] = None
    tested_table_consumed_compressed_size_bytes_overall: Optional[float] = None
    tested_table_consumed_compressed_size_bytes_overall_readable: Optional[str] = None
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
    variant_index: int
    variant_mode: str
    variant_params: Dict[str, Any] = Field(default_factory=dict)
    score: Optional[float] = None
    variant_ddl: TableDDL = Field(exclude=True)
    payload: Dict[str, Any] = Field(default_factory=dict, exclude=True)

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

    The payload is intended for result stores (e.g. ClickHouse) and is based
    on normalized `VariantMeta` content.
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
        "column_choices": column_choices,
        "index_choices": index_choices,
    }
