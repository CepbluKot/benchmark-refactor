import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from src.benchmark_runtime.implementations.clickhouse_celery.tasks import (
    ConnectionPayload,
    _ClickHouseRuntimeClient,
    _bytes_per_second,
    _error_query_metrics,
    _measure_insert,
    _measure_select_queries,
    _rows_per_second,
    QueryPlanPayload,
    SourceBenchmarkTaskPayload,
    VariantBenchmarkTaskPayload,
    run_source_benchmark,
    run_variant_benchmark,
)


class _FakeRuntimeClient:
    def __init__(
        self,
        *,
        query_metrics_sequence: Optional[List[Dict[str, float]]] = None,
        count_rows_map: Optional[Dict[tuple[str, str], int]] = None,
        column_sizes_map: Optional[Dict[tuple[str, str], Dict[str, Dict[str, Any]]]] = None,
        index_sizes_map: Optional[Dict[tuple[str, str], Dict[str, Dict[str, Any]]]] = None,
        total_size_map: Optional[Dict[tuple[str, str], float]] = None,
        raise_on_execute_query: Optional[str] = None,
        retry_policy: tuple[int, float, float] = (0, 0.0, 0.0),
    ) -> None:
        self.query_metrics_sequence = list(query_metrics_sequence or [])
        self.count_rows_map = dict(count_rows_map or {})
        self.column_sizes_map = dict(column_sizes_map or {})
        self.index_sizes_map = dict(index_sizes_map or {})
        self.total_size_map = dict(total_size_map or {})
        self.raise_on_execute_query = raise_on_execute_query
        self.retry_policy = retry_policy

        self.execute_calls: List[str] = []
        self.execute_with_metrics_calls: List[str] = []
        self.insert_with_metrics_calls: List[Dict[str, Any]] = []
        self.select_with_metrics_calls: List[str] = []
        self.created_databases: List[str] = []
        self.drop_calls: List[tuple[str, str]] = []
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def execute(self, query: str, params: Optional[Dict[str, Any]] = None):
        del params
        self.execute_calls.append(query)
        if self.raise_on_execute_query is not None and query == self.raise_on_execute_query:
            raise RuntimeError("synthetic execute failure")
        return []

    def create_database_if_not_exists(self, database: str) -> None:
        self.created_databases.append(database)

    def drop_table_if_exists(self, database: str, table: str) -> None:
        self.drop_calls.append((database, table))

    def count_rows(self, database: str, table: str) -> int:
        return int(self.count_rows_map.get((database, table), 0))

    def get_column_sizes(self, database: str, table: str) -> Dict[str, Dict[str, Any]]:
        return dict(self.column_sizes_map.get((database, table), {}))

    def get_index_sizes(self, database: str, table: str) -> Dict[str, Dict[str, Any]]:
        return dict(self.index_sizes_map.get((database, table), {}))

    def get_total_compressed_size_bytes(self, database: str, table: str) -> float:
        return float(self.total_size_map.get((database, table), 0.0))

    def execute_with_query_log_metrics(
        self,
        query: str,
        *,
        query_tag: str,
        poll_attempts: int = 25,
        poll_sleep_sec: float = 0.1,
    ) -> Dict[str, float]:
        del query_tag, poll_attempts, poll_sleep_sec
        self.execute_with_metrics_calls.append(query)
        if not self.query_metrics_sequence:
            raise AssertionError("Недостаточно synthetic query metrics для теста")
        return self.query_metrics_sequence.pop(0)

    def insert_from_source_with_metrics(
        self,
        *,
        source_database: str,
        source_table: str,
        target_database: str,
        target_table: str,
        n_rows: Optional[int],
        offset: int,
        strictly_adhere_n_rows: bool,
        query_tag: str,
        tested_cols: Optional[List[str]] = None,
    ) -> Dict[str, float]:
        del query_tag
        self.insert_with_metrics_calls.append(
            {
                "source_database": source_database,
                "source_table": source_table,
                "target_database": target_database,
                "target_table": target_table,
                "n_rows": n_rows,
                "offset": offset,
                "strictly_adhere_n_rows": strictly_adhere_n_rows,
                "tested_cols": list(tested_cols or []),
            }
        )
        if not self.query_metrics_sequence:
            raise AssertionError("Недостаточно synthetic insert metrics для теста")
        return self.query_metrics_sequence.pop(0)

    def execute_select_with_metrics(
        self,
        query: str,
        *,
        query_tag: str,
        poll_attempts: int = 25,
        poll_sleep_sec: float = 0.1,
    ) -> Dict[str, float]:
        del query_tag, poll_attempts, poll_sleep_sec
        self.select_with_metrics_calls.append(query)
        if not self.query_metrics_sequence:
            raise AssertionError("Недостаточно synthetic select metrics для теста")
        return self.query_metrics_sequence.pop(0)

    def get_retry_policy(self) -> tuple[int, float, float]:
        return self.retry_policy


