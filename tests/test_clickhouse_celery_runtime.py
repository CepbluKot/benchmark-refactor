import json
import unittest
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import patch

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
import src.benchmark_runtime.implementations.clickhouse_celery.execution as execution_module
from src.benchmark_runtime.implementations.clickhouse_celery.tasks import (
    SOURCE_BENCHMARK_TASK_NAME,
    TaskPayloadRefPayload,
    VARIANT_BENCHMARK_TASK_NAME,
    app as celery_worker_app,
)
from src.benchmark_runtime.implementations.clickhouse_celery.settings import (
    get_clickhouse_celery_worker_settings,
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


class _FlakySendTaskCeleryApp(_FakeCeleryApp):
    def __init__(self, source_payload: Dict[str, Any], *, fail_variant_times: int = 1) -> None:
        super().__init__(source_payload=source_payload)
        self._fail_variant_times = max(0, int(fail_variant_times))

    def send_task(self, task_name: str, **kwargs: Any) -> _FakeAsyncResult:
        if task_name == VARIANT_BENCHMARK_TASK_NAME and self._fail_variant_times > 0:
            self._fail_variant_times -= 1
            raise OSError("connection refused")
        return super().send_task(task_name, **kwargs)


class _RejectPublishFlakyCeleryApp(_FakeCeleryApp):
    def __init__(self, source_payload: Dict[str, Any], *, fail_variant_times: int = 1) -> None:
        super().__init__(source_payload=source_payload)
        self._fail_variant_times = max(0, int(fail_variant_times))

    def send_task(self, task_name: str, **kwargs: Any) -> _FakeAsyncResult:
        if task_name == VARIANT_BENCHMARK_TASK_NAME and self._fail_variant_times > 0:
            self._fail_variant_times -= 1
            raise RuntimeError("Queue overflow: reject-publish")
        return super().send_task(task_name, **kwargs)


class _ThrottleFakeMonitor:
    """Минимальный monitor-двойник для проверки in-flight throttling."""

    def __init__(self, in_flight_sequence: list[int]) -> None:
        self._in_flight_sequence = list(in_flight_sequence) or [0]
        self.in_flight_calls = 0
        self.registered_task_ids: list[str] = []

    def new_task_id(self) -> str:
        return "variant-test-task-id"

    def register_task(self, task_id: str) -> None:
        self.registered_task_ids.append(task_id)

    def in_flight_tasks(self) -> int:
        idx = min(self.in_flight_calls, len(self._in_flight_sequence) - 1)
        self.in_flight_calls += 1
        return max(0, int(self._in_flight_sequence[idx]))


class _SequentialAdapterWithProgressHooks:
    def __init__(self) -> None:
        self._store = None
        self.executed_jobs: list[VariantJob] = []
        self.wait_calls: list[str] = []
        self.open_calls: list[str] = []
        self.open_global_calls: list[dict[str, Any]] = []
        self.finalize_calls = 0
        self.finalize_global_calls = 0

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

    def open_global_progress_scope(
        self,
        scope_name: str,
        total_tasks: int | None = None,
    ) -> None:
        self.open_global_calls.append(
            {"scope_name": scope_name, "total_tasks": total_tasks}
        )

    def wait_for_dispatched_tasks(self, stage_label: str, timeout: float | None = None) -> bool:
        del timeout
        self.wait_calls.append(stage_label)
        return True

    def finalize_progress_scope(self, wait: bool = False, timeout: float | None = None) -> None:
        del wait, timeout
        self.finalize_calls += 1

    def finalize_global_progress_scope(self, wait: bool = False, timeout: float | None = None) -> None:
        del wait, timeout
        self.finalize_global_calls += 1


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

    def _init_redis_lock_client(self) -> None:
        class _NoopRedisLock:
            def acquire(self, blocking: bool = True) -> bool:
                del blocking
                return True

            def release(self) -> None:
                return None

        class _NoopRedisClient:
            def lock(
                self,
                name: str,
                timeout: float | None = None,
                blocking_timeout: float | None = None,
            ) -> _NoopRedisLock:
                del name, timeout, blocking_timeout
                return _NoopRedisLock()

        self._record_lock_redis_client = _NoopRedisClient()

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
                test_queries=[
                    Query(
                        query_id="q_count_events",
                        query="SELECT count() FROM `analytics`.`events`",
                        warmup_queries=["SELECT 1"],
                    )
                ],
            ),
            insert_operations_count=3,
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
                        insert_operations_count=1,
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
        self.assertIsNone(fake_app.calls[0]["expires"])
        self.assertIsNone(fake_app.calls[1]["expires"])
        self.assertEqual(
            fake_app.calls[0]["kwargs"]["payload"]["test_database"],
            "bench_tmp",
        )
        self.assertEqual(
            fake_app.calls[0]["kwargs"]["payload"]["scoring"]["mode"],
            "expression",
        )
        self.assertEqual(
            fake_app.calls[1]["kwargs"]["payload"]["scoring"]["mode"],
            "expression",
        )
        self.assertEqual(
            fake_app.calls[0]["kwargs"]["payload"]["query_plan"]["test_queries"][0]["query_type"],
            "generic",
        )
        self.assertIn(
            fake_app.calls[1]["kwargs"]["payload"]["query_plan"]["test_queries"][0]["query_type"],
            {"hit", "miss", "generic", "manual"},
        )

    def test_execute_variant_retries_dispatch_after_transient_broker_error(self) -> None:
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
        fake_app = _FlakySendTaskCeleryApp(
            source_payload=source_result_payload,
            fail_variant_times=1,
        )
        adapter = CeleryClickHouseExecutionAdapter(
            connections_by_id={"prod_ch": self.connection},
            celery_app=fake_app,
            progress_monitor_enabled=False,
        )

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
                        insert_operations_count=1,
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

        original_attempts = execution_module._CELERY_RECONNECT_MAX_ATTEMPTS
        original_initial_sleep = execution_module._CELERY_RECONNECT_INITIAL_SLEEP_SEC
        original_max_sleep = execution_module._CELERY_RECONNECT_MAX_SLEEP_SEC
        execution_module._CELERY_RECONNECT_MAX_ATTEMPTS = 3
        execution_module._CELERY_RECONNECT_INITIAL_SLEEP_SEC = 0.0
        execution_module._CELERY_RECONNECT_MAX_SLEEP_SEC = 0.0
        try:
            dispatch_ack = adapter.execute_variant(job)
        finally:
            execution_module._CELERY_RECONNECT_MAX_ATTEMPTS = original_attempts
            execution_module._CELERY_RECONNECT_INITIAL_SLEEP_SEC = original_initial_sleep
            execution_module._CELERY_RECONNECT_MAX_SLEEP_SEC = original_max_sleep

        self.assertEqual(dispatch_ack.variant_table, job.variant_table)
        variant_calls = [
            call for call in fake_app.calls if call.get("task_name") == VARIANT_BENCHMARK_TASK_NAME
        ]
        self.assertEqual(len(variant_calls), 1)

    def test_execute_variant_respects_in_flight_limit(self) -> None:
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
        adapter._global_progress_monitor = _ThrottleFakeMonitor([2, 2, 1])  # type: ignore[assignment]

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
                        insert_operations_count=1,
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

        original_limit = execution_module._CELERY_MAX_IN_FLIGHT_TASKS
        original_poll = execution_module._CELERY_IN_FLIGHT_WAIT_POLL_SEC
        original_timeout = execution_module._CELERY_IN_FLIGHT_WAIT_TIMEOUT_SEC
        execution_module._CELERY_MAX_IN_FLIGHT_TASKS = 2
        execution_module._CELERY_IN_FLIGHT_WAIT_POLL_SEC = 0.0
        execution_module._CELERY_IN_FLIGHT_WAIT_TIMEOUT_SEC = 1.0
        try:
            dispatch_ack = adapter.execute_variant(job)
        finally:
            execution_module._CELERY_MAX_IN_FLIGHT_TASKS = original_limit
            execution_module._CELERY_IN_FLIGHT_WAIT_POLL_SEC = original_poll
            execution_module._CELERY_IN_FLIGHT_WAIT_TIMEOUT_SEC = original_timeout

        self.assertEqual(dispatch_ack.variant_table, job.variant_table)
        variant_calls = [
            call for call in fake_app.calls if call.get("task_name") == VARIANT_BENCHMARK_TASK_NAME
        ]
        self.assertEqual(len(variant_calls), 1)
        monitor = adapter._global_progress_monitor
        self.assertIsNotNone(monitor)
        assert monitor is not None
        self.assertGreaterEqual(monitor.in_flight_calls, 3)

    def test_execute_variant_retries_on_reject_publish_when_queue_is_full(self) -> None:
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
        fake_app = _RejectPublishFlakyCeleryApp(
            source_payload=source_result_payload,
            fail_variant_times=2,
        )
        adapter = CeleryClickHouseExecutionAdapter(
            connections_by_id={"prod_ch": self.connection},
            celery_app=fake_app,
            progress_monitor_enabled=False,
        )

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
                        insert_operations_count=1,
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

        original_reconnect_attempts = execution_module._CELERY_RECONNECT_MAX_ATTEMPTS
        original_reject_attempts = execution_module._CELERY_REJECT_PUBLISH_MAX_ATTEMPTS
        original_reject_sleep = execution_module._CELERY_REJECT_PUBLISH_RETRY_SLEEP_SEC
        execution_module._CELERY_RECONNECT_MAX_ATTEMPTS = 0
        execution_module._CELERY_REJECT_PUBLISH_MAX_ATTEMPTS = 3
        execution_module._CELERY_REJECT_PUBLISH_RETRY_SLEEP_SEC = 0.0
        try:
            dispatch_ack = adapter.execute_variant(job)
        finally:
            execution_module._CELERY_RECONNECT_MAX_ATTEMPTS = original_reconnect_attempts
            execution_module._CELERY_REJECT_PUBLISH_MAX_ATTEMPTS = original_reject_attempts
            execution_module._CELERY_REJECT_PUBLISH_RETRY_SLEEP_SEC = original_reject_sleep

        self.assertEqual(dispatch_ack.variant_table, job.variant_table)
        variant_calls = [
            call for call in fake_app.calls if call.get("task_name") == VARIANT_BENCHMARK_TASK_NAME
        ]
        self.assertEqual(len(variant_calls), 1)

    def test_execute_variant_sends_payload_ref_when_payload_store_enabled(self) -> None:
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
        fake_ref = TaskPayloadRefPayload(
            payload_id="payload-id-1",
            payload_kind="variant",
            storage_connection=adapter._to_connection_payload(self.connection),
            storage_database="benchmark_results",
            storage_table="benchmark_task_payloads",
        )

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
                        insert_operations_count=1,
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

        original_payload_store_enabled = execution_module._CELERY_PAYLOAD_STORE_ENABLED
        execution_module._CELERY_PAYLOAD_STORE_ENABLED = True
        adapter._payload_store_enabled = True
        with patch.object(
            adapter,
            "_store_payload_in_db",
            return_value=fake_ref,
        ) as store_payload_mock:
            dispatch_ack = adapter.execute_variant(job)
        execution_module._CELERY_PAYLOAD_STORE_ENABLED = original_payload_store_enabled

        self.assertEqual(dispatch_ack.variant_table, job.variant_table)
        store_payload_mock.assert_called_once()
        variant_calls = [
            call for call in fake_app.calls if call.get("task_name") == VARIANT_BENCHMARK_TASK_NAME
        ]
        self.assertEqual(len(variant_calls), 1)
        variant_call_kwargs = variant_calls[0]["kwargs"]
        self.assertIn("payload_ref", variant_call_kwargs)
        self.assertNotIn("payload", variant_call_kwargs)
        self.assertEqual(
            variant_call_kwargs["payload_ref"]["payload_id"],
            "payload-id-1",
        )

    def test_variant_task_is_configured_to_ignore_backend_results(self) -> None:
        if celery_worker_app is None:
            self.skipTest("Celery app недоступен в тестовом окружении")
        settings = get_clickhouse_celery_worker_settings()

        source_task = celery_worker_app.tasks[SOURCE_BENCHMARK_TASK_NAME]
        variant_task = celery_worker_app.tasks[VARIANT_BENCHMARK_TASK_NAME]

        self.assertFalse(source_task.ignore_result)
        self.assertTrue(variant_task.ignore_result)
        self.assertFalse(celery_worker_app.conf.task_store_errors_even_if_ignored)
        self.assertIsNone(celery_worker_app.conf.task_default_expires)
        self.assertIsNone(celery_worker_app.conf.task_queue_ttl)
        self.assertIsNone(celery_worker_app.conf.task_queue_expires)
        self.assertEqual(celery_worker_app.conf.task_default_delivery_mode, "persistent")
        self.assertEqual(celery_worker_app.conf.task_default_queue, "bench.benchmark")
        self.assertEqual(
            celery_worker_app.conf.worker_prefetch_multiplier,
            settings.celery_worker_prefetch_multiplier,
        )
        self.assertEqual(celery_worker_app.conf.task_acks_late, settings.celery_task_acks_late)
        self.assertEqual(
            celery_worker_app.conf.task_reject_on_worker_lost,
            settings.celery_task_reject_on_worker_lost,
        )
        self.assertEqual(celery_worker_app.conf.broker_pool_limit, settings.celery_broker_pool_limit)
        self.assertEqual(celery_worker_app.conf.broker_heartbeat, settings.celery_broker_heartbeat_sec)
        self.assertEqual(celery_worker_app.conf.task_compression, settings.celery_task_compression)
        self.assertEqual(celery_worker_app.conf.result_compression, settings.celery_result_compression)

    def test_sequential_strategy_calls_progress_wait_hooks(self) -> None:
        benchmark = BenchmarkConfig(
            id="bench_seq",
            connection_id="prod_ch",
            strategy="sequential_topn_strategy",
            databases=["analytics"],
            tables=["events"],
            insert_operations_count=2,
            sequential_types_top_n_for_indexes=1,
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
        self.assertEqual(len(adapter.open_global_calls), 1)
        self.assertIsNotNone(adapter.open_global_calls[0]["total_tasks"])
        self.assertGreater(adapter.open_global_calls[0]["total_tasks"], 0)
        self.assertEqual(adapter.finalize_global_calls, 1)
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
