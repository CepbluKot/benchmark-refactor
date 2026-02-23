"""
Демо двухфазного sequential-режима:
  1) прогон вариантов types/codecs;
  2) отбор top-N по score;
  3) прогон index-вариантов только на DDL лучших type-вариантов.

В примере показаны оба варианта приоритизации колонок:
  - manual `rules.column_order` для `analytics.user_events`;
  - auto `column_order_mode="compressed_size_desc"` для `analytics.partner_stats`.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Dict, List

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from benchmark_engine import (
    BenchmarkEngine,
    BenchmarkExecutionAdapter,
    BenchmarkPlanner,
    BenchmarkRunner,
    BenchmarkVariantResult,
    InMemoryBenchmarkResultStore,
    MetadataProvider,
    VariantJob,
)
from clickhouse_ddl import TableDDL
from loader import load_config


USER_EVENTS_DDL = """
CREATE TABLE analytics.user_events
(
    `user_id`     UInt64                  CODEC(Delta(8), LZ4),
    `event_time`  DateTime                CODEC(DoubleDelta, ZSTD(1)),
    `event_type`  LowCardinality(String)  CODEC(ZSTD(1)),
    `country`     LowCardinality(String)  CODEC(ZSTD(1)),
    `revenue`     Nullable(Decimal(18,4)) CODEC(ZSTD(1))
)
ENGINE = MergeTree
ORDER BY (user_id, event_time)
"""

PARTNER_STATS_DDL = """
CREATE TABLE analytics.partner_stats
(
    `partner_id`   UInt64   CODEC(Delta(8), LZ4),
    `stat_date`    DateTime CODEC(DoubleDelta, ZSTD(1)),
    `impressions`  UInt64   CODEC(Delta(8), LZ4),
    `clicks`       UInt32   CODEC(Delta(4), LZ4),
    `spend`        Float64  CODEC(ZSTD(1))
)
ENGINE = MergeTree
ORDER BY (partner_id, stat_date)
"""


class InMemoryMetadataProvider(MetadataProvider):
    def __init__(
        self,
        ddl_by_db_table: Dict[str, Dict[str, str]],
        column_sizes_by_db_table: Dict[str, Dict[str, Dict[str, int]]],
    ) -> None:
        self._ddl_by_db_table = ddl_by_db_table
        self._column_sizes_by_db_table = column_sizes_by_db_table

    def list_databases(self) -> List[str]:
        return sorted(self._ddl_by_db_table.keys())

    def list_tables(self, database: str) -> List[str]:
        return sorted(self._ddl_by_db_table.get(database, {}).keys())

    def fetch_table_ddl(self, database: str, table: str) -> TableDDL:
        return TableDDL.from_ddl(self._ddl_by_db_table[database][table])

    def fetch_column_sizes(self, database: str, table: str) -> Dict[str, int]:
        return dict(self._column_sizes_by_db_table.get(database, {}).get(table, {}))


class SequentialTopNDemoAdapter(BenchmarkExecutionAdapter):
    """
    Dry-run adapter с искусственным score.

    Для type-этапа score выше у вариантов с более "узкими" целочисленными типами
    и с ZSTD-кодеками. Этого достаточно, чтобы увидеть как работает top-N отбор.
    """

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

    @classmethod
    def _base_type(cls, raw_type: str) -> str:
        t = raw_type
        for wrapper in ("LowCardinality", "Nullable"):
            prefix = f"{wrapper}("
            if t.startswith(prefix) and t.endswith(")"):
                t = t[len(prefix):-1]
        return t.split("(")[0]

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        stage = job.variant_meta.mode
        if stage == "types":
            int_bonus = 0.0
            zstd_bonus = 0.0
            for col in job.variant_ddl.columns:
                base = self._base_type(col.type)
                if base in self._INT_WIDTH:
                    # Чем меньше ширина типа, тем выше score.
                    int_bonus += (64 - self._INT_WIDTH[base]) / 8.0
                if col.codec and "ZSTD" in col.codec.upper():
                    zstd_bonus += 0.2
            score = round(int_bonus + zstd_bonus, 4)
        else:
            # Индексная фаза не участвует в выборе top-N, score здесь вторичен.
            score = round(0.1 * len(job.variant_ddl.indexes), 4)

        print(
            f"[run={job.benchmark_run_id}][{job.benchmark_id}] {job.source_database}.{job.source_table} "
            f"stage={stage} idx={job.variant_meta.global_index} "
            f"table={job.variant_table} score={score} "
            f"insert_rows_limit={job.insert_rows_limit}"
        )

        return BenchmarkVariantResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            variant_index=job.variant_meta.global_index,
            score=score,
            payload={"stage": stage},
        )


def main() -> None:
    config_path = ROOT_DIR / "configs" / "benchmark.project.sequential_topn.example.json"
    config = load_config(config_path)

    provider = InMemoryMetadataProvider(
        ddl_by_db_table={
            "analytics": {
                "user_events": USER_EVENTS_DDL,
                "partner_stats": PARTNER_STATS_DDL,
            }
        },
        column_sizes_by_db_table={
            "analytics": {
                "user_events": {
                    "event_time": 50_000_000,
                    "user_id": 15_000_000,
                    "event_type": 8_000_000,
                    "country": 7_000_000,
                    "revenue": 3_000_000,
                },
                "partner_stats": {
                    "stat_date": 40_000_000,
                    "partner_id": 20_000_000,
                    "impressions": 9_000_000,
                    "clicks": 6_000_000,
                    "spend": 4_000_000,
                },
            }
        },
    )

    planner = BenchmarkPlanner(
        config=config,
        providers_by_connection_id={"prod_ch": provider},
    )
    print("=== Column-order strategy by table ===")
    for table_plan in planner.iter_table_plans(benchmark_ids=["bench_sequential_topn"]):
        mode = table_plan.column_order_mode or "manual_or_bank"
        print(
            f"  {table_plan.database}.{table_plan.table}: "
            f"column_order_mode={mode}, "
            f"column_order={table_plan.rules.column_order}"
        )

    engine = BenchmarkEngine(planner=planner)
    result_store = InMemoryBenchmarkResultStore()
    runner = BenchmarkRunner(
        engine=engine,
        execution_adapter=SequentialTopNDemoAdapter(),
        result_store=result_store,
    )

    print("=== Sequential top-N demo: benchmark_id='bench_sequential_topn' ===")
    run_id = runner.run(benchmark_ids=["bench_sequential_topn"])
    results = [
        row
        for row in result_store.records
        if row.benchmark_run_id == run_id and row.benchmark_id == "bench_sequential_topn"
    ]

    type_results = [r for r in results if r.payload.get("stage") == "types"]
    index_results = [r for r in results if r.payload.get("stage") == "indexes"]
    print(f"Run id: {run_id}")
    print(f"Всего результатов: {len(results)}")
    print(f"  type stage:  {len(type_results)}")
    print(f"  index stage: {len(index_results)}")


if __name__ == "__main__":
    main()
