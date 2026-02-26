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


class _RankingStore(_CapturingStore):
    def __init__(self) -> None:
        self.update_calls: List[Dict[str, Any]] = []
        self.select_calls: List[Dict[str, Any]] = []
        self._rank_rows_by_mode: Dict[str, List[tuple[str, Optional[float]]]] = {}
        self._scope_rows_by_mode: Dict[str, int] = {}
        self._marked_rows_by_mode: Dict[str, int] = {}
        self._run_row_top_n = 1
        self._run_row_limits_json = json.dumps(
            {
                "order_by": 4,
                "types": 3,
                "codecs": 2,
                "indexes": 2,
                "final_validation": 1,
                "sequential": 1,
            }
        )
        super().__init__()

    def set_rank_rows(
        self,
        variant_mode: str,
        rows: List[tuple[str, Optional[float]]],
    ) -> None:
        self._rank_rows_by_mode[variant_mode] = list(rows)

    def set_scope_counts(
        self,
        *,
        variant_mode: str,
        scope_rows: int,
        marked_rows: int,
    ) -> None:
        self._scope_rows_by_mode[variant_mode] = int(scope_rows)
        self._marked_rows_by_mode[variant_mode] = int(marked_rows)

    def _execute(self, query: str, params: Optional[Any] = None):
        normalized = " ".join(query.split()).lower()
        if "select top_n_winners, sequential_top_n_limits_json" in normalized:
            return [[self._run_row_top_n, self._run_row_limits_json]]
        if "select count()" in normalized:
            mode = ""
            if isinstance(params, dict):
                mode = str(params.get("variant_mode") or "")
            if "and is_top_n = 1" in normalized:
                return [[self._marked_rows_by_mode.get(mode, 0)]]
            return [[self._scope_rows_by_mode.get(mode, 0)]]
        if "select id, score" in normalized:
            mode = ""
            if isinstance(params, dict):
                mode = str(params.get("variant_mode") or "")
            self.select_calls.append(dict(params or {}))
            return list(self._rank_rows_by_mode.get(mode, []))
        if " alter table " in f" {normalized} " and " update " in f" {normalized} ":
            self.update_calls.append(dict(params or {}))
            return []
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
        self.assertIn("tested_table_insert_metrics_json", columns)
        self.assertIn("source_table_insert_metrics_json", columns)
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
        tested_insert_metrics_json = json.loads(
            row_by_column["tested_table_insert_metrics_json"] or "{}"
        )
        source_insert_metrics_json = json.loads(
            row_by_column["source_table_insert_metrics_json"] or "{}"
        )
        self.assertIn("query_0", tested_per_query_json)
        self.assertIn("query_0", source_per_query_json)
        self.assertIn("query_0", speedup_per_query_json)
        self.assertIn("insert_main", tested_insert_metrics_json)
        self.assertIn("insert_main", source_insert_metrics_json)
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

    def test_recalculate_phase_ranking_scopes_to_variant_mode(self) -> None:
        store = _RankingStore()
        store.set_rank_rows(
            "types_validation",
            [
                ("tv_1", 10.0),
                ("tv_2", 9.0),
                ("tv_3", 8.0),
                ("tv_4", 7.0),
            ],
        )
        store.set_rank_rows(
            "types",
            [
                ("t_1", 100.0),
                ("t_2", 90.0),
            ],
        )

        store._recalculate_phase_ranking(
            benchmark_run_id=77,
            benchmark_id="bench_rank",
            source_database="analytics",
            source_table="events",
            phase=2,
            variant_mode="types_validation",
            phase_name="types_validation",
        )

        self.assertTrue(store.select_calls)
        self.assertEqual(store.select_calls[0].get("variant_mode"), "types_validation")
        self.assertEqual(len(store.update_calls), 4)
        self.assertEqual(
            [int(call["rank_in_phase"]) for call in store.update_calls],
            [1, 2, 3, 4],
        )
        self.assertEqual(
            [bool(call["is_top_n"]) for call in store.update_calls],
            [True, True, True, False],
        )
        self.assertTrue(all(call.get("variant_mode") == "types_validation" for call in store.update_calls))

    def test_resolve_top_n_winners_maps_validation_mode_to_stage_limit(self) -> None:
        store = _RankingStore()

        top_n_types_validation = store._resolve_top_n_winners(
            benchmark_run_id=77,
            benchmark_id="bench_rank",
            source_database="analytics",
            source_table="events",
            phase=2,
            variant_mode="types_validation",
            phase_name="types_validation",
        )
        top_n_order_by_banner = store._resolve_top_n_winners(
            benchmark_run_id=77,
            benchmark_id="bench_rank",
            source_database="analytics",
            source_table="events",
            phase=1,
            variant_mode="order_by",
            phase_name="ORDER BY",
        )

        self.assertEqual(top_n_types_validation, 3)
        self.assertEqual(top_n_order_by_banner, 4)

    def test_mark_top_n_variant_tables_sets_flag_only_for_winners(self) -> None:
        store = _RankingStore()
        store.set_scope_counts(variant_mode="codecs_validation", scope_rows=2, marked_rows=2)

        store.mark_top_n_variant_tables(
            benchmark_run_id=77,
            benchmark_id="bench_rank",
            source_database="analytics",
            source_table="events",
            phase=3,
            variant_mode="codecs_validation",
            phase_name="codecs_validation",
            winner_variant_tables=["v_2", "v_4", "v_2"],
        )

        # 1 mutation на reset + 2 mutations на уникальных winners.
        self.assertEqual(len(store.update_calls), 3)
        self.assertNotIn("winner_variant_table", store.update_calls[0])
        self.assertEqual(store.update_calls[1]["winner_variant_table"], "v_2")
        self.assertEqual(store.update_calls[2]["winner_variant_table"], "v_4")
        self.assertTrue(
            all(call.get("variant_mode") == "codecs_validation" for call in store.update_calls)
        )

    def test_mark_top_n_variant_tables_fallbacks_to_recalc_when_no_rows_marked(self) -> None:
        store = _RankingStore()
        store.set_scope_counts(variant_mode="codecs_validation", scope_rows=3, marked_rows=0)
        store.set_rank_rows(
            "codecs_validation",
            [
                ("v_1", 10.0),
                ("v_2", 9.0),
                ("v_3", 8.0),
            ],
        )
        store._run_row_top_n = 2
        store._run_row_limits_json = json.dumps({"codecs": 2, "sequential": 1})

        store.mark_top_n_variant_tables(
            benchmark_run_id=77,
            benchmark_id="bench_rank",
            source_database="analytics",
            source_table="events",
            phase=3,
            variant_mode="codecs_validation",
            phase_name="codecs_validation",
            winner_variant_tables=["missing_variant"],
        )

        # После reset + winner-update должен сработать fallback recalc с rank updates.
        rank_updates = [call for call in store.update_calls if "rank_in_phase" in call]
        self.assertTrue(rank_updates)
        self.assertEqual(
            [int(call["rank_in_phase"]) for call in rank_updates],
            [1, 2, 3],
        )

    def test_mark_top_n_variant_tables_fallbacks_to_recalc_when_marked_rows_less_than_expected(
        self,
    ) -> None:
        store = _RankingStore()
        store.set_scope_counts(variant_mode="types_validation", scope_rows=4, marked_rows=1)
        store.set_rank_rows(
            "types_validation",
            [
                ("v_1", 11.0),
                ("v_2", 10.0),
                ("v_3", 9.0),
                ("v_4", 8.0),
            ],
        )
        store._run_row_top_n = 3
        store._run_row_limits_json = json.dumps({"types": 3, "sequential": 1})

        store.mark_top_n_variant_tables(
            benchmark_run_id=77,
            benchmark_id="bench_rank",
            source_database="analytics",
            source_table="events",
            phase=2,
            variant_mode="types_validation",
            phase_name="types_validation",
            winner_variant_tables=["v_1"],
        )

        rank_updates = [call for call in store.update_calls if "rank_in_phase" in call]
        self.assertTrue(rank_updates)
        self.assertEqual(
            [bool(call["is_top_n"]) for call in rank_updates],
            [True, True, True, False],
        )


if __name__ == "__main__":
    unittest.main()
