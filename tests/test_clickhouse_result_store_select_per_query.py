import unittest
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.benchmark_runtime.implementations.clickhouse_celery.result_store import (
    ClickHouseBenchmarkResultStore,
    ClickHouseConnectionParams,
)
from src.benchmark_runtime.types import BenchmarkVariantResult


class _CapturingClient:
    def __init__(self) -> None:
        self.insert_calls: List[Dict[str, Any]] = []

    def insert(self, table: str, data: List[tuple], column_names: List[str]) -> None:
        self.insert_calls.append(
            {
                "table": table,
                "data": data,
                "column_names": column_names,
            }
        )

    def close(self) -> None:
        return None


class _CapturingStore(ClickHouseBenchmarkResultStore):
    def __init__(self) -> None:
        self.executed_queries: List[str] = []
        self.capturing_client = _CapturingClient()
        super().__init__(
            connection=ClickHouseConnectionParams(
                host="localhost",
                port=9000,
                login="default",
                password="secret",
            ),
            database="bench",
            table="results",
            create_table_if_missing=True,
        )

    def _build_client(self):
        return self.capturing_client

    def _execute(self, query: str, params: Optional[Any] = None):
        del params
        self.executed_queries.append(query)
        return []


class ClickHouseResultStorePerQuerySelectTests(unittest.TestCase):
    def test_store_contains_per_query_select_columns_and_values(self) -> None:
        store = _CapturingStore()

        result = BenchmarkVariantResult(
            benchmark_run_id=10,
            benchmark_started_at=datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc),
            benchmark_id="bench_a",
            source_database="analytics",
            source_table="events",
            variant_table="events__bench__bench_a__0001",
            variant_mode="types",
            tested_table_ddl="CREATE TABLE bench.events (...) ENGINE=MergeTree ORDER BY user_id",
            tested_table_select_metrics_by_query_json=(
                '[{"query_index":0,"query":"select count() from `bench`.`events`",'
                '"cache_mode":"warm","select_operations_count":2,'
                '"elapsed_ms_measurements":[10,20],'
                '"elapsed_ms_percentiles":[15,20],'
                '"rows_per_second_measurements":[100,120],'
                '"rows_per_second_percentiles":[110,120],'
                '"bytes_per_second_measurements":[1000,1200],'
                '"bytes_per_second_percentiles":[1100,1200],'
                '"memory_usage_measurements":[1024,2048],'
                '"memory_usage_percentiles":[1536,2048],'
                '"warmup_queries":["select 1"]}]'
            ),
            source_table_select_metrics_by_query_json=(
                '[{"query_index":0,"query":"select count() from `analytics`.`events`",'
                '"elapsed_ms_measurements":[20,40],'
                '"elapsed_ms_percentiles":[30,40],'
                '"rows_per_second_measurements":[50,60],'
                '"rows_per_second_percentiles":[55,60],'
                '"bytes_per_second_measurements":[500,600],'
                '"bytes_per_second_percentiles":[550,600],'
                '"memory_usage_measurements":[512,1024],'
                '"memory_usage_percentiles":[768,1024]}]'
            ),
            tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json=(
                '[{"query_index":0,"elapsed_ms_percentiles_speed_up_coefs":[2.0,2.0]}]'
            ),
            tested_table_consumed_compressed_size_bytes_with_indexes=1234.0,
            tested_table_consumed_compressed_size_bytes_with_indexes_readable="1.21 KiB",
            score_calculation_json='{"mode":"expression","final_score":1.0}',
            score=1.0,
        )

        store.store_worker_result(
            benchmark_run_id=10,
            benchmark_started_at=datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc),
            benchmark_id="bench_a",
            source_database="analytics",
            source_table="events",
            variant_table="events__bench__bench_a__0001",
            variant_mode="types",
            variant_params={"mode": "types"},
            tested_table_ddl_fallback="CREATE TABLE bench.events (...) ENGINE=MergeTree ORDER BY user_id",
            source_table_ddl_fallback=None,
            result=result,
        )

        self.assertEqual(len(store.capturing_client.insert_calls), 1)
        main_insert_call = next(
            call for call in store.capturing_client.insert_calls if call["table"] == "bench.results"
        )

        columns = list(main_insert_call["column_names"])
        row = list(main_insert_call["data"][0])
        row_by_column = dict(zip(columns, row))

        self.assertIn("tested_table_select_metrics_by_query_json", columns)
        self.assertIn("source_table_select_metrics_by_query_json", columns)
        self.assertIn("score_calculation_json", columns)
        self.assertIn(
            "tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json",
            columns,
        )
        self.assertIn("tested_table_consumed_compressed_size_bytes_with_indexes", columns)
        self.assertIn(
            "tested_table_consumed_compressed_size_bytes_with_indexes_readable",
            columns,
        )
        tested_per_query_json = json.loads(
            row_by_column["tested_table_select_metrics_by_query_json"] or "{}"
        )
        source_per_query_json = json.loads(
            row_by_column["source_table_select_metrics_by_query_json"] or "{}"
        )
        speedup_per_query_json = json.loads(
            row_by_column["tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json"]
            or "{}"
        )
        self.assertIn("query_0", tested_per_query_json)
        self.assertIn("query_0", source_per_query_json)
        self.assertIn("query_0", speedup_per_query_json)
        self.assertEqual(
            tested_per_query_json["query_0"]["elapsed_ms_measurements"],
            [10, 20],
        )
        self.assertEqual(
            speedup_per_query_json["query_0"]["elapsed_ms_percentiles_speed_up_coefs"],
            [2.0, 2.0],
        )
        self.assertIn("\n", row_by_column["score_calculation_json"])
        self.assertEqual(
            json.loads(row_by_column["score_calculation_json"]),
            {"mode": "expression", "final_score": 1.0},
        )
        self.assertIn("\n", row_by_column["variant_params"])
        self.assertEqual(json.loads(row_by_column["variant_params"]), {"mode": "types"})
        self.assertEqual(
            row_by_column["tested_table_consumed_compressed_size_bytes_with_indexes"],
            1234.0,
        )
        self.assertEqual(
            row_by_column["tested_table_consumed_compressed_size_bytes_with_indexes_readable"],
            "1.21 KiB",
        )

    def test_store_formats_sql_ddl_and_queries_before_insert(self) -> None:
        store = _CapturingStore()

        result = BenchmarkVariantResult(
            benchmark_run_id=11,
            benchmark_started_at=datetime(2026, 2, 24, 13, 0, tzinfo=timezone.utc),
            benchmark_id="bench_sql_format",
            source_database="analytics",
            source_table="events",
            variant_table="events__bench__bench_sql_format__0001",
            variant_mode="types",
            tested_table_ddl=(
                "create table bench.events (`user_id` UInt64, `event_time` DateTime) "
                "engine = MergeTree order by user_id"
            ),
            source_table_ddl=(
                "create table analytics.events (`user_id` UInt64, `event_time` DateTime) "
                "engine = MergeTree order by user_id"
            ),
            tested_table_select_test_query=(
                "select count() from `bench`.`events` "
                "where user_id > 0 order by event_time limit 10"
            ),
            source_table_select_test_query=(
                "select count() from `analytics`.`events` "
                "where user_id > 0 order by event_time limit 10"
            ),
            tested_table_select_metrics_by_query_json=json.dumps(
                [
                    {
                        "query_index": 0,
                        "query_id": "q_agg_user",
                        "query": (
                            "select user_id, count() from `bench`.`events` "
                            "group by user_id order by count() desc limit 5"
                        ),
                        "warmup_queries": ["select count() from `bench`.`events`"],
                    }
                ]
            ),
            source_table_select_metrics_by_query_json=json.dumps(
                [
                    {
                        "query_index": 0,
                        "query_id": "q_agg_user",
                        "query": (
                            "select user_id, count() from `analytics`.`events` "
                            "group by user_id order by count() desc limit 5"
                        ),
                        "warmup_queries": ["select count() from `analytics`.`events`"],
                    }
                ]
            ),
            tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json=json.dumps(
                [
                    {
                        "query_index": 0,
                        "query_id": "q_agg_user",
                        "query": "select count() from `bench`.`events`",
                        "source_query": "select count() from `analytics`.`events`",
                        "elapsed_ms_percentiles_speed_up_coefs": [1.1, 1.2],
                    }
                ]
            ),
            score=1.0,
        )

        store.store_worker_result(
            benchmark_run_id=11,
            benchmark_started_at=datetime(2026, 2, 24, 13, 0, tzinfo=timezone.utc),
            benchmark_id="bench_sql_format",
            source_database="analytics",
            source_table="events",
            variant_table="events__bench__bench_sql_format__0001",
            variant_mode="types",
            variant_params={"mode": "types"},
            tested_table_ddl_fallback=result.tested_table_ddl or "",
            source_table_ddl_fallback=result.source_table_ddl,
            result=result,
        )

        self.assertEqual(len(store.capturing_client.insert_calls), 1)
        main_insert_call = next(
            call for call in store.capturing_client.insert_calls if call["table"] == "bench.results"
        )
        main_columns = list(main_insert_call["column_names"])
        main_row = list(main_insert_call["data"][0])
        row_by_column = dict(zip(main_columns, main_row))

        self.assertIn("\n", row_by_column["tested_table_ddl"])
        self.assertTrue(row_by_column["tested_table_ddl"].startswith("CREATE TABLE"))
        self.assertIn("\n", row_by_column["source_table_ddl"])
        self.assertTrue(row_by_column["source_table_ddl"].startswith("CREATE TABLE"))

        self.assertTrue(row_by_column["tested_table_select_test_query"].startswith("SELECT"))
        self.assertIn("\nFROM", row_by_column["tested_table_select_test_query"])
        self.assertTrue(row_by_column["source_table_select_test_query"].startswith("SELECT"))
        self.assertIn("\nFROM", row_by_column["source_table_select_test_query"])

        tested_per_query_json = json.loads(
            row_by_column["tested_table_select_metrics_by_query_json"] or "{}"
        )
        source_per_query_json = json.loads(
            row_by_column["source_table_select_metrics_by_query_json"] or "{}"
        )
        speedup_per_query_json = json.loads(
            row_by_column["tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json"]
            or "{}"
        )
        self.assertIn("q_agg_user", tested_per_query_json)
        self.assertIn("q_agg_user", source_per_query_json)
        self.assertIn("q_agg_user", speedup_per_query_json)
        self.assertTrue(tested_per_query_json["q_agg_user"]["query"].startswith("SELECT"))
        self.assertTrue(source_per_query_json["q_agg_user"]["query"].startswith("SELECT"))


if __name__ == "__main__":
    unittest.main()