class _FakeResultStore:
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs
        self.store_calls: List[Dict[str, Any]] = []
        self.closed = False

    def store_worker_result(self, **kwargs) -> None:
        self.store_calls.append(kwargs)

    def close(self) -> None:
        self.closed = True


class ClickHouseCeleryTasksMetricsTests(unittest.TestCase):
    def _connection_payload(self) -> ConnectionPayload:
        return ConnectionPayload(
            host="localhost",
            port=9000,
            login="default",
            password="secret",
        )

    def test_run_source_benchmark_calculates_metrics_and_baseline_score(self) -> None:
        fake_client = _FakeRuntimeClient(
            query_metrics_sequence=[
                {
                    "elapsed_ns": 100_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                },
                {
                    "elapsed_ns": 200_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                },
                {
                    "elapsed_ns": 100_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                },
                {
                    "elapsed_ns": 200_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                },
            ],
            count_rows_map={("analytics", "events"): 321},
            column_sizes_map={
                ("analytics", "events"): {
                    "user_id": {
                        "name": "user_id",
                        "datatype": "UInt64",
                        "size_compressed_bytes": 400,
                        "size_compressed_bytes_readable": "400 B",
                    }
                }
            },
            total_size_map={("analytics", "events"): 1_024.0},
        )

        payload = SourceBenchmarkTaskPayload(
            connection=self._connection_payload(),
            benchmark_run_id=1,
            benchmark_started_at=datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc),
            benchmark_id="bench_source",
            source_database="analytics",
            test_database="bench_tmp",
            source_table="events",
            source_table_ddl="CREATE TABLE analytics.events (...) ENGINE=MergeTree ORDER BY user_id",
            query_plan=QueryPlanPayload(
                warmup_queries=["SELECT 1"],
                test_queries=["SELECT count() FROM `analytics`.`events`"],
            ),
            max_iterations=2,
            measured_percentiles=[50, 100],
        )

        with patch(
            "src.benchmark_runtime.implementations.clickhouse_celery.tasks._ClickHouseRuntimeClient",
            return_value=fake_client,
        ):
            result = run_source_benchmark(payload)

        self.assertAlmostEqual(result.score or 0.0, 1.0 / 200.0)
        self.assertEqual(result.metrics["source_table_insert_time_ms_measurements"], [100.0, 200.0])
        self.assertEqual(
            result.metrics["source_table_insert_time_ms_measurements_percentiles"],
            [150.0, 200.0],
        )
        self.assertEqual(result.metrics["source_table_select_time_ms_measurements"], [100.0, 200.0])
        self.assertEqual(
            result.metrics["source_table_select_time_ms_measurements_percentiles"],
            [150.0, 200.0],
        )
        per_query_metrics = result.metrics["source_table_select_metrics_by_query"]
        self.assertEqual(len(per_query_metrics), 1)
        self.assertIn("SELECT count()", per_query_metrics[0]["query"])
        self.assertEqual(per_query_metrics[0]["elapsed_ms_percentiles"], [150.0, 200.0])
        self.assertEqual(result.metrics["total_n_rows_in_source_table"], 321)
        self.assertIn("`bench_tmp`.`events__source_baseline__", result.metrics["source_table_select_test_query"])
        self.assertIn("SELECT 1", fake_client.execute_calls)
        self.assertEqual(len(fake_client.insert_with_metrics_calls), 2)
        self.assertEqual(len(fake_client.select_with_metrics_calls), 2)
        self.assertTrue(
            all(
                "`bench_tmp`.`events__source_baseline__" in query
                for query in fake_client.select_with_metrics_calls
            )
        )
        self.assertIn("bench_tmp", fake_client.created_databases)
        self.assertTrue(
            any(
                database == "bench_tmp" and table.startswith("events__source_baseline__")
                for database, table in fake_client.drop_calls
            )
        )
        self.assertTrue(fake_client.closed)

    def test_run_source_benchmark_uses_test_db_fallback_when_not_provided(self) -> None:
        fake_client = _FakeRuntimeClient(
            query_metrics_sequence=[
                {
                    "elapsed_ns": 100_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 1000.0,
                    "written_bytes": 10_000.0,
                },
                {
                    "elapsed_ns": 100_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                },
            ],
            count_rows_map={("analytics", "events"): 321},
            column_sizes_map={("analytics", "events"): {}},
            total_size_map={("analytics", "events"): 1_024.0},
        )

        payload = SourceBenchmarkTaskPayload(
            connection=self._connection_payload(),
            benchmark_run_id=1,
            benchmark_started_at=datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc),
            benchmark_id="bench_source",
            source_database="analytics",
            source_table="events",
            source_table_ddl="CREATE TABLE analytics.events (...) ENGINE=MergeTree ORDER BY user_id",
            query_plan=QueryPlanPayload(
                warmup_queries=[],
                test_queries=["SELECT count() FROM `analytics`.`events`"],
            ),
            max_iterations=1,
            measured_percentiles=[100],
        )

        with patch(
            "src.benchmark_runtime.implementations.clickhouse_celery.tasks._ClickHouseRuntimeClient",
            return_value=fake_client,
        ):
            result = run_source_benchmark(payload)

        self.assertIn("`analytics__benchmark_tmp`.`events__source_baseline__", result.metrics["source_table_select_test_query"])
        self.assertIn("analytics__benchmark_tmp", fake_client.created_databases)
        self.assertTrue(
            any(
                database == "analytics__benchmark_tmp"
                and table.startswith("events__source_baseline__")
                for database, table in fake_client.drop_calls
            )
        )

    def test_run_source_benchmark_rewrites_mixed_qualified_table_refs(self) -> None:
        fake_client = _FakeRuntimeClient(
            query_metrics_sequence=[
                {
                    "elapsed_ns": 100_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 1000.0,
                    "written_bytes": 10_000.0,
                },
                {
                    "elapsed_ns": 100_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                },
            ],
            count_rows_map={("analytics", "events"): 10},
            column_sizes_map={("analytics", "events"): {}},
            total_size_map={("analytics", "events"): 1_024.0},
        )

        payload = SourceBenchmarkTaskPayload(
            connection=self._connection_payload(),
            benchmark_run_id=1,
            benchmark_started_at=datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc),
            benchmark_id="bench_source",
            source_database="analytics",
            test_database="bench_tmp",
            source_table="events",
            source_table_ddl="CREATE TABLE analytics.events (...) ENGINE=MergeTree ORDER BY user_id",
            query_plan=QueryPlanPayload(
                warmup_queries=[
                    "SELECT count() FROM `analytics`.events",
                ],
                test_queries=[
                    "SELECT count() FROM analytics.`events`",
                ],
            ),
            max_iterations=1,
            measured_percentiles=[100],
        )

        with patch(
            "src.benchmark_runtime.implementations.clickhouse_celery.tasks._ClickHouseRuntimeClient",
            return_value=fake_client,
        ):
            result = run_source_benchmark(payload)

        rewritten_ref = "`bench_tmp`.`events__source_baseline__"
        self.assertIn(rewritten_ref, result.metrics["source_table_select_test_query"])
        self.assertTrue(any(rewritten_ref in query for query in fake_client.execute_calls))
        self.assertTrue(any(rewritten_ref in query for query in fake_client.select_with_metrics_calls))

    def test_run_variant_benchmark_calculates_metrics_score_and_stores_result(self) -> None:
        fake_client = _FakeRuntimeClient(
            query_metrics_sequence=[
                {
                    "elapsed_ns": 100_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 1000.0,
                    "written_bytes": 10_000.0,
                },
                {
                    "elapsed_ns": 200_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 1000.0,
                    "written_bytes": 10_000.0,
                },
                {
                    "elapsed_ns": 50_000_000.0,
                    "read_rows": 500.0,
                    "read_bytes": 5_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                },
                {
                    "elapsed_ns": 100_000_000.0,
                    "read_rows": 500.0,
                    "read_bytes": 5_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                },
            ],
            count_rows_map={("bench_tmp", "events__bench__bench_var__0001"): 222},
            column_sizes_map={
                ("bench_tmp", "events__bench__bench_var__0001"): {
                    "user_id": {
                        "name": "user_id",
                        "datatype": "UInt32",
                        "size_compressed_bytes": 200,
                        "size_compressed_bytes_readable": "200 B",
                    },
                    "event_time": {
                        "name": "event_time",
                        "datatype": "DateTime",
                        "size_compressed_bytes": 100,
                        "size_compressed_bytes_readable": "100 B",
                    },
                }
            },
            index_sizes_map={
                ("bench_tmp", "events__bench__bench_var__0001"): {
                    "user_id": {
                        "size_compressed_bytes": 50,
                        "size_compressed_bytes_readable": "50 B",
                    }
                }
            },
            total_size_map={("bench_tmp", "events__bench__bench_var__0001"): 2000.0},
        )
        fake_store = _FakeResultStore()

        source_metrics = {
            "total_n_rows_in_source_table": 300,
            "source_table_insert_time_ms_measurements_percentiles": [300.0, 400.0],
            "source_table_select_time_ms_measurements_percentiles": [150.0, 200.0],
            "source_table_consumed_compressed_size_bytes_overall": 4000.0,
            "source_table_n_rows_in_size_test": 300,
            "source_table_consumed_compressed_size_bytes_by_each_column": {
                "user_id": {
                    "name": "user_id",
                    "datatype": "UInt64",
                    "size_compressed_bytes": 400,
                    "size_compressed_bytes_readable": "400 B",
                },
                "event_time": {
                    "name": "event_time",
                    "datatype": "DateTime",
                    "size_compressed_bytes": 200,
                    "size_compressed_bytes_readable": "200 B",
                },
            },
            "source_table_insert_rows_per_second_measurements": [1000.0],
            "source_table_insert_bytes_per_second_measurements": [10_000.0],
            "source_table_select_rows_per_second_measurements": [1200.0],
            "source_table_select_bytes_per_second_measurements": [12_000.0],
            "source_table_select_test_query": "SELECT count() FROM source",
        }

        payload = VariantBenchmarkTaskPayload(
            connection=self._connection_payload(),
            result_connection=self._connection_payload(),
            result_database="benchmark_results",
            result_table="combined_benchmark_results",
            benchmark_run_id=2,
            benchmark_started_at=datetime(2026, 2, 24, 13, 0, tzinfo=timezone.utc),
            benchmark_id="bench_var",
            source_database="analytics",
            source_table="events",
            variant_database="bench_tmp",
            variant_table="events__bench__bench_var__0001",
            variant_mode="types",
            variant_params={"index_choices": {"user_id": {"name": "idx_user_id"}}},
            variant_ddl="CREATE TABLE bench_tmp.events__bench__bench_var__0001 (...) ENGINE=MergeTree ORDER BY user_id",
            max_iterations=2,
            insert_rows_limit=1000,
            query_plan=QueryPlanPayload(
                warmup_queries=["SELECT 1"],
                test_queries=["SELECT count() FROM `bench_tmp`.`events__bench__bench_var__0001`"],
            ),
            source_benchmark={
                "source_table_ddl": "CREATE TABLE analytics.events (...) ENGINE=MergeTree ORDER BY user_id",
                "metrics": source_metrics,
            },
            measured_percentiles=[50, 100],
        )

        with patch(
            "src.benchmark_runtime.implementations.clickhouse_celery.tasks._ClickHouseRuntimeClient",
            return_value=fake_client,
        ), patch(
            "src.benchmark_runtime.implementations.clickhouse_celery.tasks.ClickHouseBenchmarkResultStore",
            return_value=fake_store,
        ):
            result = run_variant_benchmark(payload)

        self.assertAlmostEqual(result.score or 0.0, 2.0)
        self.assertEqual(result.total_n_rows_in_tested_table, 222)
        self.assertEqual(result.total_n_rows_in_source_table, 300)
        self.assertEqual(result.tested_table_insert_time_ms_measurements, [100.0, 200.0])
        self.assertEqual(result.tested_table_select_time_ms_measurements, [50.0, 100.0])
        self.assertEqual(
            result.tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs,
            [2.0, 2.0],
        )
        self.assertEqual(
            result.tested_table_select_time_ms_measurements_percentiles_speed_up_coefs,
            [2.0, 2.0],
        )
        tested_select_per_query = json.loads(result.tested_table_select_metrics_by_query_json or "[]")
        source_select_per_query = json.loads(result.source_table_select_metrics_by_query_json or "[]")
        select_speedup_by_query = json.loads(
            result.tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json or "[]"
        )
        self.assertEqual(len(tested_select_per_query), 1)
        self.assertEqual(len(source_select_per_query), 1)
        self.assertEqual(len(select_speedup_by_query), 1)
        self.assertEqual(
            select_speedup_by_query[0]["elapsed_ms_percentiles_speed_up_coefs"],
            [2.0, 2.0],
        )
        self.assertEqual(result.tested_table_compression_overall_coef, 2.0)

        self.assertEqual(len(fake_store.store_calls), 1)
        store_call = fake_store.store_calls[0]
        self.assertEqual(store_call["benchmark_run_id"], 2)
        self.assertEqual(store_call["variant_table"], "events__bench__bench_var__0001")
        stored_result = store_call["result"]
        self.assertAlmostEqual(stored_result.score or 0.0, 2.0)

        parsed_index_pct = json.loads(result.tested_table_indexes_sizes_percent_from_col_size or "{}")
        self.assertEqual(parsed_index_pct.get("user_id"), 25.0)

        # Один drop перед созданием и один drop в finally.
        self.assertEqual(fake_client.drop_calls.count(("bench_tmp", "events__bench__bench_var__0001")), 2)
        self.assertTrue(fake_client.closed)
        self.assertTrue(fake_store.closed)
        self.assertEqual(len(fake_client.insert_with_metrics_calls), 2)
        self.assertTrue(all(call["strictly_adhere_n_rows"] for call in fake_client.insert_with_metrics_calls))
        self.assertTrue(
            all(call["tested_cols"] == ["user_id"] for call in fake_client.insert_with_metrics_calls)
        )
        self.assertEqual(len(fake_client.select_with_metrics_calls), 2)

    def test_run_variant_benchmark_closes_resources_on_failure(self) -> None:
        variant_ddl = "CREATE TABLE bench_tmp.events_failed (...) ENGINE=MergeTree ORDER BY user_id"
        fake_client = _FakeRuntimeClient(
            raise_on_execute_query=variant_ddl,
        )
        fake_store = _FakeResultStore()

        payload = VariantBenchmarkTaskPayload(
            connection=self._connection_payload(),
            result_connection=self._connection_payload(),
            result_database="benchmark_results",
            result_table="combined_benchmark_results",
            benchmark_run_id=3,
            benchmark_started_at=datetime(2026, 2, 24, 14, 0, tzinfo=timezone.utc),
            benchmark_id="bench_var_fail",
            source_database="analytics",
            source_table="events",
            variant_database="bench_tmp",
            variant_table="events_failed",
            variant_mode="combined",
            variant_params={},
            variant_ddl=variant_ddl,
            max_iterations=1,
            query_plan=QueryPlanPayload(warmup_queries=[], test_queries=[]),
            measured_percentiles=[50, 100],
        )

        with patch(
            "src.benchmark_runtime.implementations.clickhouse_celery.tasks._ClickHouseRuntimeClient",
            return_value=fake_client,
        ), patch(
            "src.benchmark_runtime.implementations.clickhouse_celery.tasks.ClickHouseBenchmarkResultStore",
            return_value=fake_store,
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic execute failure"):
                run_variant_benchmark(payload)

        self.assertGreaterEqual(fake_client.drop_calls.count(("bench_tmp", "events_failed")), 1)
        self.assertEqual(len(fake_store.store_calls), 0)
        self.assertTrue(fake_client.closed)
        self.assertTrue(fake_store.closed)

    def test_strict_insert_query_uses_numbers_and_respects_measurement_offset(self) -> None:
        query = _ClickHouseRuntimeClient._build_source_select_for_insert(
            source_database="analytics",
            source_table="events",
            n_rows=1000,
            offset=2000,
            strictly_adhere_n_rows=True,
            total_rows_in_source_table=300,
        )
        self.assertIn("numbers(repeats_not_equal_zero)", query)
        self.assertIn("intDiv(3000 + cnt - 1, cnt)", query)
        self.assertIn("LIMIT 1000 OFFSET 2000", query)

    def test_error_metrics_use_minus_one_sentinel(self) -> None:
        error_metrics = _error_query_metrics()
        self.assertEqual(error_metrics["elapsed_ns"], -1.0)
        self.assertEqual(error_metrics["read_rows"], -1.0)
        self.assertEqual(error_metrics["read_bytes"], -1.0)
        self.assertEqual(error_metrics["written_rows"], -1.0)
        self.assertEqual(error_metrics["written_bytes"], -1.0)

        self.assertEqual(_rows_per_second(-1.0, -1.0), -1.0)
        self.assertEqual(_bytes_per_second(-1.0, -1.0), -1.0)
        self.assertEqual(_rows_per_second(100.0, 0.0), -1.0)
        self.assertEqual(_bytes_per_second(1000.0, 0.0), -1.0)

    def test_insert_query_applies_tested_cols_filter(self) -> None:
        query = _ClickHouseRuntimeClient._build_source_select_for_insert(
            source_database="analytics",
            source_table="events",
            n_rows=100,
            offset=0,
            strictly_adhere_n_rows=False,
            total_rows_in_source_table=None,
            tested_cols=["payload", "user`id"],
        )
        self.assertIn("toString(`payload`) != ''", query)
        self.assertIn("toString(`user``id`) != ''", query)

    def test_insert_returns_error_metrics_when_stream_slot_not_acquired(self) -> None:
        class _DummyStreamClient:
            def raw_stream(self, query: str, fmt: str = "Native"):
                del query, fmt
                raise AssertionError("raw_stream не должен вызываться без stream slot")

        client = _ClickHouseRuntimeClient.__new__(_ClickHouseRuntimeClient)
        client._stream_connection = SimpleNamespace(
            host="localhost",
            port=9000,
            login="default",
        )
        client._stream_client = _DummyStreamClient()
        client._stream_client_checked = True
        client._stream_slot_acquire_timeout_sec = 1.0
        client._max_concurrent_streams_per_process = 1

        with patch.object(client, "_acquire_stream_slot", return_value=False):
            metrics = client.insert_from_source_with_metrics(
                source_database="analytics",
                source_table="events",
                target_database="bench_tmp",
                target_table="events_variant",
                n_rows=None,
                offset=0,
                strictly_adhere_n_rows=False,
                query_tag="insert-test-no-slot",
            )

        self.assertEqual(metrics, _error_query_metrics())

    def test_measure_select_queries_retries_until_success(self) -> None:
        fake_client = _FakeRuntimeClient(
            query_metrics_sequence=[
                _error_query_metrics(),
                {
                    "elapsed_ns": 100_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                },
            ],
            retry_policy=(1, 0.0, 0.0),
        )

        stats = _measure_select_queries(
            fake_client,
            test_queries=["SELECT count() FROM `analytics`.`events`"],
            n_measurements=1,
        )

        self.assertEqual(stats["elapsed_ns"], [100_000_000.0])
        self.assertEqual(len(stats["per_query"]), 1)
        self.assertEqual(stats["per_query"][0]["query"], "SELECT count() FROM `analytics`.`events`")
        self.assertEqual(len(fake_client.select_with_metrics_calls), 2)

    def test_measure_select_queries_tracks_each_query_separately(self) -> None:
        fake_client = _FakeRuntimeClient(
            query_metrics_sequence=[
                {
                    "elapsed_ns": 100_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                },
                {
                    "elapsed_ns": 300_000_000.0,
                    "read_rows": 3000.0,
                    "read_bytes": 30_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                },
            ],
            retry_policy=(0, 0.0, 0.0),
        )

        stats = _measure_select_queries(
            fake_client,
            test_queries=[
                "SELECT count() FROM t1",
                "SELECT count() FROM t2",
            ],
            n_measurements=1,
        )

        self.assertEqual(stats["elapsed_ns"], [100_000_000.0, 300_000_000.0])
        self.assertEqual(len(stats["per_query"]), 2)
        self.assertEqual(stats["per_query"][0]["query"], "SELECT count() FROM t1")
        self.assertEqual(stats["per_query"][0]["elapsed_ns_measurements"], [100_000_000.0])
        self.assertEqual(stats["per_query"][1]["query"], "SELECT count() FROM t2")
        self.assertEqual(stats["per_query"][1]["elapsed_ns_measurements"], [300_000_000.0])

    def test_measure_insert_retries_until_success(self) -> None:
        fake_client = _FakeRuntimeClient(
            query_metrics_sequence=[
                _error_query_metrics(),
                {
                    "elapsed_ns": 150_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 1000.0,
                    "written_bytes": 10_000.0,
                },
            ],
            retry_policy=(1, 0.0, 0.0),
        )

        stats = _measure_insert(
            fake_client,
            source_database="analytics",
            source_table="events",
            target_database="bench_tmp",
            target_table="events_variant",
            n_rows=1000,
            n_measurements=1,
        )

        self.assertEqual(stats["elapsed_ns"], [150_000_000.0])
        self.assertEqual(len(fake_client.insert_with_metrics_calls), 2)


if __name__ == "__main__":
    unittest.main()
