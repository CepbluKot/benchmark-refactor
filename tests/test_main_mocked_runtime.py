import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import main
from src.benchmark_runtime.types import BenchmarkVariantResult, SourceBenchmarkResult
from src.clickhouse_ddl import TableDDL


EVENTS_DDL = """
CREATE TABLE analytics.events
(
    `user_id` UInt64,
    `event_time` DateTime
)
ENGINE = MergeTree
ORDER BY (user_id, event_time)
"""


class _FakeSettings:
    benchmark_ids = []
    benchmark_run_id = None
    test_database = "bench_tmp"
    result_connection_id = "prod_ch"
    result_database = "bench_results"
    result_table = "combined_results"
    log_level = "INFO"

    @staticmethod
    def decode_celery_config():
        return {"workers": 2, "threads_per_worker": 1}

    @staticmethod
    def decode_connections_config():
        return {
            "connections": [
                {
                    "id": "prod_ch",
                    "dbms": "clickhouse",
                    "credential_type": "password",
                    "host": "localhost",
                    "port": 9000,
                    "login": "user",
                    "password": "pass",
                }
            ]
        }

    @staticmethod
    def decode_rule_banks_config():
        return {"rule_banks": {}, "default_rule_banks": {}}

    @staticmethod
    def decode_benchmarks_config():
        return {
            "benchmarks": [
                {
                    "id": "bench_mocked_runtime",
                    "connection_id": "prod_ch",
                    "strategy": "types_strategy",
                    "databases": ["analytics"],
                    "tables": ["events"],
                    "max_iterations": 1,
                    "global_rules": {
                        "column_rules": [
                            {"by_type": "UInt64", "types": ["UInt64", "UInt32"]}
                        ]
                    },
                    "queries": {
                        "mode": "manual",
                        "test_queries": [{"query": "SELECT count() FROM {table}", "weight": 1.0}],
                    },
                }
            ]
        }


class _FakeFetcher:
    instances = []

    def __init__(self, connection) -> None:
        self.connection = connection
        self.connected = False
        self.disconnected = False
        _FakeFetcher.instances.append(self)

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.disconnected = True
        self.connected = False

    @staticmethod
    def list_databases():
        return ["analytics"]

    @staticmethod
    def list_tables(database: str):
        return ["events"] if database == "analytics" else []

    @staticmethod
    def fetch_ddl(database: str, table: str):
        if database != "analytics" or table != "events":
            raise ValueError("unexpected table")
        return TableDDL.from_ddl(EVENTS_DDL)

    @staticmethod
    def fetch_column_sizes(database: str, table: str):
        del database, table
        return {"user_id": 100}


class _FakeResultStore:
    last_instance = None

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.closed = False
        _FakeResultStore.last_instance = self

    def close(self) -> None:
        self.closed = True

    @staticmethod
    def store_result(job, result) -> None:
        del job, result

    @staticmethod
    def get_top_type_variants(
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        top_n: int,
    ):
        del benchmark_run_id, benchmark_id, source_database, source_table, top_n
        return []


class _FakeExecutionAdapter:
    last_instance = None

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.bound_store = None
        self.source_jobs = []
        self.variant_jobs = []
        _FakeExecutionAdapter.last_instance = self

    def bind_result_store(self, result_store) -> None:
        self.bound_store = result_store

    def execute_source_benchmark(self, job) -> SourceBenchmarkResult:
        self.source_jobs.append(job)
        return SourceBenchmarkResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            source_table_ddl=job.source_table_ddl.to_ddl(),
            score=1.0,
            metrics={},
        )

    def execute_variant(self, job) -> BenchmarkVariantResult:
        self.variant_jobs.append(job)
        return BenchmarkVariantResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=datetime.now(timezone.utc),
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            variant_mode=job.variant_meta.mode,
            score=1.0,
        )


class MainMockedRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeFetcher.instances = []
        _FakeResultStore.last_instance = None
        _FakeExecutionAdapter.last_instance = None

    def test_run_from_settings_executes_benchmark_with_mocked_runtime(self) -> None:
        """Проверяет сквозной запуск benchmark через main.run_from_settings с моками."""
        with patch("main.get_settings", return_value=_FakeSettings()), patch(
            "main.make_fetcher",
            side_effect=lambda connection: _FakeFetcher(connection),
        ), patch(
            "main.ClickHouseBenchmarkResultStore",
            _FakeResultStore,
        ), patch(
            "main.CeleryClickHouseExecutionAdapter",
            _FakeExecutionAdapter,
        ):
            run_id = main.run_from_settings()

        self.assertEqual(run_id, 1)
        self.assertTrue(_FakeFetcher.instances)
        self.assertTrue(all(fetcher.disconnected for fetcher in _FakeFetcher.instances))

        result_store = _FakeResultStore.last_instance
        self.assertIsNotNone(result_store)
        self.assertTrue(result_store.closed)

        adapter = _FakeExecutionAdapter.last_instance
        self.assertIsNotNone(adapter)
        self.assertIs(adapter.bound_store, result_store)
        self.assertEqual(len(adapter.source_jobs), 1)
        self.assertGreaterEqual(len(adapter.variant_jobs), 1)
        self.assertTrue(all(job.variant_database == "bench_tmp" for job in adapter.variant_jobs))

        self.assertEqual(adapter.kwargs["result_database"], "bench_results")
        self.assertEqual(adapter.kwargs["result_table"], "combined_results")
        self.assertEqual(adapter.kwargs["result_connections_by_id"]["prod_ch"].id, "prod_ch")


if __name__ == "__main__":
    unittest.main()

