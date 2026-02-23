import unittest
from typing import Dict, List

from benchmark_engine import (
    BenchmarkEngine,
    BenchmarkExecutionAdapter,
    InMemoryBenchmarkResultStore,
    MaxIdBenchmarkRunIdProvider,
    BenchmarkPlanner,
    BenchmarkRunner,
    BenchmarkVariantResult,
    MetadataProvider,
    TableSelector,
    VariantJob,
)
from clickhouse_ddl import TableDDL
from models import (
    BenchmarkConfig,
    BenchmarkRootConfig,
    CeleryConfig,
    ColumnRuleConfig,
    ConnectionConfig,
    IndexConfig,
    IndexRuleConfig,
    QueriesConfig,
    RulesConfig,
    TableRuleConfig,
    TestQueryConfig as QueryConfigItem,
)


EVENTS_DDL = """
CREATE TABLE analytics.events
(
    `user_id` UInt64 CODEC(Delta(8), LZ4),
    `event_time` DateTime CODEC(DoubleDelta, ZSTD(1)),
    `revenue` Nullable(Decimal(18,4)) CODEC(ZSTD(1))
)
ENGINE = MergeTree
ORDER BY (user_id, event_time)
"""

SESSIONS_DDL = """
CREATE TABLE analytics.sessions
(
    `session_id` UInt64 CODEC(Delta(8), LZ4),
    `started_at` DateTime CODEC(DoubleDelta, ZSTD(1))
)
ENGINE = MergeTree
ORDER BY (session_id, started_at)
"""


class StaticMetadataProvider(MetadataProvider):
    def __init__(self, ddl_by_db_table: Dict[str, Dict[str, str]]) -> None:
        self._tables = {
            db: {tbl: TableDDL.from_ddl(ddl) for tbl, ddl in tables.items()}
            for db, tables in ddl_by_db_table.items()
        }

    def list_databases(self) -> List[str]:
        return sorted(self._tables.keys())

    def list_tables(self, database: str) -> List[str]:
        return sorted(self._tables.get(database, {}).keys())

    def fetch_table_ddl(self, database: str, table: str) -> TableDDL:
        return self._tables[database][table].copy()


class RecordingExecutionAdapter(BenchmarkExecutionAdapter):
    def __init__(self) -> None:
        self.executed_jobs: List[VariantJob] = []

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        self.executed_jobs.append(job)
        return BenchmarkVariantResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            variant_index=job.variant_meta.global_index,
            score=1.0,
            payload={"ok": True},
        )


class SequentialScoringAdapter(BenchmarkExecutionAdapter):
    def __init__(self) -> None:
        self.executed_jobs: List[VariantJob] = []

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        self.executed_jobs.append(job)
        user_id_type = job.variant_ddl.column("user_id").type
        if job.variant_meta.mode == "types":
            # Делаем UInt32 лучшим типовым кандидатом.
            score = 10.0 if user_id_type == "UInt32" else 1.0
        else:
            score = 0.5

        return BenchmarkVariantResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            variant_index=job.variant_meta.global_index,
            score=score,
            payload={
                "stage": job.variant_meta.mode,
                "user_id_type": user_id_type,
                "indexes_count": len(job.variant_ddl.indexes),
            },
        )


class PlannerEngineRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = StaticMetadataProvider(
            {"analytics": {"events": EVENTS_DDL, "sessions": SESSIONS_DDL}}
        )
        self.connection = ConnectionConfig(
            id="prod_ch",
            dbms="clickhouse",
            credential_type="password",
            host="localhost",
            port=9000,
            login="user",
            password="pass",
        )

    def _root(self, benchmark: BenchmarkConfig, dbms: str = "clickhouse") -> BenchmarkRootConfig:
        conn = self.connection.model_copy(update={"dbms": dbms})
        return BenchmarkRootConfig(
            connections=[conn],
            benchmarks=[benchmark],
            rule_banks={},
            default_rule_banks={},
            celery=CeleryConfig(workers=9, threads_per_worker=5),
        )

    def test_table_selector_deduplicates_manual_tables(self) -> None:
        benchmark = BenchmarkConfig(
            id="bench_selector",
            connection_id="prod_ch",
            mode="types",
            databases=["analytics"],
            tables=["events", "events"],
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])
                ]
            ),
        )

        targets = TableSelector().select_targets(benchmark, self.provider)

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].database, "analytics")
        self.assertEqual(targets[0].table, "events")

    def test_planner_applies_table_level_overrides(self) -> None:
        benchmark = BenchmarkConfig(
            id="bench_overrides",
            connection_id="prod_ch",
            mode="combined",
            databases=["analytics"],
            tables=["events"],
            max_iterations=10,
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(
                        by_type="UInt64",
                        types=["UInt64", "UInt32"],
                        codecs=["CODEC(Delta(8), LZ4)"],
                    )
                ]
            ),
            table_rules=[
                TableRuleConfig(
                    database="analytics",
                    table="events",
                    mode="sequential",
                    max_iterations=2,
                    rules=RulesConfig(
                        column_rules=[
                            ColumnRuleConfig(
                                by_type="Nullable",
                                by_name="revenue",
                                types=[
                                    "Nullable(Decimal(18,4))",
                                    "Nullable(Float64)",
                                ],
                                codecs=["CODEC(ZSTD(1))"],
                            )
                        ]
                    ),
                    queries=QueriesConfig(
                        mode="manual",
                        warmup_queries=["SELECT 1 FROM {table}"],
                        test_queries=[
                            QueryConfigItem(query="SELECT sum(revenue) FROM {table}")
                        ],
                    ),
                )
            ],
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )

        table_plans = list(planner.iter_table_plans())
        self.assertEqual(len(table_plans), 1)

        plan = table_plans[0]
        self.assertEqual(plan.mode, "sequential")
        self.assertEqual(plan.max_iterations, 2)
        self.assertEqual(plan.queries.mode, "manual")
        self.assertEqual(plan.celery.workers, 9)
        self.assertEqual(plan.celery.threads_per_worker, 5)
        self.assertEqual(len(plan.rules.column_rules), 1)
        self.assertEqual(plan.rules.column_rules[0].by_type, "Nullable")

    def test_planner_prefers_benchmark_celery_over_root(self) -> None:
        benchmark = BenchmarkConfig(
            id="bench_celery_override",
            connection_id="prod_ch",
            mode="types",
            databases=["analytics"],
            tables=["events"],
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])
                ]
            ),
            celery=CeleryConfig(workers=2, threads_per_worker=1),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )

        plan = next(planner.iter_table_plans())
        self.assertEqual(plan.celery.workers, 2)
        self.assertEqual(plan.celery.threads_per_worker, 1)

    def test_planner_raises_when_no_rules_can_be_resolved(self) -> None:
        benchmark = BenchmarkConfig(
            id="bench_no_rules",
            connection_id="prod_ch",
            mode="types",
            databases=["analytics"],
            tables=["events"],
            global_rules=RulesConfig(),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark, dbms="postgres"),
            providers_by_connection_id={"prod_ch": self.provider},
        )

        with self.assertRaisesRegex(ValueError, "не найдено ни column_rules"):
            list(planner.iter_table_plans())

    def test_engine_builds_jobs_and_renders_table_placeholders(self) -> None:
        benchmark = BenchmarkConfig(
            id="bench_types",
            connection_id="prod_ch",
            mode="types",
            databases=["analytics"],
            tables=["events"],
            max_iterations=1,
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(
                        by_type="UInt64",
                        by_name="user_id",
                        types=["UInt64", "UInt32"],
                        codecs=["CODEC(Delta(8), LZ4)"],
                    )
                ]
            ),
            queries=QueriesConfig(
                mode="manual",
                warmup_queries=["SELECT 1 FROM {table}"],
                test_queries=[
                    QueryConfigItem(query="SELECT count() FROM {table}", weight=2.0)
                ],
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)

        jobs = list(engine.iter_variant_jobs())
        self.assertEqual(len(jobs), 1)

        job = jobs[0]
        self.assertEqual(job.benchmark_run_id, 1)
        self.assertEqual(job.total_variants, 1)
        self.assertEqual(job.variant_meta.global_index, 0)
        self.assertTrue(job.variant_table.startswith("events__bench__bench_types__"))
        self.assertEqual(job.variant_ddl.name, f"analytics.{job.variant_table}")
        self.assertIn(job.variant_table, job.query_plan.warmup_queries[0])
        self.assertIn(job.variant_table, job.query_plan.test_queries[0].query)
        self.assertNotIn("{table}", job.query_plan.warmup_queries[0])
        self.assertNotIn("{table}", job.query_plan.test_queries[0].query)

    def test_runner_passes_jobs_to_execution_adapter(self) -> None:
        benchmark = BenchmarkConfig(
            id="bench_run",
            connection_id="prod_ch",
            mode="types",
            databases=["analytics"],
            tables=["events"],
            max_iterations=1,
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])
                ]
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        adapter = RecordingExecutionAdapter()
        result_store = InMemoryBenchmarkResultStore()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=result_store,
        )

        run_id = runner.run()

        self.assertEqual(run_id, 1)
        self.assertEqual(len(adapter.executed_jobs), 1)
        self.assertEqual(len(result_store.records), 1)
        self.assertEqual(result_store.records[0].benchmark_run_id, 1)
        self.assertEqual(adapter.executed_jobs[0].benchmark_run_id, 1)
        self.assertEqual(
            result_store.records[0].variant_table,
            adapter.executed_jobs[0].variant_table,
        )
        self.assertEqual(result_store.records[0].score, 1.0)

    def test_runner_assigns_single_serial_run_id_per_run(self) -> None:
        benchmark = BenchmarkConfig(
            id="bench_run_id_serial",
            connection_id="prod_ch",
            mode="types",
            databases=["analytics"],
            tables=["events"],
            max_iterations=1,
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])
                ]
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        adapter = RecordingExecutionAdapter()
        result_store = InMemoryBenchmarkResultStore()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=result_store,
        )

        run1 = runner.run()
        run2 = runner.run()

        self.assertEqual(run1, 1)
        self.assertEqual(run2, 2)
        run1_rows = [r for r in result_store.records if r.benchmark_run_id == 1]
        run2_rows = [r for r in result_store.records if r.benchmark_run_id == 2]
        self.assertTrue(run1_rows)
        self.assertTrue(run2_rows)

    def test_runner_uses_max_id_provider_as_source_of_run_ids(self) -> None:
        benchmark = BenchmarkConfig(
            id="bench_run_id_from_max",
            connection_id="prod_ch",
            mode="types",
            databases=["analytics"],
            tables=["events"],
            max_iterations=1,
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])
                ]
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        adapter = RecordingExecutionAdapter()

        observed_max = {"value": 10}

        def max_id_getter() -> int:
            return observed_max["value"]

        provider = MaxIdBenchmarkRunIdProvider(max_id_getter=max_id_getter)
        result_store = InMemoryBenchmarkResultStore()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=result_store,
            run_id_provider=provider,
        )

        run1 = runner.run()
        self.assertEqual(run1, 11)
        run1_rows = [r for r in result_store.records if r.benchmark_run_id == 11]
        self.assertTrue(run1_rows)

        # Имитируем, что в БД уже появились записи для run_id=11.
        observed_max["value"] = 11
        run2 = runner.run()
        self.assertEqual(run2, 12)
        run2_rows = [r for r in result_store.records if r.benchmark_run_id == 12]
        self.assertTrue(run2_rows)

    def test_sequential_mode_runs_indexes_for_top_n_type_variants(self) -> None:
        benchmark = BenchmarkConfig(
            id="bench_sequential_topn",
            connection_id="prod_ch",
            mode="sequential",
            databases=["analytics"],
            tables=["events"],
            max_iterations=10,
            sequential_top_n=1,
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(
                        by_type="UInt64",
                        by_name="user_id",
                        types=["UInt64", "UInt32"],
                        codecs=["CODEC(Delta(8), LZ4)"],
                    )
                ],
                index_rules=[
                    IndexRuleConfig(
                        by_type="UInt32",
                        by_name="user_id",
                        indexes=[
                            IndexConfig(type="minmax", granularity=4),
                            IndexConfig(type="bloom_filter(0.01)", granularity=2),
                        ],
                    )
                ],
            ),
            queries=QueriesConfig(
                mode="manual",
                test_queries=[QueryConfigItem(query="SELECT count() FROM {table}")],
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        adapter = SequentialScoringAdapter()
        result_store = InMemoryBenchmarkResultStore()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=result_store,
        )

        run_id = runner.run()

        # Stage 1: 2 type variants (UInt64/UInt32)
        # Stage 2: top-1 (UInt32) gets 3 index variants (None + 2 indexes)
        self.assertEqual(run_id, 1)
        self.assertEqual(len(result_store.records), 5)
        self.assertEqual(len(adapter.executed_jobs), 5)
        self.assertTrue(all(r.benchmark_run_id == 1 for r in result_store.records))
        self.assertTrue(all(j.benchmark_run_id == 1 for j in adapter.executed_jobs))

        stages = [job.variant_meta.mode for job in adapter.executed_jobs]
        self.assertEqual(stages[:2], ["types", "types"])
        self.assertEqual(stages[2:], ["indexes", "indexes", "indexes"])

        # Индексный этап должен идти по лучшему type-варианту (UInt32).
        indexed_job_types = [
            job.variant_ddl.column("user_id").type
            for job in adapter.executed_jobs
            if job.variant_meta.mode == "indexes"
        ]
        self.assertEqual(indexed_job_types, ["UInt32", "UInt32", "UInt32"])

        global_indexes = [job.variant_meta.global_index for job in adapter.executed_jobs]
        self.assertEqual(global_indexes, [0, 1, 2, 3, 4])

        variant_tables = [job.variant_table for job in adapter.executed_jobs]
        self.assertEqual(len(variant_tables), len(set(variant_tables)))


if __name__ == "__main__":
    unittest.main()
