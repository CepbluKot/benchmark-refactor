"""Synthetic playground for debugging custom runtime implementations.

Запускает planner -> engine -> runner на синтетических DDL и synthetic config.
Скрипт нужен как отладочная база для своей реализации под ClickHouse:
  - MetadataProvider
  - BenchmarkExecutionAdapter
  - BenchmarkResultStore
  - BenchmarkRunIdProvider
  - TableExecutionStrategy
  - VariantGenerationStrategy

Можно запускать под дебаггером и ставить breakpoints в методах ниже.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from src.benchmark_engine import BenchmarkEngine, BenchmarkPlanner, BenchmarkRunner
from src.benchmark_runtime.contracts.execution import BenchmarkExecutionAdapter
from src.benchmark_runtime.contracts.metadata import MetadataProvider
from src.benchmark_runtime.contracts.result_store import BenchmarkResultStore
from src.benchmark_runtime.contracts.run_id import BenchmarkRunIdProvider
from src.benchmark_runtime.contracts.table_strategy import TableExecutionStrategy
from src.benchmark_runtime.table_strategy import (
    CombinedTableExecutionStrategy,
    DefaultTableExecutionStrategy,
    IndexesTableExecutionStrategy,
    SequentialTopNDispatchIndexesTableExecutionStrategy,
    SequentialTopNDispatchTypesTableExecutionStrategy,
    SequentialTopNTableExecutionStrategy,
    TypesTableExecutionStrategy,
)
from src.benchmark_runtime.types import (
    BenchmarkVariantResult,
    StoredBenchmarkResult,
    TableBenchmarkPlan,
    TopTypeVariant,
    VariantJob,
    build_variant_params,
)
from src.clickhouse_ddl import TableDDL
from src.column_rules import ColumnRule
from src.index_rules import IndexRule
from src.loader import parse_config_parts
from src.naming import parse_variant_name
from src.variant_generation import get_variant_generation_strategy, register_variant_generation_strategy
from src.variant_generation.contracts import VariantGenerationStrategy
from src.variant_generation.types import VariantMeta

EVENTS_DDL = """
CREATE TABLE analytics.events
(
    `user_id`    UInt64                  CODEC(Delta(8), LZ4),
    `event_time` DateTime                CODEC(DoubleDelta, ZSTD(1)),
    `event_type` LowCardinality(String)  CODEC(ZSTD(1)),
    `revenue`    Nullable(Decimal(18,4)) CODEC(ZSTD(1))
)
ENGINE = MergeTree
ORDER BY (user_id, event_time)
"""

SESSIONS_DDL = """
CREATE TABLE analytics.sessions
(
    `session_id` UInt64   CODEC(Delta(8), LZ4),
    `started_at` DateTime CODEC(DoubleDelta, ZSTD(1)),
    `duration_s` UInt32   CODEC(Delta(4), LZ4),
    `country`    String   CODEC(ZSTD(1))
)
ENGINE = MergeTree
ORDER BY (session_id, started_at)
"""


class SyntheticMetadataProvider(MetadataProvider):
    """Synthetic metadata provider (in-memory DDL + column sizes)."""

    def __init__(
        self,
        ddl_by_db_table: Dict[str, Dict[str, str]],
        column_sizes_by_db_table: Optional[Dict[str, Dict[str, Dict[str, int]]]] = None,
    ) -> None:
        self._ddl_by_db_table = ddl_by_db_table
        self._column_sizes_by_db_table = column_sizes_by_db_table or {}

    def list_databases(self) -> List[str]:
        return sorted(self._ddl_by_db_table.keys())

    def list_tables(self, database: str) -> List[str]:
        return sorted(self._ddl_by_db_table.get(database, {}).keys())

    def fetch_table_ddl(self, database: str, table: str) -> TableDDL:
        try:
            return TableDDL.from_ddl(self._ddl_by_db_table[database][table])
        except KeyError as exc:
            raise ValueError(f"Нет синтетического DDL для {database}.{table}") from exc

    def fetch_column_sizes(self, database: str, table: str) -> Dict[str, int]:
        return dict(self._column_sizes_by_db_table.get(database, {}).get(table, {}))


class SyntheticExecutionAdapter(BenchmarkExecutionAdapter):
    """Synthetic execution adapter with deterministic score model."""

    _INT_WIDTH = {
        "UInt8": 8,
        "UInt16": 16,
        "UInt32": 32,
        "UInt64": 64,
        "Int8": 8,
        "Int16": 16,
        "Int32": 32,
        "Int64": 64,
    }

    def __init__(self) -> None:
        self._store: BenchmarkResultStore | None = None

    def bind_result_store(self, result_store: BenchmarkResultStore | None) -> None:
        self._store = result_store

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        # Удобная точка для отладки execute-потока.
        score = self._score(job)
        stage = job.variant_meta.mode
        print(
            f"[adapter] run={job.benchmark_run_id} bench={job.benchmark_id} "
            f"table={job.source_database}.{job.source_table} stage={stage} "
            f"variant={job.variant_meta.global_index} score={score} "
            f"insert_rows_limit={job.insert_rows_limit}"
        )

        result = BenchmarkVariantResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            variant_mode=stage,
            score=score,
            tested_table_indexes_sizes=str(len(job.variant_ddl.indexes)),
        )
        if self._store is not None:
            # В проде это делает Celery-воркер; здесь сохраняем локально для дебага.
            self._store.store_result(job, result)
        return result

    @classmethod
    def _score(cls, job: VariantJob) -> float:
        """Deterministic synthetic score for stable replay in debugger."""
        base = 100.0 - float(job.variant_meta.global_index)
        type_bonus = 0.0
        zstd_bonus = 0.0
        for col in job.variant_ddl.columns:
            col_type = cls._unwrap_type(col.type)
            width = cls._INT_WIDTH.get(col_type)
            if width is not None:
                type_bonus += (64 - width) / 64.0
            if col.codec and "ZSTD" in col.codec.upper():
                zstd_bonus += 0.05

        idx_bonus = float(len(job.variant_ddl.indexes)) * 0.5
        stage = job.variant_meta.mode
        if stage == "types":
            return round(base + type_bonus + zstd_bonus, 6)
        if stage == "indexes":
            return round(base + idx_bonus, 6)
        return round(base + type_bonus + zstd_bonus + idx_bonus, 6)

    @staticmethod
    def _unwrap_type(raw_type: str) -> str:
        t = raw_type
        for wrapper in ("LowCardinality", "Nullable"):
            prefix = f"{wrapper}("
            if t.startswith(prefix) and t.endswith(")"):
                t = t[len(prefix) : -1]
        return t.split("(")[0]


class DebugResultStore(BenchmarkResultStore):
    """Debug-friendly in-memory store implementing BenchmarkResultStore contract."""

    def __init__(self) -> None:
        self._records: List[StoredBenchmarkResult] = []

    @property
    def records(self) -> List[StoredBenchmarkResult]:
        return list(self._records)

    def store_result(self, job: VariantJob, result: BenchmarkVariantResult) -> None:
        # Удобная точка для отладки сохранения и валидаций identity.
        if result.benchmark_run_id != job.benchmark_run_id:
            raise ValueError("result.benchmark_run_id не совпадает с job.benchmark_run_id")
        if result.benchmark_id != job.benchmark_id:
            raise ValueError("result.benchmark_id не совпадает с job.benchmark_id")
        if (
            result.benchmark_started_at is not None
            and result.benchmark_started_at != job.benchmark_started_at
        ):
            raise ValueError("result.benchmark_started_at не совпадает с job.benchmark_started_at")

        row = StoredBenchmarkResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            source_db_name=job.source_database,
            source_table_name=job.source_table,
            variant_table=job.variant_table,
            variant_mode=result.variant_mode or job.variant_meta.mode,
            variant_params=(
                dict(result.variant_params)
                if result.variant_params
                else build_variant_params(job.variant_meta)
            ),
            source_table_ddl=result.source_table_ddl,
            tested_table_ddl=result.tested_table_ddl or job.variant_ddl.to_ddl(),
            index_params=result.index_params
            or json.dumps(
                (
                    dict(result.variant_params)
                    if result.variant_params
                    else build_variant_params(job.variant_meta)
                ).get("index_choices", {}),
                ensure_ascii=False,
                default=str,
            ),
            extra_json=result.extra_json,
            score=result.score,
        )
        self._records.append(row)

    def get_top_type_variants(
        self,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        top_n: int,
    ) -> List[TopTypeVariant]:
        # Удобная точка для отладки top-N логики sequential.
        if top_n <= 0:
            return []

        candidates = [
            row
            for row in self._records
            if row.benchmark_run_id == benchmark_run_id
            and row.benchmark_id == benchmark_id
            and row.source_database == source_database
            and row.source_table == source_table
            and row.variant_mode == "types"
        ]
        ranked = sorted(
            candidates,
            key=lambda row: (
                row.score is None,
                -(row.score if row.score is not None else 0.0),
                _variant_index_from_variant_table(row.variant_table),
            ),
        )
        return [
            TopTypeVariant(
                variant_index=_variant_index_from_variant_table(row.variant_table),
                variant_ddl=TableDDL.from_ddl(row.tested_table_ddl),
                score=row.score,
            )
            for row in ranked[:top_n]
        ]


def _variant_index_from_variant_table(name: str) -> int:
    parsed = parse_variant_name(name)
    if parsed is None:
        return 0
    return parsed[2]


class DebugRunIdProvider(BenchmarkRunIdProvider):
    """Simple deterministic run-id provider for debugger-friendly replay."""

    def __init__(self, start_from: int = 1000) -> None:
        self._next = start_from

    def next_benchmark_run_id(self) -> int:
        value = self._next
        self._next += 1
        return value


class TracingTableExecutionStrategy(TableExecutionStrategy):
    """Decorator for table-level strategies with detailed debug logs."""

    def __init__(self, strategy_key: str, delegate: TableExecutionStrategy) -> None:
        self._strategy_key = strategy_key
        self._delegate = delegate

    def execute_table(
        self,
        runner: BenchmarkRunner,
        table_plan: TableBenchmarkPlan,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
    ) -> None:
        print(
            f"[table_strategy] start strategy={self._strategy_key} "
            f"bench={table_plan.benchmark_id} table={table_plan.database}.{table_plan.table} "
            f"mode={table_plan.mode} max_iterations={table_plan.max_iterations}"
        )
        self._delegate.execute_table(
            runner=runner,
            table_plan=table_plan,
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
        )
        print(
            f"[table_strategy] done strategy={self._strategy_key} "
            f"bench={table_plan.benchmark_id} table={table_plan.database}.{table_plan.table}"
        )


class TracingVariantGenerationStrategy(VariantGenerationStrategy):
    """Decorator for variant generation strategy with per-variant tracing."""

    def __init__(self, mode: str, delegate: VariantGenerationStrategy) -> None:
        self._mode = mode
        self._delegate = delegate

    def iter_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
    ) -> Iterable[Tuple[TableDDL, VariantMeta]]:
        print(
            f"[variant_generation] iter start mode={self._mode} table={table.name} "
            f"column_rules={len(column_rules)} index_rules={len(index_rules)}"
        )
        for local_idx, (variant, meta) in enumerate(
            self._delegate.iter_variants(
                table=table,
                column_rules=column_rules,
                index_rules=index_rules,
                column_order=column_order,
            )
        ):
            print(
                f"[variant_generation] mode={self._mode} "
                f"local_idx={local_idx} variant_name={variant.name}"
            )
            yield variant, meta
        print(f"[variant_generation] iter done mode={self._mode}")

    def total_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
    ) -> int:
        total = self._delegate.total_variants(
            table=table,
            column_rules=column_rules,
            index_rules=index_rules,
            column_order=column_order,
        )
        print(f"[variant_generation] total mode={self._mode} table={table.name} total={total}")
        return total


def install_variant_generation_tracing() -> None:
    """Wraps built-in mode strategies with tracing decorators."""
    for mode in ("types", "indexes", "combined", "sequential"):
        strategy = get_variant_generation_strategy(mode)
        if isinstance(strategy, TracingVariantGenerationStrategy):
            continue
        register_variant_generation_strategy(
            mode=mode,
            strategy=TracingVariantGenerationStrategy(mode=mode, delegate=strategy),
            overwrite=True,
        )


def build_tracing_table_strategies() -> Dict[str, TableExecutionStrategy]:
    """Builds tracing wrappers for all built-in table strategies."""
    return {
        "types_strategy": TracingTableExecutionStrategy(
            strategy_key="types_strategy",
            delegate=TypesTableExecutionStrategy(),
        ),
        "indexes_strategy": TracingTableExecutionStrategy(
            strategy_key="indexes_strategy",
            delegate=IndexesTableExecutionStrategy(),
        ),
        "combined_strategy": TracingTableExecutionStrategy(
            strategy_key="combined_strategy",
            delegate=CombinedTableExecutionStrategy(),
        ),
        "sequential_topn_strategy": TracingTableExecutionStrategy(
            strategy_key="sequential_topn_strategy",
            delegate=SequentialTopNTableExecutionStrategy(),
        ),
        "sequential_topn_stage1_dispatch_strategy": TracingTableExecutionStrategy(
            strategy_key="sequential_topn_stage1_dispatch_strategy",
            delegate=SequentialTopNDispatchTypesTableExecutionStrategy(),
        ),
        "sequential_topn_stage2_dispatch_strategy": TracingTableExecutionStrategy(
            strategy_key="sequential_topn_stage2_dispatch_strategy",
            delegate=SequentialTopNDispatchIndexesTableExecutionStrategy(),
        ),
    }


def build_synthetic_root_config() -> object:
    """Builds root config from inline synthetic JSON sections."""
    return parse_config_parts(
        celery_raw={"workers": 2, "threads_per_worker": 1},
        connections_raw={
            "connections": [
                {
                    "id": "synthetic_ch",
                    "dbms": "clickhouse",
                    "credential_type": "password",
                    "host": "localhost",
                    "port": 9000,
                    "login": "default",
                    "password": "dev",
                }
            ]
        },
        rule_banks_raw={
            "rule_banks": {
                "clickhouse_debug_bank": {
                    "column_rules": [
                        {
                            "by_type": "UInt64",
                            "types": ["UInt64", "UInt32", "UInt16"],
                            "codecs": ["CODEC(Delta(8), LZ4)", "CODEC(ZSTD(1))"],
                        },
                        {
                            "by_type": "UInt32",
                            "types": ["UInt32", "UInt16"],
                            "codecs": ["CODEC(Delta(4), LZ4)", "CODEC(ZSTD(1))"],
                        },
                    ],
                    "index_rules": [
                        {
                            "by_type": "UInt64",
                            "indexes": [
                                {"type": "minmax", "granularity": 1},
                                {"type": "set(100)", "granularity": 2},
                            ],
                        },
                        {
                            "by_type": "UInt32",
                            "indexes": [
                                {"type": "minmax", "granularity": 1}
                            ],
                        },
                    ],
                }
            },
            "default_rule_banks": {"clickhouse": "clickhouse_debug_bank"},
        },
        benchmarks_raw={
            "benchmarks": [
                {
                    "id": "bench_sequential_debug",
                    "connection_id": "synthetic_ch",
                    "strategy": "sequential_topn_strategy",
                    "databases": ["analytics"],
                    "tables": {"analytics": ["events"]},
                    "max_iterations": 8,
                    "sequential_top_n": 2,
                    "insert_rows_limit": 500000,
                    "insert_rows_limits": {
                        "types": 120000,
                        "indexes": 50000,
                        "sequential": 70000,
                    },
                    "global_rules": {"rule_bank": "clickhouse_debug_bank"},
                    "queries": {
                        "mode": "manual",
                        "warmup_queries": ["SELECT count() FROM {table}"],
                        "test_queries": [
                            {
                                "query": "SELECT sum(user_id) FROM {table}",
                                "weight": 1.0,
                            }
                        ],
                    },
                },
                {
                    "id": "bench_combined_debug",
                    "connection_id": "synthetic_ch",
                    "strategy": "combined_strategy",
                    "column_order_mode": "compressed_size_desc",
                    "databases": ["analytics"],
                    "tables": {"analytics": ["sessions"]},
                    "max_iterations": 5,
                    "insert_rows_limit": 250000,
                    "global_rules": {"rule_bank": "clickhouse_debug_bank"},
                    "queries": {"mode": "auto"},
                },
            ]
        },
    )


def build_synthetic_provider() -> SyntheticMetadataProvider:
    """Builds in-memory metadata source for synthetic run."""
    return SyntheticMetadataProvider(
        ddl_by_db_table={
            "analytics": {
                "events": EVENTS_DDL,
                "sessions": SESSIONS_DDL,
            }
        },
        column_sizes_by_db_table={
            "analytics": {
                "events": {
                    "event_time": 40_000_000,
                    "user_id": 15_000_000,
                    "event_type": 7_000_000,
                    "revenue": 3_000_000,
                },
                "sessions": {
                    "started_at": 20_000_000,
                    "session_id": 10_000_000,
                    "duration_s": 5_000_000,
                    "country": 2_000_000,
                },
            }
        },
    )


def print_summary(records: Iterable[StoredBenchmarkResult]) -> None:
    """Prints compact summary grouped by benchmark/table/stage."""
    grouped: Dict[tuple[str, str, str], List[StoredBenchmarkResult]] = defaultdict(list)
    for row in records:
        key = (row.benchmark_id, f"{row.source_database}.{row.source_table}", row.variant_mode)
        grouped[key].append(row)

    print("\n=== Synthetic run summary ===")
    for (bench_id, table_name, stage), rows in sorted(grouped.items()):
        scores = [r.score for r in rows if r.score is not None]
        best = max(scores) if scores else None
        print(
            f"- {bench_id} | {table_name} | stage={stage}: "
            f"results={len(rows)}, best_score={best}"
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synthetic playground for debugging benchmark runtime integrations."
    )
    parser.add_argument(
        "--benchmark-id",
        action="append",
        dest="benchmark_ids",
        help="Можно указать несколько раз: --benchmark-id bench_a --benchmark-id bench_b",
    )
    parser.add_argument(
        "--benchmark-run-id",
        type=int,
        default=None,
        help="Явный run id (если не задан, берётся из DebugRunIdProvider).",
    )
    parser.add_argument(
        "--no-variant-trace",
        action="store_true",
        help="Отключить tracing VariantGenerationStrategy.",
    )
    parser.add_argument(
        "--no-table-strategy-trace",
        action="store_true",
        help="Отключить tracing TableExecutionStrategy.",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    if not args.no_variant_trace:
        install_variant_generation_tracing()

    config = build_synthetic_root_config()
    metadata = build_synthetic_provider()

    planner = BenchmarkPlanner(
        config=config,
        providers_by_connection_id={"synthetic_ch": metadata},
    )
    engine = BenchmarkEngine(planner=planner)

    result_store = DebugResultStore()
    tracing_table_strategies = (
        None if args.no_table_strategy_trace else build_tracing_table_strategies()
    )
    default_strategy = (
        None
        if args.no_table_strategy_trace
        else TracingTableExecutionStrategy(
            strategy_key="default_fallback",
            delegate=DefaultTableExecutionStrategy(),
        )
    )
    runner = BenchmarkRunner(
        engine=engine,
        execution_adapter=SyntheticExecutionAdapter(),
        result_store=result_store,
        run_id_provider=DebugRunIdProvider(start_from=1000),
        run_started_at_provider=lambda: datetime.now(timezone.utc),
        table_execution_strategies=tracing_table_strategies,
        default_table_execution_strategy=default_strategy,
    )

    run_id = runner.run(
        benchmark_ids=args.benchmark_ids,
        benchmark_run_id=args.benchmark_run_id,
    )
    print(f"\nBenchmark run completed. benchmark_run_id={run_id}")

    print_summary(result_store.records)


if __name__ == "__main__":
    main()
