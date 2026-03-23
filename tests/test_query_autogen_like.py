import unittest
from typing import Dict, List, Sequence

from src.benchmark_engine import QueryPlanBuilder
from src.benchmark_runtime.contracts.metadata import MetadataProvider
from src.clickhouse_ddl import TableDDL
from src.fetcher import Fetcher
from src.models import QueriesConfig, TestQueryConfig as QueryConfigItem
from src.query_generator import generate_queries


_DDL = """
CREATE TABLE analytics.events
(
    `event_time` DateTime,
    `user_id` UInt64,
    `page_url` String,
    `country` LowCardinality(String)
)
ENGINE = MergeTree
ORDER BY event_time
"""


class _RecordingProvider(MetadataProvider):
    def __init__(self, tokens: Dict[str, Dict[str, str]] | None = None) -> None:
        self.calls: int = 0
        self.columns_seen: List[str] = []
        self.tokens = tokens or {}

    def list_databases(self) -> List[str]:
        return ["analytics"]

    def list_tables(self, database: str) -> List[str]:
        return ["events"]

    def fetch_table_ddl(self, database: str, table: str) -> TableDDL:
        return TableDDL.from_ddl(_DDL)

    def fetch_like_tokens(
        self,
        database: str,
        table: str,
        columns: Sequence[str],
        *,
        sample_rows_per_column: int = 20,
        min_token_length: int = 3,
        max_token_length: int = 24,
    ) -> Dict[str, Dict[str, str]]:
        del database, table, sample_rows_per_column, min_token_length, max_token_length
        self.calls += 1
        self.columns_seen = [str(col) for col in columns]
        return dict(self.tokens)


class _FailingProvider(_RecordingProvider):
    def fetch_like_tokens(
        self,
        database: str,
        table: str,
        columns: Sequence[str],
        *,
        sample_rows_per_column: int = 20,
        min_token_length: int = 3,
        max_token_length: int = 24,
    ) -> Dict[str, Dict[str, str]]:
        del database, table, columns, sample_rows_per_column, min_token_length, max_token_length
        raise RuntimeError("provider failure")


