"""
Точка входа запуска benchmark-алгоритма по JSON-конфигам из settings.

Сейчас используется in-memory заглушка metadata-провайдера вместо реального
Fetcher/подключения к ClickHouse.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.benchmark_engine import (
    BenchmarkEngine,
    BenchmarkPlanner,
    BenchmarkRunner,
    InMemoryBenchmarkResultStore,
    MetadataProvider,
    NoopExecutionAdapter,
)
from src.clickhouse_ddl import TableDDL
from src.loader import parse_config_parts

from settings import get_settings


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


class StubMetadataProvider(MetadataProvider):
    """Заглушка metadata-provider вместо реального Fetcher/ClickHouse."""

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
        try:
            return TableDDL.from_ddl(self._ddl_by_db_table[database][table])
        except KeyError as exc:
            raise ValueError(
                f"Нет DDL-заглушки для таблицы {database}.{table}"
            ) from exc

    def fetch_column_sizes(self, database: str, table: str) -> Dict[str, int]:
        return dict(self._column_sizes_by_db_table.get(database, {}).get(table, {}))


def _build_stub_providers(connection_ids: List[str]) -> Dict[str, MetadataProvider]:
    """
    Создаёт map `connection_id -> StubMetadataProvider`.

    Пока в `main.py` используется только заглушка вместо Fetcher.
    """
    stub = StubMetadataProvider(
        ddl_by_db_table={
            "analytics": {
                "user_events": USER_EVENTS_DDL,
                "partner_stats": PARTNER_STATS_DDL,
            },
            "marketing": {
                "campaign_rollup": CAMPAIGN_ROLLUP_DDL,
            },
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
            },
            "marketing": {
                "campaign_rollup": {
                    "event_time": 35_000_000,
                    "campaign_id": 18_000_000,
                    "conversions": 7_000_000,
                    "cost": 6_000_000,
                    "region": 2_000_000,
                }
            },
        },
    )
    return {connection_id: stub for connection_id in connection_ids}


def run_from_settings() -> int:
    """Запускает BenchmarkRunner по настройкам и возвращает run id."""
    app_settings = get_settings()
    config = parse_config_parts(
        celery_raw=app_settings.decode_celery_config(),
        connections_raw=app_settings.decode_connections_config(),
        rule_banks_raw=app_settings.decode_rule_banks_config(),
        benchmarks_raw=app_settings.decode_benchmarks_config(),
    )

    providers = _build_stub_providers(
        connection_ids=[connection.id for connection in config.connections]
    )
    planner = BenchmarkPlanner(
        config=config,
        providers_by_connection_id=providers,
    )
    engine = BenchmarkEngine(planner=planner)
    runner = BenchmarkRunner(
        engine=engine,
        execution_adapter=NoopExecutionAdapter(),
        result_store=InMemoryBenchmarkResultStore(),
    )

    benchmark_ids: Optional[List[str]] = app_settings.benchmark_ids or None
    return runner.run(
        benchmark_ids=benchmark_ids,
        benchmark_run_id=app_settings.benchmark_run_id,
    )


def main() -> None:
    """CLI entrypoint."""
    run_id = run_from_settings()
    print(f"Benchmark run completed. benchmark_run_id={run_id}")


if __name__ == "__main__":
    main()
