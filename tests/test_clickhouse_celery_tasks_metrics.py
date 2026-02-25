import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from src.benchmark_runtime.implementations.clickhouse_celery import tasks as celery_tasks_module
from src.benchmark_runtime.implementations.clickhouse_celery.common import (
    make_readable_bytes,
)
from src.benchmark_runtime.implementations.clickhouse_celery.tasks import (
    ConnectionPayload,
    _ClickHouseRuntimeClient,
    _bytes_per_second,
    _error_query_metrics,
    _measure_insert,
    _measure_select_queries,
    _rows_per_second,
    QueryPayload,
    QueryPlanPayload,
    SourceBenchmarkTaskPayload,
    VariantBenchmarkTaskPayload,
    run_source_benchmark,
    run_variant_benchmark,
)
from src.benchmark_runtime.types import build_index_params_json

VALID_SOURCE_DDL = """
CREATE TABLE analytics.events
(
    `user_id` UInt64,
    `event_time` DateTime
)
ENGINE = MergeTree
ORDER BY user_id
"""

VALID_VARIANT_DDL = """
CREATE TABLE bench_tmp.events__bench__bench_var__0001
(
    `user_id` UInt32,
    `event_time` DateTime
)
ENGINE = MergeTree
ORDER BY user_id
"""

VALID_FAILED_VARIANT_DDL = """
CREATE TABLE bench_tmp.events__bench__bench_var_fail__9999
(
    `user_id` UInt32,
    `event_time` DateTime
)
ENGINE = MergeTree
ORDER BY user_id
"""


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
        self.insert_with_metrics_calls: List[Dict[str, Any]] = []
        self.select_with_metrics_calls: List[str] = []
        self.created_databases: List[str] = []
        self.drop_calls: List[tuple[str, str]] = []
        self.allowed_drop_databases: List[str] = []
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def execute(self, query: str, params: Optional[Dict[str, Any]] = None):
        del params
        self.execute_calls.append(query)
        if self.raise_on_execute_query is not None and query == self.raise_on_execute_query:
            raise RuntimeError("synthetic execute failure")
        return []

    def execute_user_read_only_query(self, query: str) -> list:
        return self.execute(query)

    def create_database_if_not_exists(self, database: str) -> None:
        self.created_databases.append(database)

    def drop_table_if_exists(
        self,
        database: str,
        table: str,
        *,
        allowed_database: str,
    ) -> None:
        self.drop_calls.append((database, table))
        self.allowed_drop_databases.append(allowed_database)

    def count_rows(self, database: str, table: str) -> int:
        exact = self.count_rows_map.get((database, table))
        if exact is not None:
            return int(exact)

        if "__source_baseline__" in table:
            synthetic_total = 0
            for call in self.insert_with_metrics_calls:
                if (
                    call["target_database"] == database
                    and call["target_table"] == table
                ):
                    n_rows = call["n_rows"]
                    if n_rows is None:
                        synthetic_total += int(
                            self.count_rows_map.get(
                                (call["source_database"], call["source_table"]),
                                0,
                            )
                        )
                    else:
                        synthetic_total += int(n_rows)
            if synthetic_total > 0:
                return synthetic_total

        return 0

    def get_column_sizes(self, database: str, table: str) -> Dict[str, Dict[str, Any]]:
        return dict(self.column_sizes_map.get((database, table), {}))

    def get_index_sizes(self, database: str, table: str) -> Dict[str, Dict[str, Any]]:
        return dict(self.index_sizes_map.get((database, table), {}))

    def get_total_compressed_size_bytes(self, database: str, table: str) -> float:
        return float(self.total_size_map.get((database, table), 0.0))

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

    def _variant_task_payload_dict(self) -> Dict[str, Any]:
        """Возвращает минимальный валидный payload для variant Celery task."""
        started_at = datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc).isoformat()
        return {
            "connection": {
                "host": "localhost",
                "port": 9000,
                "login": "default",
                "password": "secret",
            },
            "result_connection": {
                "host": "localhost",
                "port": 9000,
                "login": "default",
                "password": "secret",
            },
            "result_database": "benchmark_results",
            "result_table": "combined_benchmark_results",
            "benchmark_run_id": 101,
            "benchmark_started_at": started_at,
            "benchmark_id": "bench_variant_task",
            "source_database": "analytics",
            "source_table": "events",
            "variant_database": "bench_tmp",
            "variant_table": "events__bench__bench_var__0001",
            "variant_mode": "types",
            "variant_params": {},
            "variant_ddl": VALID_VARIANT_DDL,
            "max_iterations": 1,
            "insert_rows_limit": 1000,
            "query_plan": {
                "test_queries": ["SELECT count() FROM `bench_tmp`.`events__bench__bench_var__0001`"],
            },
        }

    def test_run_source_benchmark_calculates_metrics_and_baseline_score(self) -> None:
        fake_client = _FakeRuntimeClient(
            query_metrics_sequence=[
                {
                    "elapsed_ns": 100_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                    "memory_usage": 1024.0,
                },
                {
                    "elapsed_ns": 200_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                    "memory_usage": 2048.0,
                },
                {
                    "elapsed_ns": 100_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                    "memory_usage": 4096.0,
                },
                {
                    "elapsed_ns": 200_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                    "memory_usage": 8192.0,
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
            source_table_ddl=VALID_SOURCE_DDL,
            query_plan=QueryPlanPayload(
                test_queries=[
                    {
                        "query": "SELECT count() FROM `analytics`.`events`",
                        "cache_mode": "warm",
                        "select_operations_count": 2,
                        "warmup_queries": ["SELECT 1"],
                    }
                ],
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
        self.assertEqual(
            result.metrics["source_table_insert_memory_usage_measurements"],
            [1024.0, 2048.0],
        )
        self.assertEqual(
            result.metrics["source_table_insert_memory_usage_measurements_readable"],
            [make_readable_bytes(1024.0), make_readable_bytes(2048.0)],
        )
        self.assertEqual(
            result.metrics["source_table_insert_memory_usage_measurements_percentiles_readable"],
            [make_readable_bytes(1536.0), make_readable_bytes(2048.0)],
        )
        self.assertEqual(result.metrics["source_table_select_time_ms_measurements"], [100.0, 200.0])
        self.assertEqual(
            result.metrics["source_table_select_time_ms_measurements_percentiles"],
            [150.0, 200.0],
        )
        self.assertEqual(
            result.metrics["source_table_select_memory_usage_measurements"],
            [4096.0, 8192.0],
        )
        self.assertEqual(
            result.metrics["source_table_select_memory_usage_measurements_readable"],
            [make_readable_bytes(4096.0), make_readable_bytes(8192.0)],
        )
        self.assertEqual(
            result.metrics["source_table_select_memory_usage_measurements_percentiles_readable"],
            [make_readable_bytes(6144.0), make_readable_bytes(8192.0)],
        )
        per_query_metrics = result.metrics["source_table_select_metrics_by_query"]
        self.assertEqual(len(per_query_metrics), 1)
        self.assertIn("SELECT count()", per_query_metrics[0]["query"])
        self.assertEqual(per_query_metrics[0]["elapsed_ms_percentiles"], [150.0, 200.0])
        self.assertEqual(
            per_query_metrics[0]["memory_usage_measurements_readable"],
            [make_readable_bytes(4096.0), make_readable_bytes(8192.0)],
        )
        self.assertEqual(
            per_query_metrics[0]["memory_usage_percentiles_readable"],
            [make_readable_bytes(6144.0), make_readable_bytes(8192.0)],
        )
        self.assertEqual(result.metrics["total_n_rows_in_source_table"], 321)
        self.assertEqual(result.metrics["tested_table_total_size_bytes_with_indexes"], 1024.0)
        self.assertEqual(
            result.metrics["tested_table_total_size_bytes_with_indexes_readable"],
            make_readable_bytes(1024.0),
        )
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
            source_table_ddl=VALID_SOURCE_DDL,
            query_plan=QueryPlanPayload(
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
            source_table_ddl=VALID_SOURCE_DDL,
            query_plan=QueryPlanPayload(
                test_queries=[
                    {
                        "query": "SELECT count() FROM analytics.`events`",
                        "cache_mode": "warm",
                        "select_operations_count": 1,
                        "warmup_queries": [
                            "SELECT count() FROM `analytics`.events",
                        ],
                    },
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

    def test_run_source_benchmark_uses_custom_scoring_expression(self) -> None:
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
            benchmark_id="bench_source_custom_score",
            source_database="analytics",
            test_database="bench_tmp",
            source_table="events",
            source_table_ddl=VALID_SOURCE_DDL,
            query_plan=QueryPlanPayload(
                test_queries=["SELECT count() FROM `analytics`.`events`"],
            ),
            max_iterations=1,
            scoring={
                "mode": "expression",
                "expression": "safe_div(source_select_time_ms_by_percentile[100], tested_select_time_ms_by_percentile[100])",
            },
            measured_percentiles=[100],
        )

        with patch(
            "src.benchmark_runtime.implementations.clickhouse_celery.tasks._ClickHouseRuntimeClient",
            return_value=fake_client,
        ):
            result = run_source_benchmark(payload)

        self.assertEqual(result.score, 1.0)
        self.assertIsNotNone(result.score_calculation_json)
        parsed_score = json.loads(result.score_calculation_json or "{}")
        self.assertEqual(parsed_score.get("mode"), "expression")
        self.assertEqual(parsed_score.get("final_score"), 1.0)
        self.assertEqual(
            parsed_score.get("expression"),
            "safe_div(source_select_time_ms_by_percentile[100], tested_select_time_ms_by_percentile[100])",
        )

    def test_run_source_benchmark_supports_geomean_expression_with_medians_and_sizes(self) -> None:
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
            benchmark_id="bench_source_custom_score_geomean",
            source_database="analytics",
            test_database="bench_tmp",
            source_table="events",
            source_table_ddl=VALID_SOURCE_DDL,
            query_plan=QueryPlanPayload(
                test_queries=["SELECT count() FROM `analytics`.`events`"],
            ),
            max_iterations=1,
            scoring={
                "mode": "expression",
                "expression": (
                    "pow(safe_div(medians.source_insert_time_ms, medians.tested_insert_time_ms, 1.0) "
                    "* safe_div(medians.source_select_time_ms, medians.tested_select_time_ms, 1.0) "
                    "* safe_div(source_size_bytes, tested_size_bytes, 1.0), 1 / 3)"
                ),
            },
            measured_percentiles=[100],
        )

        with patch(
            "src.benchmark_runtime.implementations.clickhouse_celery.tasks._ClickHouseRuntimeClient",
            return_value=fake_client,
        ):
            result = run_source_benchmark(payload)

        self.assertEqual(result.score, 1.0)
        parsed_score = json.loads(result.score_calculation_json or "{}")
        self.assertEqual(parsed_score.get("mode"), "expression")
        self.assertEqual(parsed_score.get("final_score"), 1.0)

    def test_run_source_benchmark_stores_baseline_row_when_result_store_configured(self) -> None:
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
        fake_store = _FakeResultStore()

        payload = SourceBenchmarkTaskPayload(
            connection=self._connection_payload(),
            benchmark_run_id=1,
            benchmark_started_at=datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc),
            benchmark_id="bench_source",
            source_database="analytics",
            test_database="bench_tmp",
            source_table="events",
            source_table_ddl=VALID_SOURCE_DDL,
            result_connection=self._connection_payload(),
            result_database="benchmark_results",
            result_table="combined_benchmark_results",
            query_plan=QueryPlanPayload(
                test_queries=["SELECT count() FROM `analytics`.`events`"],
            ),
            max_iterations=1,
            measured_percentiles=[50, 100],
        )

        with patch(
            "src.benchmark_runtime.implementations.clickhouse_celery.tasks._ClickHouseRuntimeClient",
            return_value=fake_client,
        ), patch(
            "src.benchmark_runtime.implementations.clickhouse_celery.tasks.ClickHouseBenchmarkResultStore",
            return_value=fake_store,
        ):
            result = run_source_benchmark(payload)

        self.assertTrue(fake_store.closed)
        self.assertEqual(len(fake_store.store_calls), 1)
        store_call = fake_store.store_calls[0]
        self.assertEqual(store_call["variant_mode"], "source_baseline")
        self.assertEqual(store_call["source_database"], "analytics")
        self.assertEqual(store_call["source_table"], "events")
        self.assertTrue(store_call["variant_table"].startswith("events__source_baseline__"))
        stored_result = store_call["result"]
        self.assertTrue(stored_result.is_source_table_copy)
        self.assertEqual(stored_result.variant_mode, "source_baseline")
        self.assertEqual(stored_result.score, result.score)
        self.assertEqual(stored_result.total_n_rows_in_source_table, 321)
        self.assertEqual(stored_result.total_n_rows_in_tested_table, 321)
        baseline_tested_cols_sizes = json.loads(
            stored_result.tested_table_consumed_compressed_size_bytes_by_each_column or "{}"
        )
        baseline_source_cols_sizes = json.loads(
            stored_result.source_table_consumed_compressed_size_bytes_by_each_column or "{}"
        )
        self.assertEqual(
            baseline_tested_cols_sizes.get("user_id", {}).get("size_compressed_bytes"),
            400,
        )
        self.assertEqual(
            baseline_source_cols_sizes.get("user_id", {}).get("size_compressed_bytes"),
            400,
        )
        self.assertIn(
            "\n",
            stored_result.tested_table_consumed_compressed_size_bytes_by_each_column or "",
        )
        self.assertIn(
            '"size_compressed_bytes": 400',
            stored_result.source_table_consumed_compressed_size_bytes_by_each_column or "",
        )

    def test_run_source_benchmark_stores_baseline_rows_count_with_insert_limit(self) -> None:
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
            column_sizes_map={
                ("analytics", "events"): {},
                ("bench_tmp", "events__source_baseline__synthetic"): {},
            },
            total_size_map={
                ("analytics", "events"): 1_024.0,
                ("bench_tmp", "events__source_baseline__synthetic"): 1_024.0,
            },
        )
        fake_store = _FakeResultStore()

        payload = SourceBenchmarkTaskPayload(
            connection=self._connection_payload(),
            benchmark_run_id=1,
            benchmark_started_at=datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc),
            benchmark_id="bench_source",
            source_database="analytics",
            test_database="bench_tmp",
            source_table="events",
            source_table_ddl=VALID_SOURCE_DDL,
            result_connection=self._connection_payload(),
            result_database="benchmark_results",
            result_table="combined_benchmark_results",
            query_plan=QueryPlanPayload(
                test_queries=["SELECT count() FROM `analytics`.`events`"],
            ),
            max_iterations=1,
            insert_rows_limit=100,
            measured_percentiles=[100],
        )

        with patch(
            "src.benchmark_runtime.implementations.clickhouse_celery.tasks._ClickHouseRuntimeClient",
            return_value=fake_client,
        ), patch(
            "src.benchmark_runtime.implementations.clickhouse_celery.tasks.ClickHouseBenchmarkResultStore",
            return_value=fake_store,
        ), patch(
            "src.benchmark_runtime.implementations.clickhouse_celery.tasks.uuid.uuid4",
            return_value=SimpleNamespace(hex="synthetic"),
        ):
            run_source_benchmark(payload)

        self.assertEqual(len(fake_store.store_calls), 1)
        stored_result = fake_store.store_calls[0]["result"]
        self.assertEqual(stored_result.insert_test_n_rows, 100)
        self.assertEqual(stored_result.total_n_rows_in_source_table, 321)
        self.assertEqual(stored_result.total_n_rows_in_tested_table, 100)

    def test_run_variant_benchmark_calculates_metrics_score_and_stores_result(self) -> None:
        fake_client = _FakeRuntimeClient(
            query_metrics_sequence=[
                {
                    "elapsed_ns": 100_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 1000.0,
                    "written_bytes": 10_000.0,
                    "memory_usage": 3072.0,
                },
                {
                    "elapsed_ns": 200_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 1000.0,
                    "written_bytes": 10_000.0,
                    "memory_usage": 5120.0,
                },
                {
                    "elapsed_ns": 50_000_000.0,
                    "read_rows": 500.0,
                    "read_bytes": 5_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                    "memory_usage": 4096.0,
                },
                {
                    "elapsed_ns": 100_000_000.0,
                    "read_rows": 500.0,
                    "read_bytes": 5_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                    "memory_usage": 6144.0,
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
            "source_table_insert_memory_usage_measurements": [2048.0],
            "source_table_insert_memory_usage_measurements_readable": [
                make_readable_bytes(2048.0)
            ],
            "source_table_insert_memory_usage_measurements_percentiles": [2048.0],
            "source_table_insert_memory_usage_measurements_percentiles_readable": [
                make_readable_bytes(2048.0)
            ],
            "source_table_select_rows_per_second_measurements": [1200.0],
            "source_table_select_bytes_per_second_measurements": [12_000.0],
            "source_table_select_memory_usage_measurements": [1024.0],
            "source_table_select_memory_usage_measurements_readable": [
                make_readable_bytes(1024.0)
            ],
            "source_table_select_memory_usage_measurements_percentiles": [1024.0],
            "source_table_select_memory_usage_measurements_percentiles_readable": [
                make_readable_bytes(1024.0)
            ],
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
            variant_params={
                "index_choices": {
                    "user_id": {
                        "name": "idx_user_id",
                        "expr": "user_id",
                        "index_type": "set(512)",
                        "granularity": "2",
                    }
                }
            },
            variant_ddl=VALID_VARIANT_DDL,
            max_iterations=2,
            insert_rows_limit=1000,
            query_plan=QueryPlanPayload(
                test_queries=["SELECT count() FROM `bench_tmp`.`events__bench__bench_var__0001`"],
            ),
            source_benchmark={
                "source_table_ddl": VALID_SOURCE_DDL,
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

        expected_score = ((350.0 / 150.0) * (175.0 / 75.0) * (4000.0 / 2050.0)) ** (1.0 / 3.0)
        self.assertAlmostEqual(result.score or 0.0, expected_score)
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
        self.assertEqual(
            result.tested_table_insert_memory_usage_measurements_readable,
            [make_readable_bytes(3072.0), make_readable_bytes(5120.0)],
        )
        self.assertEqual(
            result.tested_table_insert_memory_usage_measurements_percentiles_readable,
            [make_readable_bytes(4096.0), make_readable_bytes(5120.0)],
        )
        self.assertEqual(
            result.source_table_insert_memory_usage_measurements_readable,
            [make_readable_bytes(2048.0)],
        )
        self.assertEqual(
            result.source_table_insert_memory_usage_measurements_percentiles_readable,
            [make_readable_bytes(2048.0)],
        )
        self.assertEqual(
            result.tested_table_select_memory_usage_measurements_readable,
            [make_readable_bytes(4096.0), make_readable_bytes(6144.0)],
        )
        self.assertEqual(
            result.tested_table_select_memory_usage_measurements_percentiles_readable,
            [make_readable_bytes(5120.0), make_readable_bytes(6144.0)],
        )
        self.assertEqual(
            result.source_table_select_memory_usage_measurements_readable,
            [make_readable_bytes(1024.0)],
        )
        self.assertEqual(
            result.source_table_select_memory_usage_measurements_percentiles_readable,
            [make_readable_bytes(1024.0)],
        )
        tested_select_per_query = json.loads(result.tested_table_select_metrics_by_query_json or "[]")
        source_select_per_query = json.loads(result.source_table_select_metrics_by_query_json or "[]")
        select_speedup_by_query = json.loads(
            result.tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json or "[]"
        )
        self.assertEqual(len(tested_select_per_query), 1)
        self.assertEqual(len(source_select_per_query), 1)
        self.assertEqual(len(select_speedup_by_query), 1)
        self.assertIn("memory_usage_measurements_readable", tested_select_per_query[0])
        self.assertIn("memory_usage_percentiles_readable", tested_select_per_query[0])
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
        self.assertAlmostEqual(stored_result.score or 0.0, expected_score)
        self.assertIsNone(result.index_params)
        self.assertIsNone(stored_result.index_params)
        self.assertIn("index_choices", result.variant_params)
        self.assertIn("user_id", result.variant_params.get("index_choices", {}))
        self.assertEqual(result.tested_table_total_size_bytes_with_indexes, 2050.0)
        self.assertEqual(
            result.tested_table_total_size_bytes_with_indexes_readable,
            make_readable_bytes(2050.0),
        )

        parsed_index_pct = json.loads(result.tested_table_indexes_sizes_percent_from_col_size or "{}")
        self.assertEqual(parsed_index_pct.get("user_id"), 25.0)
        # Legacy-совместимость: поле хранится как pretty JSON (indent=2).
        self.assertIn("\n", result.tested_table_indexes_sizes_percent_from_col_size or "")
        self.assertIn('"user_id": 25.0', result.tested_table_indexes_sizes_percent_from_col_size or "")
        parsed_indexes_sizes = json.loads(result.tested_table_indexes_sizes or "{}")
        self.assertEqual(parsed_indexes_sizes.get("user_id", {}).get("size_compressed_bytes"), 50)
        # Legacy-совместимость: tested_table_indexes_sizes тоже хранится как pretty JSON (indent=2).
        self.assertIn("\n", result.tested_table_indexes_sizes or "")
        self.assertIn('"size_compressed_bytes": 50', result.tested_table_indexes_sizes or "")
        parsed_cols_sizes = json.loads(result.tested_table_cols_sizes or "{}")
        self.assertEqual(parsed_cols_sizes.get("user_id", {}).get("size_compressed_bytes"), 200)
        # Legacy-совместимость: tested_table_cols_sizes тоже хранится как pretty JSON (indent=2).
        self.assertIn("\n", result.tested_table_cols_sizes or "")
        self.assertIn('"datatype": "UInt32"', result.tested_table_cols_sizes or "")
        parsed_tested_compressed_by_col = json.loads(
            result.tested_table_consumed_compressed_size_bytes_by_each_column or "{}"
        )
        parsed_source_compressed_by_col = json.loads(
            result.source_table_consumed_compressed_size_bytes_by_each_column or "{}"
        )
        self.assertEqual(
            parsed_tested_compressed_by_col.get("user_id", {}).get("size_compressed_bytes"),
            200,
        )
        self.assertEqual(
            parsed_source_compressed_by_col.get("user_id", {}).get("size_compressed_bytes"),
            400,
        )
        self.assertIn(
            "\n",
            result.tested_table_consumed_compressed_size_bytes_by_each_column or "",
        )
        self.assertIn(
            '"size_compressed_bytes": 400',
            result.source_table_consumed_compressed_size_bytes_by_each_column or "",
        )
        parsed_compression_by_col = json.loads(
            result.tested_table_compression_by_each_column_coef or "{}"
        )
        self.assertEqual(parsed_compression_by_col.get("user_id"), 2.0)
        self.assertEqual(parsed_compression_by_col.get("event_time"), 2.0)
        # Legacy-совместимость: compression_by_each_column_coef хранится как pretty JSON (indent=2).
        self.assertIn("\n", result.tested_table_compression_by_each_column_coef or "")
        self.assertIn(
            '"user_id": 2.0',
            result.tested_table_compression_by_each_column_coef or "",
        )

        # Один drop перед созданием и один drop в finally.
        self.assertEqual(fake_client.drop_calls.count(("bench_tmp", "events__bench__bench_var__0001")), 2)
        self.assertTrue(fake_client.closed)

    def test_run_variant_benchmark_uses_custom_scoring_expression_by_index(self) -> None:
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
            column_sizes_map={("bench_tmp", "events__bench__bench_var__0001"): {}},
            total_size_map={("bench_tmp", "events__bench__bench_var__0001"): 2000.0},
        )
        fake_store = _FakeResultStore()
        source_metrics = {
            "total_n_rows_in_source_table": 300,
            "source_table_insert_time_ms_measurements_percentiles": [300.0, 400.0],
            "source_table_select_time_ms_measurements_percentiles": [150.0, 200.0],
            "source_table_consumed_compressed_size_bytes_overall": 4000.0,
            "source_table_insert_rows_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_insert_bytes_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_insert_memory_usage_measurements_percentiles": [1.0, 1.0],
            "source_table_select_rows_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_select_bytes_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_select_memory_usage_measurements_percentiles": [1.0, 1.0],
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
            scoring={
                "mode": "expression",
                "expression": (
                    "safe_div(source.select.time_ms_percentiles[1], tested.select.time_ms_percentiles[1]) + "
                    "safe_div(source.insert.time_ms_percentiles[1], tested.insert.time_ms_percentiles[1])"
                ),
            },
            variant_params={},
            variant_ddl=VALID_VARIANT_DDL,
            max_iterations=2,
            insert_rows_limit=1000,
            query_plan=QueryPlanPayload(
                test_queries=["SELECT count() FROM `bench_tmp`.`events__bench__bench_var__0001`"],
            ),
            source_benchmark={
                "source_table_ddl": VALID_SOURCE_DDL,
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

        # 200/100 + 400/200 = 2 + 2 = 4
        self.assertEqual(result.score, 4.0)
        self.assertIsNotNone(result.score_calculation_json)
        parsed_score = json.loads(result.score_calculation_json or "{}")
        self.assertEqual(parsed_score.get("mode"), "expression")
        self.assertEqual(parsed_score.get("final_score"), 4.0)

    def test_run_variant_benchmark_uses_custom_scoring_expression_by_percentile(self) -> None:
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
            column_sizes_map={("bench_tmp", "events__bench__bench_var__0001"): {}},
            total_size_map={("bench_tmp", "events__bench__bench_var__0001"): 2000.0},
        )
        fake_store = _FakeResultStore()
        source_metrics = {
            "total_n_rows_in_source_table": 300,
            "source_table_insert_time_ms_measurements_percentiles": [300.0, 400.0],
            "source_table_select_time_ms_measurements_percentiles": [150.0, 200.0],
            "source_table_consumed_compressed_size_bytes_overall": 4000.0,
            "source_table_insert_rows_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_insert_bytes_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_insert_memory_usage_measurements_percentiles": [1.0, 1.0],
            "source_table_select_rows_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_select_bytes_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_select_memory_usage_measurements_percentiles": [1.0, 1.0],
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
            scoring={
                "mode": "expression",
                "expression": (
                    "safe_div(source_select_time_ms_by_percentile[100], tested_select_time_ms_by_percentile['p100'])"
                ),
            },
            variant_params={},
            variant_ddl=VALID_VARIANT_DDL,
            max_iterations=2,
            insert_rows_limit=1000,
            query_plan=QueryPlanPayload(
                test_queries=["SELECT count() FROM `bench_tmp`.`events__bench__bench_var__0001`"],
            ),
            source_benchmark={
                "source_table_ddl": VALID_SOURCE_DDL,
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

        self.assertEqual(result.score, 2.0)

    def test_run_variant_benchmark_uses_custom_scoring_expression_per_query_by_id(self) -> None:
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
            column_sizes_map={("bench_tmp", "events__bench__bench_var__0001"): {}},
            total_size_map={("bench_tmp", "events__bench__bench_var__0001"): 2000.0},
        )
        fake_store = _FakeResultStore()
        source_metrics = {
            "total_n_rows_in_source_table": 300,
            "source_table_insert_time_ms_measurements_percentiles": [300.0, 400.0],
            "source_table_select_time_ms_measurements_percentiles": [150.0, 200.0],
            "source_table_consumed_compressed_size_bytes_overall": 4000.0,
            "source_table_insert_rows_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_insert_bytes_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_insert_memory_usage_measurements_percentiles": [1.0, 1.0],
            "source_table_select_rows_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_select_bytes_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_select_memory_usage_measurements_percentiles": [1.0, 1.0],
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
            scoring={
                "mode": "expression",
                "expression": (
                    "safe_div(tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json['q_main']."
                    "elapsed_ms_percentiles_speed_up_coefs[1], 1)"
                ),
            },
            variant_params={},
            variant_ddl=VALID_VARIANT_DDL,
            max_iterations=2,
            insert_rows_limit=1000,
            query_plan=QueryPlanPayload(
                test_queries=[
                    QueryPayload(
                        query_id="q_main",
                        query="SELECT count() FROM `bench_tmp`.`events__bench__bench_var__0001`",
                    )
                ],
            ),
            source_benchmark={
                "source_table_ddl": VALID_SOURCE_DDL,
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

        self.assertEqual(result.score, 2.0)

    def test_run_variant_benchmark_custom_scoring_error_uses_on_error_score(self) -> None:
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
            column_sizes_map={("bench_tmp", "events__bench__bench_var__0001"): {}},
            total_size_map={("bench_tmp", "events__bench__bench_var__0001"): 2000.0},
        )
        fake_store = _FakeResultStore()
        source_metrics = {
            "total_n_rows_in_source_table": 300,
            "source_table_insert_time_ms_measurements_percentiles": [300.0, 400.0],
            "source_table_select_time_ms_measurements_percentiles": [150.0, 200.0],
            "source_table_consumed_compressed_size_bytes_overall": 4000.0,
            "source_table_insert_rows_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_insert_bytes_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_insert_memory_usage_measurements_percentiles": [1.0, 1.0],
            "source_table_select_rows_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_select_bytes_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_select_memory_usage_measurements_percentiles": [1.0, 1.0],
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
            scoring={
                "mode": "expression",
                "expression": "source.select.time_ms_percentiles[999]",
                "on_error_score": -7.5,
            },
            variant_params={},
            variant_ddl=VALID_VARIANT_DDL,
            max_iterations=2,
            insert_rows_limit=1000,
            query_plan=QueryPlanPayload(
                test_queries=["SELECT count() FROM `bench_tmp`.`events__bench__bench_var__0001`"],
            ),
            source_benchmark={
                "source_table_ddl": VALID_SOURCE_DDL,
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

        self.assertEqual(result.score, -7.5)

    def test_run_variant_benchmark_custom_scoring_error_without_on_error_returns_none(
        self,
    ) -> None:
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
            column_sizes_map={("bench_tmp", "events__bench__bench_var__0001"): {}},
            total_size_map={("bench_tmp", "events__bench__bench_var__0001"): 2000.0},
        )
        fake_store = _FakeResultStore()
        source_metrics = {
            "total_n_rows_in_source_table": 300,
            "source_table_insert_time_ms_measurements_percentiles": [300.0, 400.0],
            "source_table_select_time_ms_measurements_percentiles": [150.0, 200.0],
            "source_table_consumed_compressed_size_bytes_overall": 4000.0,
            "source_table_insert_rows_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_insert_bytes_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_insert_memory_usage_measurements_percentiles": [1.0, 1.0],
            "source_table_select_rows_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_select_bytes_per_second_measurements_percentiles": [1.0, 1.0],
            "source_table_select_memory_usage_measurements_percentiles": [1.0, 1.0],
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
            scoring={
                "mode": "expression",
                "expression": "source.select.time_ms_percentiles[999]",
            },
            variant_params={},
            variant_ddl=VALID_VARIANT_DDL,
            max_iterations=2,
            insert_rows_limit=1000,
            query_plan=QueryPlanPayload(
                test_queries=["SELECT count() FROM `bench_tmp`.`events__bench__bench_var__0001`"],
            ),
            source_benchmark={
                "source_table_ddl": VALID_SOURCE_DDL,
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

        self.assertIsNone(result.score)

    def test_run_source_benchmark_custom_scoring_error_without_on_error_returns_none(
        self,
    ) -> None:
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
            benchmark_id="bench_source_custom_score",
            source_database="analytics",
            test_database="bench_tmp",
            source_table="events",
            source_table_ddl=VALID_SOURCE_DDL,
            query_plan=QueryPlanPayload(
                test_queries=["SELECT count() FROM `analytics`.`events`"],
            ),
            max_iterations=1,
            scoring={
                "mode": "expression",
                "expression": "source.select.time_ms_percentiles[999]",
            },
            measured_percentiles=[100],
        )

        with patch(
            "src.benchmark_runtime.implementations.clickhouse_celery.tasks._ClickHouseRuntimeClient",
            return_value=fake_client,
        ):
            result = run_source_benchmark(payload)

        self.assertIsNone(result.score)

    def test_run_source_benchmark_skips_when_source_table_is_empty(self) -> None:
        fake_client = _FakeRuntimeClient(
            count_rows_map={("analytics", "events"): 0},
        )

        payload = SourceBenchmarkTaskPayload(
            connection=self._connection_payload(),
            benchmark_run_id=1,
            benchmark_started_at=datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc),
            benchmark_id="bench_source_empty",
            source_database="analytics",
            test_database="bench_tmp",
            source_table="events",
            source_table_ddl=VALID_SOURCE_DDL,
            query_plan=QueryPlanPayload(
                test_queries=["SELECT count() FROM `analytics`.`events`"],
            ),
            max_iterations=2,
            measured_percentiles=[50, 100],
        )

        with patch(
            "src.benchmark_runtime.implementations.clickhouse_celery.tasks._ClickHouseRuntimeClient",
            return_value=fake_client,
        ), self.assertLogs(
            "src.benchmark_runtime.implementations.clickhouse_celery.tasks",
            level="WARNING",
        ) as captured_logs:
            result = run_source_benchmark(payload)

        self.assertIsNone(result.score)
        self.assertEqual(result.metrics.get("status"), "skipped")
        self.assertEqual(result.metrics.get("skip_reason"), "source_table_empty")
        self.assertEqual(result.metrics.get("total_n_rows_in_source_table"), 0)
        self.assertEqual(len(fake_client.insert_with_metrics_calls), 0)
        self.assertEqual(len(fake_client.select_with_metrics_calls), 0)
        self.assertTrue(
            any("содержит 0 строк" in line for line in captured_logs.output)
        )
        self.assertTrue(fake_client.closed)

    def test_run_variant_benchmark_closes_resources_on_failure(self) -> None:
        variant_ddl = VALID_FAILED_VARIANT_DDL
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
            variant_table="events__bench__bench_var_fail__9999",
            variant_mode="combined",
            variant_params={},
            variant_ddl=variant_ddl,
            max_iterations=1,
            query_plan=QueryPlanPayload(test_queries=[]),
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

        self.assertGreaterEqual(
            fake_client.drop_calls.count(("bench_tmp", "events__bench__bench_var_fail__9999")),
            1,
        )
        self.assertEqual(len(fake_store.store_calls), 0)
        self.assertTrue(fake_client.closed)
        self.assertTrue(fake_store.closed)

    def test_runtime_client_drop_table_rejects_non_benchmark_table(self) -> None:
        client = _ClickHouseRuntimeClient.__new__(_ClickHouseRuntimeClient)
        client.execute = lambda query, params=None: []  # type: ignore[method-assign]

        with self.assertRaisesRegex(ValueError, "только для benchmark-таблиц"):
            client.drop_table_if_exists(
                "bench_tmp",
                "events",
                allowed_database="bench_tmp",
            )

    def test_runtime_client_drop_table_rejects_non_test_database(self) -> None:
        client = _ClickHouseRuntimeClient.__new__(_ClickHouseRuntimeClient)
        client.execute = lambda query, params=None: []  # type: ignore[method-assign]

        with self.assertRaisesRegex(ValueError, "только в тестовой БД"):
            client.drop_table_if_exists(
                "analytics",
                "events__bench__bench_var__0001",
                allowed_database="bench_tmp",
            )

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
        self.assertEqual(error_metrics["memory_usage"], -1.0)

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

    def test_insert_fallback_uses_command_summary_metrics(self) -> None:
        class _DummyClient:
            def command(self, query: str):
                del query
                return SimpleNamespace(
                    summary={
                        "elapsed_ns": 123_000_000.0,
                        "read_rows": 1000.0,
                        "read_bytes": 10_000.0,
                        "written_rows": 1000.0,
                        "written_bytes": 10_000.0,
                    }
                )

        client = _ClickHouseRuntimeClient.__new__(_ClickHouseRuntimeClient)
        client._client = _DummyClient()
        client._stream_client = None
        client._stream_client_checked = True
        client._stream_connection = SimpleNamespace(
            host="localhost",
            port=9000,
            login="default",
        )

        metrics = client.insert_from_source_with_metrics(
            source_database="analytics",
            source_table="events",
            target_database="bench_tmp",
            target_table="events_variant",
            n_rows=None,
            offset=0,
            strictly_adhere_n_rows=False,
            query_tag="insert-summary-fallback",
        )

        self.assertEqual(metrics["elapsed_ns"], 123_000_000.0)
        self.assertEqual(metrics["read_rows"], 1000.0)
        self.assertEqual(metrics["written_rows"], 1000.0)

    def test_stream_insert_uses_dedicated_insert_client(self) -> None:
        class _DummySourceStream:
            headers = None

            def close(self) -> None:
                return None

        class _DummyReadClient:
            def __init__(self) -> None:
                self.raw_stream_calls: List[tuple[str, str]] = []

            def raw_stream(self, query: str, fmt: str = "Native"):
                self.raw_stream_calls.append((query, fmt))
                return _DummySourceStream()

        class _DummyWriteClient:
            def __init__(self) -> None:
                self.raw_insert_calls: List[Dict[str, Any]] = []

            def raw_insert(self, *, table: str, insert_block: Any, fmt: str = "Native"):
                self.raw_insert_calls.append(
                    {
                        "table": table,
                        "insert_block": insert_block,
                        "fmt": fmt,
                    }
                )
                return SimpleNamespace(
                    summary={
                        "elapsed_ns": 111_000_000.0,
                        "read_rows": 777.0,
                        "read_bytes": 7_770.0,
                        "written_rows": 777.0,
                        "written_bytes": 7_770.0,
                    }
                )

        client = _ClickHouseRuntimeClient.__new__(_ClickHouseRuntimeClient)
        client._stream_connection = SimpleNamespace(
            host="localhost",
            port=9000,
            login="default",
            password="secret",
        )
        read_client = _DummyReadClient()
        write_client = _DummyWriteClient()

        with patch.object(client, "_get_stream_client", return_value=read_client), patch.object(
            client, "_get_stream_insert_client", return_value=write_client
        ), patch.object(client, "_acquire_stream_slot", return_value=True), patch.object(
            client, "_release_stream_slot", return_value=None
        ):
            metrics = client.insert_from_source_with_metrics(
                source_database="analytics",
                source_table="events",
                target_database="bench_tmp",
                target_table="events_variant",
                n_rows=None,
                offset=0,
                strictly_adhere_n_rows=False,
                query_tag="insert-dedicated-client",
            )

        self.assertEqual(len(read_client.raw_stream_calls), 1)
        self.assertEqual(len(write_client.raw_insert_calls), 1)
        self.assertEqual(
            write_client.raw_insert_calls[0]["table"],
            "bench_tmp.events_variant",
        )
        self.assertEqual(metrics["elapsed_ns"], 111_000_000.0)
        self.assertEqual(metrics["read_rows"], 777.0)
        self.assertEqual(metrics["written_rows"], 777.0)

    def test_select_metrics_use_summary_stream_first(self) -> None:
        class _DummyStreamClient:
            def command(self, query: str):
                del query
                return SimpleNamespace(
                    summary={
                        "elapsed_ns": 50_000_000.0,
                        "read_rows": 500.0,
                        "read_bytes": 5_000.0,
                        "written_rows": 0.0,
                        "written_bytes": 0.0,
                    }
                )

        class _DummyClient:
            def query(self, query: str):
                raise AssertionError(f"client.query не должен вызываться: {query}")

        client = _ClickHouseRuntimeClient.__new__(_ClickHouseRuntimeClient)
        client._client = _DummyClient()
        client._stream_client = _DummyStreamClient()
        client._stream_client_checked = True
        client._stream_connection = SimpleNamespace(
            host="localhost",
            port=9000,
            login="default",
        )

        metrics = client.execute_select_with_metrics(
            "SELECT count() FROM `analytics`.`events`",
            query_tag="select-summary",
        )
        self.assertEqual(metrics["elapsed_ns"], 50_000_000.0)
        self.assertEqual(metrics["read_rows"], 500.0)

    def test_stream_empty_check_returns_true_on_summary_parse_error(self) -> None:
        class _BrokenHeaders:
            def get(self, key: str):
                del key
                return "{broken-json"

        broken_stream = SimpleNamespace(headers=_BrokenHeaders())
        self.assertTrue(_ClickHouseRuntimeClient._is_stream_empty(broken_stream))

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

    def test_measure_insert_filters_zero_rows_per_second_from_measurements(self) -> None:
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
                    "elapsed_ns": 120_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 12_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 12_000.0,
                },
            ],
            retry_policy=(0, 0.0, 0.0),
        )

        stats = _measure_insert(
            fake_client,
            source_database="analytics",
            source_table="events",
            target_database="bench_tmp",
            target_table="events_variant",
            n_rows=1000,
            n_measurements=2,
        )

        self.assertEqual(stats["elapsed_ns"], [100_000_000.0, 120_000_000.0])
        self.assertEqual(stats["rows_per_second"], [10_000.0])
        self.assertEqual(stats["written_rows"], [1000.0])

    def test_measure_select_queries_filters_zero_rows_per_second_from_measurements(self) -> None:
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
                    "elapsed_ns": 100_000_000.0,
                    "read_rows": 0.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                },
            ],
            retry_policy=(0, 0.0, 0.0),
        )

        stats = _measure_select_queries(
            fake_client,
            test_queries=["SELECT count() FROM t1"],
            n_measurements=2,
        )

        self.assertEqual(stats["elapsed_ns"], [100_000_000.0, 100_000_000.0])
        self.assertEqual(stats["rows_per_second"], [10_000.0])
        self.assertEqual(
            stats["per_query"][0]["rows_per_second_measurements"],
            [10_000.0],
        )

    def test_measure_select_queries_cold_mode_drops_caches_before_each_measurement(self) -> None:
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
                    "elapsed_ns": 120_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                },
            ],
            retry_policy=(0, 0.0, 0.0),
        )

        stats = _measure_select_queries(
            fake_client,
            test_queries=[
                QueryPayload(
                    query="SELECT count() FROM t1",
                    cache_mode="cold",
                    select_operations_count=2,
                )
            ],
            n_measurements=5,
        )

        self.assertEqual(len(fake_client.select_with_metrics_calls), 2)
        self.assertEqual(
            fake_client.execute_calls.count("SYSTEM DROP MARK CACHE"),
            2,
        )
        self.assertEqual(
            fake_client.execute_calls.count("SYSTEM DROP UNCOMPRESSED CACHE"),
            2,
        )
        self.assertEqual(stats["per_query"][0]["select_operations_count"], 2)
        self.assertEqual(stats["per_query"][0]["cache_mode"], "cold")

    def test_measure_select_queries_warm_mode_runs_query_warmups_once(self) -> None:
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
                    "elapsed_ns": 110_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                },
                {
                    "elapsed_ns": 120_000_000.0,
                    "read_rows": 1000.0,
                    "read_bytes": 10_000.0,
                    "written_rows": 0.0,
                    "written_bytes": 0.0,
                },
            ],
            retry_policy=(0, 0.0, 0.0),
        )

        stats = _measure_select_queries(
            fake_client,
            test_queries=[
                QueryPayload(
                    query="SELECT count() FROM t1",
                    cache_mode="warm",
                    select_operations_count=3,
                    warmup_queries=["SELECT 1"],
                )
            ],
            n_measurements=1,
        )

        self.assertEqual(fake_client.execute_calls.count("SELECT 1"), 1)
        self.assertEqual(len(fake_client.select_with_metrics_calls), 3)
        self.assertEqual(stats["per_query"][0]["select_operations_count"], 3)
        self.assertEqual(stats["per_query"][0]["cache_mode"], "warm")
        self.assertEqual(stats["per_query"][0]["warmup_queries"], ["SELECT 1"])

    def test_query_plan_rejects_dangerous_query_level_warmup_sql(self) -> None:
        with self.assertRaisesRegex(ValueError, "потенциально опасный SQL"):
            QueryPlanPayload(
                test_queries=[
                    {
                        "query": "SELECT 1",
                        "warmup_queries": ["DROP TABLE analytics.events"],
                    }
                ],
            )

    def test_query_plan_rejects_non_read_only_query_level_warmup_sql(self) -> None:
        with self.assertRaisesRegex(ValueError, "разрешены только read-only SQL-запросы"):
            QueryPlanPayload(
                test_queries=[
                    {
                        "query": "SELECT 1",
                        "warmup_queries": ["SYSTEM FLUSH LOGS"],
                    }
                ],
            )

    def test_query_plan_rejects_query_level_warmup_for_cold_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "cache_mode=cold"):
            QueryPlanPayload(
                test_queries=[
                    {
                        "query": "SELECT 1",
                        "cache_mode": "cold",
                        "select_operations_count": 1,
                        "warmup_queries": ["SELECT 1"],
                    }
                ],
            )

    def test_runtime_client_rejects_dangerous_user_query(self) -> None:
        client = _ClickHouseRuntimeClient.__new__(_ClickHouseRuntimeClient)
        with self.assertRaisesRegex(ValueError, "опасные input-параметры"):
            client.execute_user_read_only_query("DROP TABLE analytics.events")

    def test_runtime_client_rejects_dangerous_select_query_before_execution(self) -> None:
        client = _ClickHouseRuntimeClient.__new__(_ClickHouseRuntimeClient)
        with self.assertRaisesRegex(ValueError, "опасные input-параметры"):
            client.execute_select_with_metrics(
                "DELETE FROM analytics.events",
                query_tag="select-test",
            )

    def test_build_index_params_json_uses_variant_table_key_and_pretty_json(self) -> None:
        payload = {
            "user_id": {"index_type": "set(512)", "granularity": 2},
            "country": {"index_type": "minmax", "granularity": 4},
        }
        index_params = build_index_params_json(
            "events__bench__bench_var__0001",
            payload,
        )
        self.assertIsNotNone(index_params)
        parsed = json.loads(index_params or "{}")
        self.assertEqual(
            parsed.get("events__bench__bench_var__0001"),
            ["set(512) GRANULARITY 2", "minmax GRANULARITY 4"],
        )
        self.assertIn("\n", index_params or "")

    def test_variant_task_skips_invalid_payload_without_crash(self) -> None:
        variant_task = getattr(celery_tasks_module, "variant_benchmark_task", None)
        if variant_task is None:
            self.skipTest("Celery app/task недоступны в текущем окружении")

        result = variant_task({"benchmark_id": "bench_invalid_payload"})

        self.assertEqual(result["status"], "skipped_invalid_variant_payload")
        self.assertEqual(result.get("benchmark_id"), "bench_invalid_payload")

    def test_variant_task_skips_failed_variant_without_crash(self) -> None:
        variant_task = getattr(celery_tasks_module, "variant_benchmark_task", None)
        if variant_task is None:
            self.skipTest("Celery app/task недоступны в текущем окружении")

        payload = self._variant_task_payload_dict()
        with patch(
            "src.benchmark_runtime.implementations.clickhouse_celery.tasks.run_variant_benchmark",
            side_effect=RuntimeError("synthetic variant failure"),
        ):
            result = variant_task(payload)

        self.assertEqual(result["status"], "skipped_invalid_variant")
        self.assertEqual(result["benchmark_run_id"], 101)
        self.assertEqual(result["benchmark_id"], "bench_variant_task")
        self.assertEqual(result["variant_table"], "events__bench__bench_var__0001")
        self.assertIn("synthetic variant failure", result["error"])


if __name__ == "__main__":
    unittest.main()
