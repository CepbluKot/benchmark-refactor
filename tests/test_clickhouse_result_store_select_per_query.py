import unittest
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from src.benchmark_runtime.implementations.clickhouse_celery.result_store import (
    ClickHouseBenchmarkResultStore,
    ClickHouseConnectionParams,
)
from src.benchmark_runtime.types import BenchmarkVariantResult


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


class _CapturingClient:
    def __init__(self, *, stored_record_ids: Optional[set[str]] = None) -> None:
        self.insert_calls: List[Dict[str, Any]] = []
        self.stored_record_ids = stored_record_ids

    def insert(self, table: str, data: List[tuple], column_names: List[str]) -> None:
        self.insert_calls.append(
            {
                "table": table,
                "data": data,
                "column_names": column_names,
            }
        )
        if self.stored_record_ids is None:
            return
        if not data or "id" not in column_names:
            return
        id_index = column_names.index("id")
        for row in data:
            if id_index < len(row):
                self.stored_record_ids.add(str(row[id_index]))

    def close(self) -> None:
        return None


class _CapturingStore(ClickHouseBenchmarkResultStore):
    def __init__(self) -> None:
        self.executed_queries: List[str] = []
        self.stored_record_ids: set[str] = set()
        self.capturing_client = _CapturingClient(stored_record_ids=self.stored_record_ids)
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

    def _init_redis_lock_client(self) -> None:
        self._record_lock_redis_client = _NoopRedisClient()

    def _execute(self, query: str, params: Optional[Any] = None):
        normalized = " ".join(query.split()).lower()
        if normalized.startswith("select 1 from"):
            record_id = ""
            if isinstance(params, dict):
                record_id = str(params.get("id") or "")
            return [[1]] if record_id in self.stored_record_ids else []
        self.executed_queries.append(query)
        return []


class _IdentityCollisionStore(_CapturingStore):
    def _execute(self, query: str, params: Optional[Any] = None):
        normalized = " ".join(query.split()).lower()
        if normalized.startswith("select 1 from"):
            return [[1]]
        if normalized.startswith(
            "select benchmark_run_id, benchmark_id, source_db_name, source_table_name, variant_table, variant_mode from"
        ):
            return [[999, "foreign_bench", "foreign_db", "foreign_table", "foreign_variant", "types"]]
        return super()._execute(query, params)


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


class _MaxRunIdStore(ClickHouseBenchmarkResultStore):
    def __init__(
        self,
        *,
        phased_exists: bool,
        legacy_exists: bool,
        phased_max: Optional[int],
        legacy_max: Optional[int],
        create_legacy_table: bool = True,
    ) -> None:
        self.capturing_client = _CapturingClient()
        self.ensure_schema_calls = 0
        self.executed_queries: List[str] = []
        self.exists_by_table: Dict[str, int] = {
            "results_phased": 1 if phased_exists else 0,
            "results_legacy": 1 if legacy_exists else 0,
        }
        self.max_by_table: Dict[str, Optional[int]] = {
            "results_phased": phased_max,
            "results_legacy": legacy_max,
        }
        super().__init__(
            connection=ClickHouseConnectionParams(
                host="localhost",
                port=9000,
                login="default",
                password="secret",
            ),
            database="bench",
            table="results_phased",
            legacy_table="results_legacy",
            phased_table="results_phased",
            create_legacy_table=create_legacy_table,
            create_table_if_missing=False,
        )

    def _build_client(self):
        return self.capturing_client

    def _init_redis_lock_client(self) -> None:
        self._record_lock_redis_client = _NoopRedisClient()

    def ensure_schema(self) -> None:
        self.ensure_schema_calls += 1
        for table_name in self.exists_by_table:
            self.exists_by_table[table_name] = 1

    def _execute(self, query: str, params: Optional[Any] = None):
        del params
        self.executed_queries.append(query)
        normalized = " ".join(query.split()).lower()
        if normalized.startswith("exists table"):
            if "results_phased" in normalized:
                return [[self.exists_by_table["results_phased"]]]
            if "results_legacy" in normalized:
                return [[self.exists_by_table["results_legacy"]]]
            return [[0]]
        if normalized.startswith("select max(benchmark_run_id)"):
            if "results_phased" in normalized:
                return [[self.max_by_table["results_phased"]]]
            if "results_legacy" in normalized:
                return [[self.max_by_table["results_legacy"]]]
            return [[None]]
        return []