class QueryAutoLikeTests(unittest.TestCase):
    def test_generate_queries_appends_data_aware_like_pairs(self) -> None:
        table = TableDDL.from_ddl(_DDL)
        generated = generate_queries(
            table,
            measured_columns=["page_url"],
            prefer_measured_columns=True,
            like_tokens_by_column={
                "page_url": {"hit_token": "/catalog", "miss_token": "nomatch_token"},
                "unknown_col": {"hit_token": "x", "miss_token": "y"},
            },
            include_miss_queries=True,
        )
        self.assertEqual(len(generated), 2)
        sqls = [item.query for item in generated]
        self.assertTrue(any("/catalog" in sql for sql in sqls))
        self.assertTrue(any("nomatch_token" in sql for sql in sqls))

    def test_generate_queries_skips_like_when_hit_token_is_empty(self) -> None:
        table = TableDDL.from_ddl(_DDL)
        generated = generate_queries(
            table,
            measured_columns=["page_url"],
            prefer_measured_columns=True,
            like_tokens_by_column={
                "page_url": {"hit_token": "   ", "miss_token": "nomatch_token"},
            },
        )
        self.assertEqual(len(generated), 1)
        self.assertTrue(all("nomatch_token" not in item.query for item in generated))

    def test_query_plan_builder_manual_mode_does_not_call_provider(self) -> None:
        table = TableDDL.from_ddl(_DDL)
        provider = _FailingProvider()
        plan = QueryPlanBuilder().build(
            table,
            QueriesConfig(
                mode="manual",
                auto_like_on_measured_columns=True,
                auto_like_replace_default_auto_queries=True,
                test_queries=[QueryConfigItem(query="SELECT 1 FROM {table}")],
            ),
            provider=provider,
            source_database="analytics",
            source_table="events",
            measured_columns=["page_url"],
        )
        self.assertEqual(provider.calls, 0)
        self.assertEqual(len(plan.test_queries), 1)
        self.assertEqual(plan.test_queries[0].query, "SELECT 1 FROM {table}")

    def test_query_plan_builder_handles_provider_exception_with_fallback(self) -> None:
        table = TableDDL.from_ddl(_DDL)
        provider = _FailingProvider()
        plan = QueryPlanBuilder().build(
            table,
            QueriesConfig(
                mode="auto",
                auto_like_on_measured_columns=True,
                auto_like_replace_default_auto_queries=True,
            ),
            provider=provider,
            source_database="analytics",
            source_table="events",
            measured_columns=["page_url"],
        )
        sqls = [item.query for item in plan.test_queries]
        query_types = [item.query_type for item in plan.test_queries]
        self.assertEqual(len(sqls), 1)
        self.assertTrue(all("`page_url` LIKE '%%'" in sql for sql in sqls))
        self.assertEqual(query_types.count("hit"), 1)
        self.assertEqual(query_types.count("miss"), 0)

    def test_query_plan_builder_passes_only_string_measured_columns(self) -> None:
        table = TableDDL.from_ddl(_DDL)
        provider = _RecordingProvider()
        QueryPlanBuilder().build(
            table,
            QueriesConfig(
                mode="auto",
                auto_like_on_measured_columns=True,
            ),
            provider=provider,
            source_database="analytics",
            source_table="events",
            measured_columns=["user_id", "country", "page_url", "country", "unknown"],
        )
        self.assertEqual(provider.columns_seen, ["country", "page_url"])

    def test_query_plan_builder_replace_default_auto_queries_when_tokens_exist(self) -> None:
        table = TableDDL.from_ddl(_DDL)
        provider = _RecordingProvider(
            tokens={"page_url": {"hit_token": "/catalog", "miss_token": "zzzzz_no"}}
        )
        plan = QueryPlanBuilder().build(
            table,
            QueriesConfig(
                mode="auto",
                auto_like_on_measured_columns=True,
                auto_like_replace_default_auto_queries=True,
                auto_include_miss_queries=True,
            ),
            provider=provider,
            source_database="analytics",
            source_table="events",
            measured_columns=["page_url"],
        )
        sqls = [item.query for item in plan.test_queries]
        self.assertEqual(len(sqls), 2)
        self.assertTrue(all("LIKE concat('%'," in sql for sql in sqls))

    def test_query_plan_builder_auto_with_manual_keeps_manual_queries(self) -> None:
        table = TableDDL.from_ddl(_DDL)
        provider = _RecordingProvider(
            tokens={"page_url": {"hit_token": "/catalog", "miss_token": "zzzzz_no"}}
        )
        manual_sql = "SELECT 42 FROM {table}"
        plan = QueryPlanBuilder().build(
            table,
            QueriesConfig(
                mode="auto_with_manual",
                auto_like_on_measured_columns=True,
                auto_like_replace_default_auto_queries=True,
                auto_include_miss_queries=True,
                test_queries=[QueryConfigItem(query=manual_sql)],
            ),
            provider=provider,
            source_database="analytics",
            source_table="events",
            measured_columns=["page_url"],
        )
        sqls = [item.query for item in plan.test_queries]
        self.assertIn(manual_sql, sqls)
        self.assertEqual(len(sqls), 3)

    def test_generate_queries_prefers_measured_columns_and_string_like(self) -> None:
        table = TableDDL.from_ddl(_DDL)
        generated = generate_queries(
            table,
            measured_columns=["user_id", "page_url", "country"],
            prefer_measured_columns=True,
            like_tokens_by_column={
                "page_url": {"hit_token": "/catalog", "miss_token": "bench_nomatch_url"},
                "country": {"hit_token": "RU", "miss_token": "bench_nomatch_country"},
            },
            range_tokens_by_column={
                "user_id": {"min": "10"},
            },
        )
        sqls = [item.query for item in generated]
        self.assertTrue(any("`user_id` >" in sql for sql in sqls))
        self.assertTrue(any("`page_url` LIKE concat('%'," in sql for sql in sqls))
        self.assertTrue(any("`country` LIKE concat('%'," in sql for sql in sqls))

    def test_generate_queries_builds_hit_and_miss_per_measured_column(self) -> None:
        table = TableDDL.from_ddl(_DDL)
        generated = generate_queries(
            table,
            measured_columns=["user_id", "page_url"],
            prefer_measured_columns=True,
            like_tokens_by_column={
                "page_url": {
                    "hit_token": "/catalog",
                    "miss_token": "bench_nomatch_page_url",
                }
            },
            range_tokens_by_column={
                "user_id": {"min": "10"},
            },
            include_miss_queries=True,
        )
        sqls = [item.query for item in generated]
        query_types = [item.query_type for item in generated]
        # user_id: hit + miss via range
        self.assertTrue(any("`user_id` >" in sql for sql in sqls))
        self.assertTrue(any("`user_id` <" in sql for sql in sqls))
        # page_url: hit + miss, и оба сценария содержат LIKE '%%'
        self.assertTrue(any("`page_url` LIKE '%%'" in sql and "/catalog" in sql for sql in sqls))
        self.assertTrue(
            any(
                "`page_url` LIKE '%%'" in sql and "bench_nomatch_page_url" in sql
                for sql in sqls
            )
        )
        self.assertEqual(query_types.count("hit"), 2)
        self.assertEqual(query_types.count("miss"), 2)

    def test_generate_queries_uses_datetime_parse_cast_for_range_literals(self) -> None:
        table = TableDDL.from_ddl(_DDL)
        generated = generate_queries(
            table,
            measured_columns=["event_time"],
            prefer_measured_columns=True,
            range_tokens_by_column={
                "event_time": {"min": "2025-01-27 13:51:49+03:00"},
            },
            include_miss_queries=True,
        )
        sqls = [item.query for item in generated]
        self.assertEqual(len(sqls), 2)
        self.assertTrue(all("parseDateTimeBestEffort(" in sql for sql in sqls))
        self.assertTrue(all("AS DateTime" in sql for sql in sqls))
        self.assertTrue(all("+03:00" in sql for sql in sqls))

    def test_generate_queries_uses_typed_cast_for_numeric_range_literals(self) -> None:
        table = TableDDL.from_ddl(_DDL)
        generated = generate_queries(
            table,
            measured_columns=["user_id"],
            prefer_measured_columns=True,
            range_tokens_by_column={
                "user_id": {"min": "10"},
            },
            include_miss_queries=True,
        )
        sqls = [item.query for item in generated]
        self.assertEqual(len(sqls), 2)
        self.assertTrue(all("CAST('10' AS UInt64)" in sql for sql in sqls))

    def test_generate_queries_applies_default_limit_10_to_auto_selects(self) -> None:
        table = TableDDL.from_ddl(_DDL)
        generated = generate_queries(table, prefer_measured_columns=True)
        sqls = [item.query for item in generated]
        self.assertTrue(sqls)
        self.assertTrue(all("LIMIT 10" in sql for sql in sqls))

    def test_generate_queries_applies_custom_limit_from_config(self) -> None:
        table = TableDDL.from_ddl(_DDL)
        builder = QueryPlanBuilder()
        plan = builder.build(
            table,
            QueriesConfig(
                mode="auto",
                auto_select_limit=7,
            ),
        )
        sqls = [item.query for item in plan.test_queries]
        self.assertTrue(sqls)
        self.assertTrue(all("LIMIT 7" in sql for sql in sqls))

    def test_generate_queries_auto_base_has_no_group_by_queries(self) -> None:
        table = TableDDL.from_ddl(_DDL)
        generated = generate_queries(table, prefer_measured_columns=True)
        sqls = [item.query.lower() for item in generated]
        self.assertTrue(sqls)
        self.assertTrue(all("group by" not in sql for sql in sqls))


