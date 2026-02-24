"""Runtime immutable DTOs used across planner/engine/runner layers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from clickhouse_ddl import TableDDL
from combiner import VariantMeta
from models import (
    BenchmarkMode,
    BenchmarkStrategy,
    CeleryConfig,
    ColumnOrderMode,
    InsertRowsLimitsConfig,
    QueriesConfig,
)
from resolver import ResolvedRules


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
    score: Optional[float] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class StoredBenchmarkResult(_FrozenModel):
    """Persistence-normalized result record for result-store implementations."""

    benchmark_run_id: int
    benchmark_started_at: datetime
    benchmark_id: str
    source_database: str
    source_table: str
    variant_table: str
    variant_index: int
    variant_mode: str
    score: Optional[float] = None
    variant_ddl: TableDDL
    payload: Dict[str, Any] = Field(default_factory=dict)


class TopTypeVariant(_FrozenModel):
    """Top-N candidate from type stage for sequential index stage."""

    variant_index: int
    variant_ddl: TableDDL
    score: Optional[float] = None
