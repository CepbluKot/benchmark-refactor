import json
import unittest
from datetime import datetime, timezone
from typing import Any, Dict, List

from src.benchmark_engine import (
    BenchmarkEngine,
    BenchmarkPlanner,
    BenchmarkRunner,
    BenchmarkVariantResult,
    InMemoryBenchmarkResultStore,
    MetadataProvider,
    SourceBenchmarkJob,
    SourceBenchmarkResult,
    VariantJob,
)
from src.benchmark_runtime.implementations.clickhouse_celery.execution import (
    CeleryClickHouseExecutionAdapter,
)
from src.benchmark_runtime.implementations.clickhouse_celery.tasks import (
    SOURCE_BENCHMARK_TASK_NAME,
    VARIANT_BENCHMARK_TASK_NAME,
    app as celery_worker_app,
)
from src.benchmark_runtime.implementations.clickhouse_celery.result_store import (
    ClickHouseBenchmarkResultStore,
    ClickHouseConnectionParams,
)
from src.benchmark_runtime.types import Query, QueryPlan
from src.clickhouse_ddl import TableDDL
from src.models import (
    BenchmarkConfig,
    BenchmarkRootConfig,
    CeleryConfig,
    ColumnRuleConfig,
    ConnectionConfig,
    IndexConfig,
    IndexRuleConfig,
    RuleBankConfig,
    RulesConfig,
)


EVENTS_DDL = """
CREATE TABLE analytics.events
(
    `user_id` UInt64 CODEC(Delta(8), LZ4),
    `event_time` DateTime CODEC(DoubleDelta, ZSTD(1)),
    `payload` String CODEC(ZSTD(1))
)
ENGINE = MergeTree
ORDER BY (user_id, event_time)
"""


class _StaticMetadataProvider(MetadataProvider):
    def __init__(self) -> None:
        self._ddl = {"analytics": {"events": TableDDL.from_ddl(EVENTS_DDL)}}

    def list_databases(self) -> List[str]:
        return ["analytics"]

    def list_tables(self, database: str) -> List[str]:
        return ["events"] if database == "analytics" else []

    def fetch_table_ddl(self, database: str, table: str) -> TableDDL:
        return self._ddl[database][table].copy()


class _FakeAsyncResult:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def get(self, timeout: float | None = None) -> Any:
        del timeout
        return self._payload


class _FakeCeleryApp:
    def __init__(self, source_payload: Dict[str, Any]) -> None:
        self.source_payload = source_payload
        self.calls: list[dict[str, Any]] = []

    def send_task(self, task_name: str, **kwargs: Any) -> _FakeAsyncResult:
        self.calls.append({"task_name": task_name, **kwargs})
        if task_name == "bench.source_benchmark":
            return _FakeAsyncResult(self.source_payload)
        return _FakeAsyncResult({"status": "dispatched"})


class _SequentialAdapterWithProgressHooks:
    def __init__(self) -> None:
        self._store = None
        self.executed_jobs: list[VariantJob] = []
        self.wait_calls: list[str] = []
        self.open_calls: list[str] = []
        self.finalize_calls = 0

    def bind_result_store(self, result_store):
        self._store = result_store

    def execute_source_benchmark(self, job: SourceBenchmarkJob) -> SourceBenchmarkResult:
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

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        self.executed_jobs.append(job)
        score = 0.5
        if job.variant_meta.mode == "types":
            score = 10.0 if job.variant_ddl.column("user_id").type == "UInt32" else 1.0

        result = BenchmarkVariantResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            variant_mode=job.variant_meta.mode,
            score=score,
        )
        if self._store is not None:
            self._store.store_result(job, result)
        return result

    def open_progress_scope(self, scope_name: str) -> None:
        self.open_calls.append(scope_name)

    def wait_for_dispatched_tasks(self, stage_label: str, timeout: float | None = None) -> bool:
        del timeout
        self.wait_calls.append(stage_label)
        return True

    def finalize_progress_scope(self, wait: bool = False, timeout: float | None = None) -> None:
        del wait, timeout
        self.finalize_calls += 1


class _FakeClickHouseResultStore(ClickHouseBenchmarkResultStore):
    def __init__(self, rows_to_return: list[tuple[str, str, float | None]]) -> None:
        self.rows_to_return = rows_to_return
        self.captured_queries: list[tuple[str, Any]] = []
        super().__init__(
            connection=ClickHouseConnectionParams(
                host="localhost",
                port=9000,
                login="default",
                password="",
            ),
            database="bench",
            table="results",
            create_table_if_missing=False,
        )

    def _build_client(self):
        class _DummyClient:
            def disconnect(self):
                return None

        return _DummyClient()

    def _execute(self, query: str, params: Any = None):
        self.captured_queries.append((query, params))
        if "SELECT\n                variant_table" in query:
            return list(self.rows_to_return)
        return []


class ClickHouseCeleryRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = ConnectionConfig(
            id="prod_ch",
            host="localhost",
            port=9000,
            login="default",
            password="secret",
            dbms="clickhouse",
            credential_type="password",
        )

    def test_execution_adapter_dispatches_source_and_variant_tasks(self) -> None:
        source_result_payload = {
            "baseline_id": "baseline-1",
            "benchmark_run_id": 11,
            "benchmark_started_at": datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc).isoformat(),
            "benchmark_id": "bench_a",
            "source_database": "analytics",
            "source_table": "events",
            "source_table_ddl": EVENTS_DDL,
            "score": 1.0,
            "metrics": {"status": "ok"},
        }
        fake_app = _FakeCeleryApp(source_payload=source_result_payload)
        adapter = CeleryClickHouseExecutionAdapter(
            connections_by_id={"prod_ch": self.connection},
            celery_app=fake_app,
            progress_monitor_enabled=False,
        )

        source_job = SourceBenchmarkJob(
            benchmark_run_id=11,
            benchmark_started_at=datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc),
            benchmark_id="bench_a",
            connection_id="prod_ch",
            connection_dbms="clickhouse",
            source_database="analytics",
            test_database="bench_tmp",
            source_table="events",
            source_table_ddl=TableDDL.from_ddl(EVENTS_DDL),
            query_plan=QueryPlan(
                warmup_queries=["SELECT 1"],
                test_queries=[Query(query="SELECT count() FROM `analytics`.`events`")],
            ),
            max_iterations=3,
            insert_rows_limit=100,
            celery=CeleryConfig(workers=2, threads_per_worker=1),
        )
        source_result = adapter.execute_source_benchmark(source_job)
        self.assertEqual(source_result.benchmark_id, "bench_a")

        planner = BenchmarkPlanner(
            config=BenchmarkRootConfig(
                connections=[self.connection],
                benchmarks=[
                    BenchmarkConfig(
                        id="bench_a",
                        connection_id="prod_ch",
                        strategy="types_strategy",
                        databases=["analytics"],
                        tables=["events"],
                        max_iterations=1,
                        global_rules=RulesConfig(
                            column_rules=[
                                ColumnRuleConfig(
                                    by_type="UInt64",
                                    types=["UInt64", "UInt32"],
                                )
                            ]
                        ),
                    )
                ],
                rule_banks={},
                default_rule_banks={},
                celery=CeleryConfig(workers=2, threads_per_worker=1),
            ),
            providers_by_connection_id={"prod_ch": _StaticMetadataProvider()},
        )
        engine = BenchmarkEngine(planner=planner)
        job = next(
            engine.iter_variant_jobs(
                benchmark_ids=["bench_a"],
                benchmark_run_id=11,
                benchmark_started_at=datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc),
            )
        )
        dispatch_ack = adapter.execute_variant(job)

        self.assertEqual(dispatch_ack.variant_table, job.variant_table)
        self.assertIsNone(dispatch_ack.score)
        self.assertEqual(len(fake_app.calls), 2)
        self.assertEqual(fake_app.calls[0]["task_name"], "bench.source_benchmark")
        self.assertEqual(fake_app.calls[1]["task_name"], "bench.variant_benchmark")
        self.assertFalse(fake_app.calls[0]["ignore_result"])
        self.assertTrue(fake_app.calls[1]["ignore_result"])
        self.assertEqual(
            fake_app.calls[0]["kwargs"]["payload"]["test_database"],
            "bench_tmp",
        )

    def test_variant_task_is_configured_to_ignore_backend_results(self) -> None:
        if celery_worker_app is None:
            self.skipTest("Celery app недоступен в тестовом окружении")

        source_task = celery_worker_app.tasks[SOURCE_BENCHMARK_TASK_NAME]
        variant_task = celery_worker_app.tasks[VARIANT_BENCHMARK_TASK_NAME]

        self.assertFalse(source_task.ignore_result)
        self.assertTrue(variant_task.ignore_result)
        self.assertFalse(celery_worker_app.conf.task_store_errors_even_if_ignored)

    def test_sequential_strategy_calls_progress_wait_hooks(self) -> None:
        benchmark = BenchmarkConfig(
            id="bench_seq",
            connection_id="prod_ch",
            strategy="sequential_topn_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=2,
            sequential_top_n=1,
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])
                ],
                index_rules=[
                    IndexRuleConfig(
                        by_type="UInt64",
                        indexes=[IndexConfig(type="set(100)", granularity=1)],
                    )
                ],
            ),
        )
        planner = BenchmarkPlanner(
            config=BenchmarkRootConfig(
                connections=[self.connection],
                benchmarks=[benchmark],
                rule_banks={},
                default_rule_banks={},
                celery=CeleryConfig(workers=2, threads_per_worker=1),
            ),
            providers_by_connection_id={"prod_ch": _StaticMetadataProvider()},
        )
        engine = BenchmarkEngine(planner=planner)
        adapter = _SequentialAdapterWithProgressHooks()
        store = InMemoryBenchmarkResultStore()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=store,
        )

        run_id = runner.run()
        self.assertEqual(run_id, 1)
        self.assertGreaterEqual(len(adapter.open_calls), 2)
        self.assertGreaterEqual(len(adapter.wait_calls), 2)
        self.assertGreaterEqual(adapter.finalize_calls, 1)

    def test_clickhouse_result_store_parses_top_variants(self) -> None:
        rows = [
            (
                "events__bench__bench_seq__0002",
                EVENTS_DDL.replace("UInt64", "UInt32", 1),
                10.0,
            ),
            (
                "events__bench__bench_seq__0001",
                EVENTS_DDL,
                5.0,
            ),
        ]
        store = _FakeClickHouseResultStore(rows_to_return=rows)
        top = store.get_top_type_variants(
            benchmark_run_id=1,
            benchmark_id="bench_seq",
            source_database="analytics",
            source_table="events",
            top_n=2,
        )

        self.assertEqual(len(top), 2)
        self.assertEqual(top[0].variant_index, 2)
        self.assertEqual(top[0].variant_ddl.column("user_id").type, "UInt32")
        self.assertEqual(top[1].variant_index, 1)


if __name__ == "__main__":
    unittest.main()