class FetcherLikeTokensTests(unittest.TestCase):
    def test_fetch_like_tokens_returns_hit_and_miss(self) -> None:
        fetcher = Fetcher.__new__(Fetcher)

        def _execute(query: str, params: Dict[str, object] | None = None):
            if "WHERE `page_url` IS NOT NULL" in query:
                return [("/catalog/item/123",)]
            if "WHERE `page_url` LIKE" in query:
                pattern = str((params or {}).get("pattern", ""))
                if "_1%" in pattern:
                    return [(1,)]
                return []
            raise AssertionError(f"unexpected query: {query}")

        fetcher._execute = _execute  # type: ignore[method-assign]
        result = fetcher.fetch_like_tokens(
            "analytics",
            "events",
            ["page_url"],
            sample_rows_per_column=5,
            min_token_length=3,
            max_token_length=24,
        )
        self.assertIn("page_url", result)
        self.assertTrue(result["page_url"]["hit_token"])
        self.assertTrue(result["page_url"]["miss_token"].startswith("bench_nomatch_"))
        self.assertNotEqual(result["page_url"]["miss_token"], result["page_url"]["hit_token"])

    def test_fetch_like_tokens_skips_columns_without_valid_tokens(self) -> None:
        fetcher = Fetcher.__new__(Fetcher)

        def _execute(query: str, params: Dict[str, object] | None = None):
            del params
            if "WHERE `page_url` IS NOT NULL" in query:
                return [(None,), ("",), ("ab",)]
            if "LIKE" in query:
                return []
            raise AssertionError(f"unexpected query: {query}")

        fetcher._execute = _execute  # type: ignore[method-assign]
        result = fetcher.fetch_like_tokens(
            "analytics",
            "events",
            ["page_url"],
            min_token_length=3,
        )
        self.assertEqual(result, {})

    def test_fetch_like_tokens_deduplicates_input_columns(self) -> None:
        fetcher = Fetcher.__new__(Fetcher)
        sample_calls: List[str] = []

        def _execute(query: str, params: Dict[str, object] | None = None):
            del params
            if "WHERE `page_url` IS NOT NULL" in query:
                sample_calls.append("page_url")
                return [("/catalog/item/123",)]
            if "WHERE `page_url` LIKE" in query:
                return []
            raise AssertionError(f"unexpected query: {query}")

        fetcher._execute = _execute  # type: ignore[method-assign]
        result = fetcher.fetch_like_tokens(
            "analytics",
            "events",
            ["page_url", "page_url", " "],
        )
        self.assertIn("page_url", result)
        self.assertEqual(sample_calls, ["page_url"])

    def test_fetch_like_tokens_continues_when_column_sampling_fails(self) -> None:
        fetcher = Fetcher.__new__(Fetcher)

        def _execute(query: str, params: Dict[str, object] | None = None):
            del params
            if "WHERE `page_url` IS NOT NULL" in query:
                raise RuntimeError("sample failed")
            if "WHERE `country` IS NOT NULL" in query:
                return [("RUS",)]
            if "WHERE `country` LIKE" in query:
                return []
            raise AssertionError(f"unexpected query: {query}")

        fetcher._execute = _execute  # type: ignore[method-assign]
        result = fetcher.fetch_like_tokens(
            "analytics",
            "events",
            ["page_url", "country"],
        )
        self.assertNotIn("page_url", result)
        self.assertIn("country", result)


if __name__ == "__main__":
    unittest.main()