class _FailFastStore(ClickHouseBenchmarkResultStore):
    def __init__(self) -> None:
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
            create_table_if_missing=False,
        )

    def _build_client(self):
        return self.capturing_client

    def _execute(self, query: str, params: Optional[Any] = None):
        del query, params
        return []


class _CustomScoreRecalcStore(_CapturingStore):
    def __init__(self) -> None:
        self.recalc_rows: List[tuple[str, Optional[str]]] = []
        self.recalc_updates: List[Dict[str, Any]] = []
        super().__init__()

    def _execute(self, query: str, params: Optional[Any] = None):
        normalized = " ".join(query.split()).lower()
        if normalized.startswith("select id, score_calculation_json"):
            return list(self.recalc_rows)
        if " alter table " in f" {normalized} " and " update score_custom " in f" {normalized} ":
            self.recalc_updates.append(dict(params or {}))
            return []
        return super()._execute(query, params)


class _CloneDedupStore(_CapturingStore):
    def __init__(self) -> None:
        self.candidate_query_params: Optional[Dict[str, Any]] = None
        self.insert_select_params: Optional[Dict[str, Any]] = None
        super().__init__()

    def _execute(self, query: str, params: Optional[Any] = None):
        normalized = " ".join(query.split()).lower()
        if normalized.startswith("select 1 from"):
            return []
        if (
            "select id, benchmark_run_id, variant_table, tested_table_ddl, score, measurement_quality_flag, variant_params"
            in normalized
            and "where benchmark_id = %(benchmark_id)s" in normalized
            and "variant_mode = %(variant_mode)s" in normalized
            and "limit 5000" in normalized
        ):
            self.candidate_query_params = dict(params or {})
            runtime_params = {
                "__runtime_query_signature": "sig_q",
                "__runtime_insert_rows_limit": 100000,
                "__runtime_insert_operations_count": 10,
                "__runtime_measured_percentiles_signature": "[1,50,95,99,100]",
            }
            return [
                [
                    "prev_result_id_1",
                    77,  # previous run_id
                    "old_variant_table",
                    "CREATE TABLE bench.results (`x` UInt32) ENGINE = MergeTree ORDER BY x",
                    1.111,
                    "stable",
                    json.dumps(runtime_params, ensure_ascii=False),
                ]
            ]
        if normalized.startswith("select id from"):
            return []
        if normalized.startswith("insert into"):
            self.insert_select_params = dict(params or {})
            return []
        return super()._execute(query, params)


