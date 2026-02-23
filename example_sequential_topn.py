"""
Демо двухфазного sequential-режима:
  1) прогон вариантов types/codecs;
  2) отбор top-N по score;
  3) прогон index-вариантов только на DDL лучших type-вариантов.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from benchmark_engine import (
    BenchmarkEngine,
    BenchmarkExecutionAdapter,
    BenchmarkPlanner,
    BenchmarkRunner,
    BenchmarkVariantResult,
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
    def __init__(self, ddl_by_db_table: Dict[str, Dict[str, str]]) -> None:
        self._ddl_by_db_table = ddl_by_db_table

    def list_databases(self) -> List[str]:
        return sorted(self._ddl_by_db_table.keys())

    def list_tables(self, database: str) -> List[str]:
        return sorted(self._ddl_by_db_table.get(database, {}).keys())

    def fetch_table_ddl(self, database: str, table: str) -> TableDDL:
        return TableDDL.from_ddl(self._ddl_by_db_table[database][table])


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
            f"table={job.variant_table} score={score}"
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
    config_path = Path(__file__).with_name(
        "benchmark.project.sequential_topn.example.json"
    )
    config = load_config(config_path)

    provider = InMemoryMetadataProvider(
        ddl_by_db_table={
            "analytics": {
                "user_events": USER_EVENTS_DDL,
                "partner_stats": PARTNER_STATS_DDL,
            }
        }
    )

    planner = BenchmarkPlanner(
        config=config,
        providers_by_connection_id={"prod_ch": provider},
    )
    engine = BenchmarkEngine(planner=planner)
    runner = BenchmarkRunner(
        engine=engine,
        execution_adapter=SequentialTopNDemoAdapter(),
    )

    print("=== Sequential top-N demo: benchmark_id='bench_sequential_topn' ===")
    results = runner.run(benchmark_ids=["bench_sequential_topn"])

    type_results = [r for r in results if r.payload.get("stage") == "types"]
    index_results = [r for r in results if r.payload.get("stage") == "indexes"]
    print(f"Всего результатов: {len(results)}")
    print(f"  type stage:  {len(type_results)}")
    print(f"  index stage: {len(index_results)}")


if __name__ == "__main__":
    main()
