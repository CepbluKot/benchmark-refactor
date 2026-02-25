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
            tested_table_select_metrics_by_query_json='[{"query_index":0}]',
            source_table_select_metrics_by_query_json='[{"query_index":0}]',
            tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json=(
                '[{"query_index":0,"elapsed_ms_percentiles_speed_up_coefs":[1.5,2.0]}]'
            ),
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

        self.assertTrue(
            any(
                "ADD COLUMN IF NOT EXISTS `tested_table_select_metrics_by_query_json`" in query
                for query in store.executed_queries
            )
        )
        self.assertTrue(
            any(
                "ADD COLUMN IF NOT EXISTS `source_table_select_metrics_by_query_json`" in query
                for query in store.executed_queries
            )
        )
        self.assertTrue(
            any(
                "tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json" in query
                for query in store.executed_queries
            )
        )

        self.assertEqual(len(store.capturing_client.insert_calls), 1)
        insert_call = store.capturing_client.insert_calls[0]
        columns = list(insert_call["column_names"])
        row = list(insert_call["data"][0])
        row_by_column = dict(zip(columns, row))

        self.assertIn("tested_table_select_metrics_by_query_json", columns)
        self.assertIn("source_table_select_metrics_by_query_json", columns)
        self.assertIn("score_calculation_json", columns)
        self.assertIn(
            "tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json",
            columns,
        )
        self.assertEqual(
            json.loads(row_by_column["tested_table_select_metrics_by_query_json"]),
            [{"query_index": 0}],
        )
        self.assertEqual(
            json.loads(row_by_column["source_table_select_metrics_by_query_json"]),
            [{"query_index": 0}],
        )
        self.assertEqual(
            json.loads(row_by_column["tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json"]),
            [{"query_index": 0, "elapsed_ms_percentiles_speed_up_coefs": [1.5, 2.0]}],
        )
        self.assertIn("\n", row_by_column["tested_table_select_metrics_by_query_json"])
        self.assertIn("\n", row_by_column["source_table_select_metrics_by_query_json"])
        self.assertIn("\n", row_by_column["score_calculation_json"])
        self.assertEqual(
            json.loads(row_by_column["score_calculation_json"]),
            {"mode": "expression", "final_score": 1.0},
        )
        self.assertIn(
            "\n",
            row_by_column["tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json"],
        )
        self.assertIn("\n", row_by_column["variant_params"])
        self.assertEqual(json.loads(row_by_column["variant_params"]), {"mode": "types"})


if __name__ == "__main__":
    unittest.main()
