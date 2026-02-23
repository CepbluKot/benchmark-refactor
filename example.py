"""
Демо новой архитектуры:
  - JSON-конфиг через Pydantic
  - class-based planner/engine/runner
  - глобальные и локальные override правил/итераций
  - выбор БД и таблиц через "*" и ручные map-селекторы
  - interface ExecutionAdapter для подключения вашего существующего кода замеров
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

CAMPAIGN_ROLLUP_DDL = """
CREATE TABLE marketing.campaign_rollup
(
    `campaign_id`   UInt64                  CODEC(Delta(8), LZ4),
    `event_time`    DateTime                CODEC(DoubleDelta, ZSTD(1)),
    `region`        LowCardinality(String)  CODEC(ZSTD(1)),
    `conversions`   UInt32                  CODEC(Delta(4), LZ4),
    `cost`          Float64                 CODEC(ZSTD(1))
)
ENGINE = MergeTree
ORDER BY (campaign_id, event_time)
"""


class InMemoryMetadataProvider(MetadataProvider):
    """
    В памяти имитирует metadata API (list_databases/list_tables/fetch_table_ddl).
    В проде вместо этого подключается ваш реальный Fetcher/DB client.
    """

    def __init__(self, ddl_by_db_table: Dict[str, Dict[str, str]]) -> None:
        """Принимает map вида `{database: {table: ddl_sql}}`."""
        self._ddl_by_db_table = ddl_by_db_table

    def list_databases(self) -> List[str]:
        """Возвращает доступные БД из in-memory словаря."""
        return sorted(self._ddl_by_db_table.keys())

    def list_tables(self, database: str) -> List[str]:
        """Возвращает таблицы указанной БД."""
        return sorted(self._ddl_by_db_table.get(database, {}).keys())

    def fetch_table_ddl(self, database: str, table: str) -> TableDDL:
        """Парсит DDL строки таблицы в `TableDDL`."""
        ddl = self._ddl_by_db_table[database][table]
        return TableDDL.from_ddl(ddl)


class DemoExecutionAdapter(BenchmarkExecutionAdapter):
    """
    Пример точки интеграции.
    Здесь можно напрямую подключить ваш существующий код:
      - создание variant таблицы
      - перенос данных
      - warmup
      - замеры тестовых запросов
      - подсчёт финального score
    """

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        """Dry-run выполнение: печатает план и возвращает псевдо-score."""
        pseudo_score = round(1.0 / (1 + job.variant_meta.global_index), 6)
        print(
            f"[run={job.benchmark_run_id}][{job.benchmark_id}] {job.source_database}.{job.source_table} "
            f"-> {job.variant_table} "
            f"(mode={job.mode}, idx={job.variant_meta.global_index}, total={job.total_variants})"
        )
        print(
            f"  celery: workers={job.celery.workers}, "
            f"threads_per_worker={job.celery.threads_per_worker}, "
            f"queries={len(job.query_plan.test_queries)}"
        )
        return BenchmarkVariantResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            variant_index=job.variant_meta.global_index,
            score=pseudo_score,
            payload={"dry_run": True},
        )


def main() -> None:
    """Демонстрирует запуск пайплайна planner -> engine -> runner на тестовых DDL."""
    config_path = Path(__file__).with_name("benchmark.project.example.json")
    config = load_config(config_path)

    provider = InMemoryMetadataProvider(
        ddl_by_db_table={
            "analytics": {
                "user_events": USER_EVENTS_DDL,
                "partner_stats": PARTNER_STATS_DDL,
            },
            "marketing": {
                "campaign_rollup": CAMPAIGN_ROLLUP_DDL,
            },
        }
    )

    planner = BenchmarkPlanner(
        config=config,
        providers_by_connection_id={"prod_ch": provider},
    )
    engine = BenchmarkEngine(planner=planner)
    result_store = InMemoryBenchmarkResultStore()
    runner = BenchmarkRunner(
        engine=engine,
        execution_adapter=DemoExecutionAdapter(),
        result_store=result_store,
    )

    print("=== План + dry-run выполнения benchmark_id='bench_mixed_selectors' ===")
    run_id = runner.run(benchmark_ids=["bench_mixed_selectors"])
    run_results = [
        row
        for row in result_store.records
        if row.benchmark_run_id == run_id and row.benchmark_id == "bench_mixed_selectors"
    ]
    print(f"Run id: {run_id}")
    print(f"Всего результатов: {len(run_results)}")
    print("Первые 3 score:")
    for result in run_results[:3]:
        print(
            f"  {result.variant_table}: score={result.score}, payload={result.payload}"
        )


if __name__ == "__main__":
    main()