class ClickHouseResultStorePerQuerySelectTests(unittest.TestCase):
    def test_store_uses_localhost_redis_fallback_when_urls_not_set(self) -> None:
        with patch.dict(
            os.environ,
            {
                "BENCH_RESULT_STORE_REDIS_URL": "",
                "BENCH_CELERY_BACKEND_URL": "",
            },
            clear=False,
        ):
            store = _CapturingStore()
            self.assertEqual(
                store._record_lock_redis_url,  # noqa: SLF001
                "redis://localhost:6379/0",
            )

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
                '[{"query_index":0,"elapsed_ms_percentiles_speed_up_coefs":[2.0,2.0],'
                '"read_bytes_percentiles_speed_up_coefs":[1.8,1.6]}]'
            ),
            tested_table_consumed_compressed_size_bytes_with_indexes=1234.0,
            tested_table_consumed_compressed_size_bytes_with_indexes_readable="1.21 KiB",
            tested_table_consumed_compressed_size_bytes_with_indexes_json=(
                '{"size_bytes":1234.0,"size_bytes_readable":"1.21 KiB",'
                '"bytes_on_disk_sum":1500.0,"bytes_on_disk_sum_readable":"1.46 KiB"}'
            ),
            tested_table_primary_index_size_json=(
                '{"size_bytes":321.0,"size_bytes_readable":"321 B",'
                '"size_percent_from_total_size":26.0129}'
            ),
            measurement_quality_flag="stable",
            measurement_quality_details_json=(
                '{"quality_flag":"stable","total_queries":1,"noisy_queries":0}'
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
        self.assertIn(
            "tested_table_select_time_ms_percentiles_speed_up_coefs_vs_source_by_query_json",
            columns,
        )
        self.assertIn(
            "tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json",
            columns,
        )
        self.assertIn("tested_table_consumed_compressed_size_bytes_with_indexes_json", columns)
        self.assertIn("tested_table_primary_index_size_json", columns)
        self.assertIn("variant_mode_id", columns)
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
        speedup_vs_source_per_query_json = json.loads(
            row_by_column[
                "tested_table_select_time_ms_percentiles_speed_up_coefs_vs_source_by_query_json"
            ]
            or "{}"
        )
        read_bytes_speedup_per_query_json = json.loads(
            row_by_column[
                "tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json"
            ]
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
        self.assertIn("query_0", read_bytes_speedup_per_query_json)
        self.assertEqual(speedup_vs_source_per_query_json, speedup_per_query_json)
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
        self.assertEqual(
            read_bytes_speedup_per_query_json["query_0"][
                "read_bytes_percentiles_speed_up_coefs"
            ],
            [1.8, 1.6],
        )
        self.assertIn("\n", row_by_column["score_calculation_json"])
        self.assertEqual(
            json.loads(row_by_column["score_calculation_json"]),
            {"mode": "expression", "final_score": 1.0},
        )
        self.assertIn("\n", row_by_column["variant_params"])
        self.assertEqual(json.loads(row_by_column["variant_params"]), {"mode": "types"})
        tested_size_json = json.loads(
            row_by_column["tested_table_consumed_compressed_size_bytes_with_indexes_json"]
            or "{}"
        )
        self.assertEqual(tested_size_json.get("size_bytes"), 1234.0)
        self.assertEqual(tested_size_json.get("size_bytes_readable"), "1.21 KiB")
        self.assertEqual(tested_size_json.get("bytes_on_disk_sum"), 1500.0)
        self.assertEqual(tested_size_json.get("bytes_on_disk_sum_readable"), "1.46 KiB")
        primary_index_json = json.loads(row_by_column["tested_table_primary_index_size_json"] or "{}")
        self.assertEqual(primary_index_json.get("size_bytes"), 321.0)
        self.assertEqual(primary_index_json.get("size_bytes_readable"), "321 B")
        self.assertEqual(primary_index_json.get("size_percent_from_total_size"), 26.0129)
        self.assertEqual(row_by_column.get("measurement_quality_flag"), "stable")
        self.assertEqual(
            json.loads(row_by_column.get("measurement_quality_details_json") or "{}"),
            {"quality_flag": "stable", "total_queries": 1, "noisy_queries": 0},
        )
        self.assertEqual(int(row_by_column["variant_mode_id"]), 1)

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
        speedup_vs_source_per_query_json = json.loads(
            row_by_column[
                "tested_table_select_time_ms_percentiles_speed_up_coefs_vs_source_by_query_json"
            ]
            or "{}"
        )
        self.assertIn("q_agg_user", tested_per_query_json)
        self.assertIn("q_agg_user", source_per_query_json)
        self.assertIn("q_agg_user", speedup_per_query_json)
        self.assertEqual(speedup_vs_source_per_query_json, speedup_per_query_json)
        self.assertTrue(tested_per_query_json["q_agg_user"]["query"].startswith("SELECT"))
        self.assertTrue(source_per_query_json["q_agg_user"]["query"].startswith("SELECT"))

    def test_store_phased_duplicates_select_speedup_json_to_vs_source_column(self) -> None:
        store = _CapturingStore()

        result = BenchmarkVariantResult(
            benchmark_run_id=15,
            benchmark_started_at=datetime(2026, 2, 24, 18, 0, tzinfo=timezone.utc),
            benchmark_id="bench_phased_speedup_dup",
            source_database="analytics",
            source_table="events",
            variant_table="events__bench__bench_phased_speedup_dup__0001",
            variant_mode="types_validation",
            tested_table_ddl=(
                "CREATE TABLE benchmark_tmp.events__bench__bench_phased_speedup_dup__0001 "
                "(`user_id` Int32) ENGINE = MergeTree ORDER BY user_id"
            ),
            tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json=json.dumps(
                [
                    {
                        "query_index": 0,
                        "query_id": "q_main",
                        "elapsed_ms_percentiles_speed_up_coefs": [1.2, 1.3],
                    }
                ],
                ensure_ascii=False,
            ),
            score=1.0,
        )

        store.store_worker_result(
            benchmark_run_id=15,
            benchmark_started_at=datetime(2026, 2, 24, 18, 0, tzinfo=timezone.utc),
            benchmark_id="bench_phased_speedup_dup",
            benchmark_strategy="sequential_phased_topn_strategy",
            source_database="analytics",
            source_table="events",
            variant_table="events__bench__bench_phased_speedup_dup__0001",
            variant_mode="types_validation",
            variant_params={"mode": "types_validation"},
            tested_table_ddl_fallback=result.tested_table_ddl or "",
            source_table_ddl_fallback=None,
            result=result,
        )

        self.assertEqual(len(store.capturing_client.insert_calls), 1)
        phased_insert_call = store.capturing_client.insert_calls[0]
        columns = list(phased_insert_call["column_names"])
        row = list(phased_insert_call["data"][0])
        row_by_column = dict(zip(columns, row))

        self.assertIn(
            "tested_table_select_time_ms_percentiles_speed_up_coefs_vs_source_by_query_json",
            columns,
        )
        self.assertEqual(
            row_by_column[
                "tested_table_select_time_ms_percentiles_speed_up_coefs_vs_source_by_query_json"
            ],
            row_by_column["tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json"],
        )

    def test_store_worker_result_uses_fallback_when_tested_ddl_table_mismatch(self) -> None:
        store = _CapturingStore()

        result = BenchmarkVariantResult(
            benchmark_run_id=12,
            benchmark_started_at=datetime(2026, 2, 24, 14, 0, tzinfo=timezone.utc),
            benchmark_id="bench_mismatch_ddl",
            source_database="dm_core_lm",
            source_table="logs_dbt",
            variant_table="logs_dbt__bench__bench_mismatch_ddl__0001",
            variant_mode="types",
            # Намеренно некорректный DDL: имя другой таблицы.
            tested_table_ddl=(
                "CREATE TABLE benchmark_tmp.logs_adqm__bench__bench_mismatch_ddl__0001 "
                "(`msg` String) ENGINE = MergeTree ORDER BY msg"
            ),
            score=1.0,
        )

        fallback_ddl = (
            "CREATE TABLE benchmark_tmp.logs_dbt__bench__bench_mismatch_ddl__0001 "
            "(`msg` String) ENGINE = MergeTree ORDER BY msg"
        )

        store.store_worker_result(
            benchmark_run_id=12,
            benchmark_started_at=datetime(2026, 2, 24, 14, 0, tzinfo=timezone.utc),
            benchmark_id="bench_mismatch_ddl",
            source_database="dm_core_lm",
            source_table="logs_dbt",
            variant_table="logs_dbt__bench__bench_mismatch_ddl__0001",
            variant_mode="types",
            variant_params={"mode": "types"},
            tested_table_ddl_fallback=fallback_ddl,
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
        stored_ddl = str(row_by_column["tested_table_ddl"])
        self.assertIn("logs_dbt__bench__bench_mismatch_ddl__0001", stored_ddl)
        self.assertNotIn("logs_adqm__bench__bench_mismatch_ddl__0001", stored_ddl)

    def test_store_worker_result_is_idempotent_by_execution_uuid_in_process(self) -> None:
        store = _CapturingStore()

        result = BenchmarkVariantResult(
            benchmark_run_id=99,
            benchmark_started_at=datetime(2026, 2, 24, 15, 0, tzinfo=timezone.utc),
            benchmark_id="bench_idempotent",
            source_database="analytics",
            source_table="events",
            variant_table="events__bench__bench_idempotent__0001",
            variant_mode="types",
            tested_table_ddl=(
                "CREATE TABLE benchmark_tmp.events__bench__bench_idempotent__0001 "
                "(`user_id` Int32) ENGINE = MergeTree ORDER BY user_id"
            ),
            score=1.0,
        )
        payload_kwargs = dict(
            benchmark_run_id=99,
            benchmark_started_at=datetime(2026, 2, 24, 15, 0, tzinfo=timezone.utc),
            benchmark_id="bench_idempotent",
            source_database="analytics",
            source_table="events",
            variant_table="events__bench__bench_idempotent__0001",
            variant_mode="types",
            variant_params={"mode": "types", "execution_uuid": "exec-idempotent-1"},
            tested_table_ddl_fallback=result.tested_table_ddl or "",
            source_table_ddl_fallback=None,
            result=result,
        )

        store.store_worker_result(**payload_kwargs)
        store.store_worker_result(**payload_kwargs)

        self.assertEqual(len(store.capturing_client.insert_calls), 1)

    def test_store_worker_result_same_execution_uuid_for_different_variants_does_not_conflict(self) -> None:
        store = _CapturingStore()

        base_result = BenchmarkVariantResult(
            benchmark_run_id=100,
            benchmark_started_at=datetime(2026, 2, 24, 15, 5, tzinfo=timezone.utc),
            benchmark_id="bench_uuid_scope",
            source_database="analytics",
            source_table="events",
            variant_table="events__bench__bench_uuid_scope__0001",
            variant_mode="types",
            tested_table_ddl=(
                "CREATE TABLE benchmark_tmp.events__bench__bench_uuid_scope__0001 "
                "(`user_id` Int32) ENGINE = MergeTree ORDER BY user_id"
            ),
            score=1.0,
        )

        store.store_worker_result(
            benchmark_run_id=100,
            benchmark_started_at=datetime(2026, 2, 24, 15, 5, tzinfo=timezone.utc),
            benchmark_id="bench_uuid_scope",
            source_database="analytics",
            source_table="events",
            variant_table="events__bench__bench_uuid_scope__0001",
            variant_mode="types",
            variant_params={"mode": "types", "execution_uuid": "shared-exec-uuid"},
            tested_table_ddl_fallback=base_result.tested_table_ddl or "",
            source_table_ddl_fallback=None,
            result=base_result,
        )

        second_result = base_result.model_copy(
            update={
                "variant_table": "events__bench__bench_uuid_scope__0002",
                "tested_table_ddl": (
                    "CREATE TABLE benchmark_tmp.events__bench__bench_uuid_scope__0002 "
                    "(`user_id` Int32) ENGINE = MergeTree ORDER BY user_id"
                ),
            }
        )
        store.store_worker_result(
            benchmark_run_id=100,
            benchmark_started_at=datetime(2026, 2, 24, 15, 5, tzinfo=timezone.utc),
            benchmark_id="bench_uuid_scope",
            source_database="analytics",
            source_table="events",
            variant_table="events__bench__bench_uuid_scope__0002",
            variant_mode="types",
            variant_params={"mode": "types", "execution_uuid": "shared-exec-uuid"},
            tested_table_ddl_fallback=second_result.tested_table_ddl or "",
            source_table_ddl_fallback=None,
            result=second_result,
        )

        self.assertEqual(len(store.capturing_client.insert_calls), 2)

    def test_store_worker_result_raises_on_duplicate_id_identity_collision(self) -> None:
        store = _IdentityCollisionStore()

        result = BenchmarkVariantResult(
            benchmark_run_id=101,
            benchmark_started_at=datetime(2026, 2, 24, 15, 10, tzinfo=timezone.utc),
            benchmark_id="bench_collision_guard",
            source_database="analytics",
            source_table="events",
            variant_table="events__bench__bench_collision_guard__0001",
            variant_mode="types",
            tested_table_ddl=(
                "CREATE TABLE benchmark_tmp.events__bench__bench_collision_guard__0001 "
                "(`user_id` Int32) ENGINE = MergeTree ORDER BY user_id"
            ),
            score=1.0,
        )

        with self.assertRaisesRegex(RuntimeError, "record id collision"):
            store.store_worker_result(
                benchmark_run_id=101,
                benchmark_started_at=datetime(2026, 2, 24, 15, 10, tzinfo=timezone.utc),
                benchmark_id="bench_collision_guard",
                source_database="analytics",
                source_table="events",
                variant_table="events__bench__bench_collision_guard__0001",
                variant_mode="types",
                variant_params={"mode": "types", "execution_uuid": "collision-id"},
                tested_table_ddl_fallback=result.tested_table_ddl or "",
                source_table_ddl_fallback=None,
                result=result,
            )
        self.assertEqual(len(store.capturing_client.insert_calls), 0)

    def test_store_phased_does_not_include_legacy_indexes_percent_column(self) -> None:
        store = _CapturingStore()

        result = BenchmarkVariantResult(
            benchmark_run_id=13,
            benchmark_started_at=datetime(2026, 2, 24, 16, 0, tzinfo=timezone.utc),
            benchmark_id="bench_phased_indexes_percent",
            source_database="analytics",
            source_table="events",
            variant_table="events__bench__bench_phased_indexes_percent__0001",
            variant_mode="indexes_validation",
            tested_table_ddl=(
                "CREATE TABLE benchmark_tmp.events__bench__bench_phased_indexes_percent__0001 "
                "(`user_id` Int32) ENGINE = MergeTree ORDER BY user_id"
            ),
            score=1.0,
        )

        store.store_worker_result(
            benchmark_run_id=13,
            benchmark_started_at=datetime(2026, 2, 24, 16, 0, tzinfo=timezone.utc),
            benchmark_id="bench_phased_indexes_percent",
            benchmark_strategy="sequential_phased_topn_strategy",
            source_database="analytics",
            source_table="events",
            variant_table="events__bench__bench_phased_indexes_percent__0001",
            variant_mode="indexes_validation",
            variant_params={"mode": "indexes_validation"},
            tested_table_ddl_fallback=result.tested_table_ddl or "",
            source_table_ddl_fallback=None,
            result=result,
        )

        self.assertEqual(len(store.capturing_client.insert_calls), 1)
        phased_insert_call = store.capturing_client.insert_calls[0]
        columns = list(phased_insert_call["column_names"])

        self.assertNotIn("tested_table_indexes_sizes_percent_from_col_size", columns)
        self.assertIn("tested_table_primary_index_size_json", columns)
        self.assertIn("variant_mode_id", columns)
        row = list(phased_insert_call["data"][0])
        row_by_column = dict(zip(columns, row))
        self.assertEqual(int(row_by_column["variant_mode_id"]), 1)

    def test_store_phased_size_bytes_indexes_json_contains_percent_from_source_table(self) -> None:
        store = _CapturingStore()

        result = BenchmarkVariantResult(
            benchmark_run_id=13,
            benchmark_started_at=datetime(2026, 2, 24, 16, 5, tzinfo=timezone.utc),
            benchmark_id="bench_phased_indexes_size_ratio",
            source_database="analytics",
            source_table="events",
            variant_table="events__bench__bench_phased_indexes_size_ratio__0001",
            variant_mode="indexes_validation",
            tested_table_ddl=(
                "CREATE TABLE benchmark_tmp.events__bench__bench_phased_indexes_size_ratio__0001 "
                "(`country` String) ENGINE = MergeTree ORDER BY country"
            ),
            source_table_consumed_compressed_size_bytes_overall=1_000.0,
            tested_table_indexes_sizes=json.dumps(
                {
                    "idx_country_tokenbf": {
                        "column": "country",
                        "size_compressed_bytes": 50,
                        "size_compressed_bytes_readable": "50 B",
                    }
                },
                ensure_ascii=False,
            ),
            score=1.0,
        )

        store.store_worker_result(
            benchmark_run_id=13,
            benchmark_started_at=datetime(2026, 2, 24, 16, 5, tzinfo=timezone.utc),
            benchmark_id="bench_phased_indexes_size_ratio",
            benchmark_strategy="sequential_phased_topn_strategy",
            source_database="analytics",
            source_table="events",
            variant_table="events__bench__bench_phased_indexes_size_ratio__0001",
            variant_mode="indexes_validation",
            variant_params={"mode": "indexes_validation"},
            tested_table_ddl_fallback=result.tested_table_ddl or "",
            source_table_ddl_fallback=None,
            result=result,
        )

        self.assertEqual(len(store.capturing_client.insert_calls), 1)
        phased_insert_call = store.capturing_client.insert_calls[0]
        columns = list(phased_insert_call["column_names"])
        row = list(phased_insert_call["data"][0])
        row_by_column = dict(zip(columns, row))

        self.assertIn("size_bytes_indexes_json", columns)
        size_indexes_json = json.loads(row_by_column["size_bytes_indexes_json"] or "{}")
        idx_payload = size_indexes_json.get("idx_country_tokenbf") or {}
        self.assertEqual(idx_payload.get("size_compressed_bytes"), 50)
        self.assertIsNone(idx_payload.get("size_percent_from_source_table"))
        self.assertEqual(
            idx_payload.get("data_skipping_index_size_percent_from_source_table"),
            5.0,
        )

    def test_store_phased_source_baseline_keeps_compression_coef_empty(self) -> None:
        store = _CapturingStore()

        result = BenchmarkVariantResult(
            benchmark_run_id=14,
            benchmark_started_at=datetime(2026, 2, 24, 17, 0, tzinfo=timezone.utc),
            benchmark_id="bench_source_baseline_coef",
            source_database="analytics",
            source_table="events",
            variant_table="events__source_baseline__abc123",
            variant_mode="source_baseline",
            tested_table_ddl=(
                "CREATE TABLE benchmark_tmp.events__source_baseline__abc123 "
                "(`user_id` Int32) ENGINE = MergeTree ORDER BY user_id"
            ),
            source_table_consumed_compressed_size_bytes_overall=220_000_000,
            tested_table_consumed_compressed_size_bytes_with_indexes=10_000_000,
            tested_table_compression_overall_coef=None,
            score=1.0,
        )

        store.store_worker_result(
            benchmark_run_id=14,
            benchmark_started_at=datetime(2026, 2, 24, 17, 0, tzinfo=timezone.utc),
            benchmark_id="bench_source_baseline_coef",
            benchmark_strategy="sequential_phased_topn_strategy",
            source_database="analytics",
            source_table="events",
            variant_table="events__source_baseline__abc123",
            variant_mode="source_baseline",
            variant_params={"mode": "source_baseline"},
            tested_table_ddl_fallback=result.tested_table_ddl or "",
            source_table_ddl_fallback=None,
            result=result,
        )

        self.assertEqual(len(store.capturing_client.insert_calls), 1)
        phased_insert_call = store.capturing_client.insert_calls[0]
        columns = list(phased_insert_call["column_names"])
        row = list(phased_insert_call["data"][0])
        row_by_column = dict(zip(columns, row))
        self.assertIsNone(row_by_column["tested_table_compression_overall_coef"])

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

    def test_max_benchmark_run_id_recovers_from_missing_tables(self) -> None:
        store = _MaxRunIdStore(
            phased_exists=False,
            legacy_exists=False,
            phased_max=7,
            legacy_max=5,
        )

        self.assertEqual(store.max_benchmark_run_id(), 7)
        self.assertGreaterEqual(store.ensure_schema_calls, 1)

    def test_max_benchmark_run_id_uses_max_from_phased_and_legacy(self) -> None:
        store = _MaxRunIdStore(
            phased_exists=True,
            legacy_exists=True,
            phased_max=4,
            legacy_max=9,
        )

        self.assertEqual(store.max_benchmark_run_id(), 9)
        self.assertEqual(store.ensure_schema_calls, 0)

    def test_max_benchmark_run_id_skips_legacy_when_disabled(self) -> None:
        store = _MaxRunIdStore(
            phased_exists=True,
            legacy_exists=False,
            phased_max=12,
            legacy_max=None,
            create_legacy_table=False,
        )

        self.assertEqual(store.max_benchmark_run_id(), 12)
        self.assertFalse(
            any("results_legacy" in query.lower() for query in store.executed_queries)
        )

    def test_recalculate_custom_score_for_benchmark_updates_score_custom(self) -> None:
        store = _CustomScoreRecalcStore()
        store.recalc_rows = [
            (
                "row_1",
                json.dumps(
                    {
                        "mode": "expression",
                        "context": {
                            "source_size_bytes": 200.0,
                            "tested_size_bytes": 100.0,
                        },
                    },
                    ensure_ascii=False,
                ),
            ),
            (
                "row_2",
                json.dumps(
                    {
                        "mode": "expression",
                        "context": {
                            "source_size_bytes": 90.0,
                            "tested_size_bytes": 30.0,
                        },
                    },
                    ensure_ascii=False,
                ),
            ),
        ]

        summary = store.recalculate_custom_score_for_benchmark(
            benchmark_id="bench_custom_score",
            expression="safe_div(source_size_bytes, tested_size_bytes, 0.0)",
            target_tables="phased",
        )

        self.assertIn("results", summary)
        self.assertEqual(summary["results"]["total_rows"], 2)
        self.assertEqual(summary["results"]["updated_rows"], 2)
        self.assertEqual(summary["results"]["failed_rows"], 0)
        self.assertEqual(len(store.recalc_updates), 2)
        updates_by_id = {str(item.get("id")): item for item in store.recalc_updates}
        self.assertAlmostEqual(float(updates_by_id["row_1"]["score_custom"]), 2.0)
        self.assertAlmostEqual(float(updates_by_id["row_2"]["score_custom"]), 3.0)

    def test_recalculate_custom_score_for_benchmark_validates_expression(self) -> None:
        store = _CustomScoreRecalcStore()
        with self.assertRaisesRegex(ValueError, "Некорректная expression"):
            store.recalculate_custom_score_for_benchmark(
                benchmark_id="bench_custom_score",
                expression="unknown_name + 1",
            )

    def test_clone_result_for_equivalent_ddl_reuses_metrics_from_previous_run(self) -> None:
        store = _CloneDedupStore()

        result = store.clone_result_for_equivalent_ddl(
            benchmark_strategy="sequential_phased_topn_strategy",
            benchmark_run_id=100,
            benchmark_started_at=datetime(2026, 3, 3, 10, 0, tzinfo=timezone.utc),
            benchmark_id="bench_a",
            source_database="analytics",
            source_table="events",
            variant_table="events__bench__bench_var__0002",
            variant_mode="types",
            variant_params={
                "execution_uuid": "exec-2",
                "__runtime_query_signature": "sig_q",
                "__runtime_insert_rows_limit": 100000,
                "__runtime_insert_operations_count": 10,
                "__runtime_measured_percentiles_signature": "[1,50,95,99,100]",
            },
            tested_table_ddl="CREATE TABLE bench.results (`x` UInt32) ENGINE = MergeTree ORDER BY x",
            source_table_ddl="CREATE TABLE analytics.events (`x` UInt32) ENGINE = MergeTree ORDER BY x",
            celery_task_id="task-1",
            celery_worker_hostname="worker-a",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "cloned")
        self.assertEqual(result["source_result_id"], "prev_result_id_1")
        self.assertIsNotNone(store.candidate_query_params)
        # Дедуп ищется по истории запусков, а не только в текущем run.
        self.assertNotIn("benchmark_run_id", store.candidate_query_params or {})
        self.assertIsNotNone(store.insert_select_params)


if __name__ == "__main__":
    unittest.main()
