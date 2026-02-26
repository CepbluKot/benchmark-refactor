import unittest
from datetime import datetime, timezone
from typing import Dict, List

import src.benchmark_runtime.implementations.table_strategy.sequential_topn as sequential_topn_strategy_impl
from src.benchmark_engine import (
    BenchmarkEngine,
    BenchmarkExecutionAdapter,
    BenchmarkResultStore,
    InMemoryBenchmarkResultStore,
    MaxIdBenchmarkRunIdProvider,
    BenchmarkPlanner,
    BenchmarkRunner,
    BenchmarkVariantResult,
    TableExecutionStrategy,
    FetcherMetadataProvider,
    MetadataProvider,
    QueryPlanBuilder,
    SourceBenchmarkJob,
    SourceBenchmarkResult,
    TableBenchmarkPlan,
    TopTypeVariant,
    TableSelector,
    VariantJob,
)
from src.clickhouse_ddl import TableDDL
from src.models import (
    BenchmarkConfig,
    BenchmarkRootConfig,
    CeleryConfig,
    CodecRuleConfig,
    ColumnRuleConfig,
    ConnectionConfig,
    InsertRowsLimitsConfig,
    IndexConfig,
    IndexRuleConfig,
    OrderByRulesConfig,
    QueriesConfig,
    RuleBankConfig,
    RulesConfig,
    TableRuleConfig,
    TestQueryConfig as QueryConfigItem,
)
from src.resolver import ResolvedRules


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
    def __init__(
        self,
        ddl_by_db_table: Dict[str, Dict[str, str]],
        column_sizes_by_db_table: Dict[str, Dict[str, Dict[str, int]]] | None = None,
    ) -> None:
        """Готовит in-memory DDL и размеры колонок для тестов планировщика."""
        self._tables = {
            db: {tbl: TableDDL.from_ddl(ddl) for tbl, ddl in tables.items()}
            for db, tables in ddl_by_db_table.items()
        }
        self._column_sizes = column_sizes_by_db_table or {}

    def list_databases(self) -> List[str]:
        """Возвращает список доступных БД."""
        return sorted(self._tables.keys())

    def list_tables(self, database: str) -> List[str]:
        """Возвращает список таблиц в указанной БД."""
        return sorted(self._tables.get(database, {}).keys())

    def fetch_table_ddl(self, database: str, table: str) -> TableDDL:
        """Возвращает копию DDL заданной таблицы."""
        return self._tables[database][table].copy()

    def fetch_column_sizes(self, database: str, table: str) -> Dict[str, int]:
        """Возвращает размеры колонок для авто-ранжирования порядка колонок."""
        return dict(self._column_sizes.get(database, {}).get(table, {}))


class RecordingExecutionAdapter(BenchmarkExecutionAdapter):
    def __init__(self) -> None:
        """Инициализирует адаптер, который записывает все вызовы в память."""
        self.executed_jobs: List[VariantJob] = []
        self.source_jobs: List[SourceBenchmarkJob] = []
        self.source_results: List[SourceBenchmarkResult] = []
        self.call_sequence: List[str] = []
        self._store: BenchmarkResultStore | None = None

    def bind_result_store(self, result_store: BenchmarkResultStore | None) -> None:
        """Привязывает store для тестового сохранения variant-результатов."""
        self._store = result_store

    def execute_source_benchmark(self, job: SourceBenchmarkJob) -> SourceBenchmarkResult:
        """Фиксирует baseline-вызов и возвращает синтетический baseline-результат."""
        self.call_sequence.append("source")
        self.source_jobs.append(job)
        result = SourceBenchmarkResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            source_table_ddl=job.source_table_ddl.to_ddl(),
            score=1.0,
            metrics={"status": "baseline_done"},
        )
        self.source_results.append(result)
        return result

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        """Фиксирует variant-вызов и возвращает синтетический score."""
        self.call_sequence.append("variant")
        self.executed_jobs.append(job)
        result = BenchmarkVariantResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            variant_mode=job.variant_meta.mode,
            score=1.0,
        )
        if self._store is not None:
            self._store.store_result(job, result)
        return result


class SequentialScoringAdapter(BenchmarkExecutionAdapter):
    def __init__(self) -> None:
        """Инициализирует адаптер со скорингом для тестов sequential top-N."""
        self.executed_jobs: List[VariantJob] = []
        self.source_jobs: List[SourceBenchmarkJob] = []
        self.source_results: List[SourceBenchmarkResult] = []
        self.call_sequence: List[str] = []
        self._store: BenchmarkResultStore | None = None

    def bind_result_store(self, result_store: BenchmarkResultStore | None) -> None:
        """Привязывает store для записи синтетических результатов."""
        self._store = result_store

    def execute_source_benchmark(self, job: SourceBenchmarkJob) -> SourceBenchmarkResult:
        """Возвращает baseline-результат для дальнейшей прокидки в variant jobs."""
        self.call_sequence.append("source")
        self.source_jobs.append(job)
        result = SourceBenchmarkResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            source_table_ddl=job.source_table_ddl.to_ddl(),
            score=1.0,
            metrics={"status": "baseline_done"},
        )
        self.source_results.append(result)
        return result

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        """Считает синтетический score для type/indexes этапов и пишет в store."""
        self.call_sequence.append("variant")
        self.executed_jobs.append(job)
        user_id_type = job.variant_ddl.column("user_id").type
        if job.variant_meta.mode == "types":
            # Делаем UInt32 лучшим типовым кандидатом.
            score = 10.0 if user_id_type == "UInt32" else 1.0
        else:
            score = 0.5

        result = BenchmarkVariantResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            variant_mode=job.variant_meta.mode,
            score=score,
            tested_table_indexes_sizes=str(len(job.variant_ddl.indexes)),
        )
        if self._store is not None:
            self._store.store_result(job, result)
        return result


class SequentialPhasedScoringAdapter(BenchmarkExecutionAdapter):
    """Синтетический adapter для теста multi-phase стратегии."""

    def __init__(self) -> None:
        self.executed_jobs: List[VariantJob] = []
        self.source_jobs: List[SourceBenchmarkJob] = []
        self.source_results: List[SourceBenchmarkResult] = []
        self._store: BenchmarkResultStore | None = None

    def bind_result_store(self, result_store: BenchmarkResultStore | None) -> None:
        self._store = result_store

    def execute_source_benchmark(self, job: SourceBenchmarkJob) -> SourceBenchmarkResult:
        self.source_jobs.append(job)
        result = SourceBenchmarkResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            source_table_ddl=job.source_table_ddl.to_ddl(),
            score=1.0,
            metrics={"status": "baseline_done"},
        )
        self.source_results.append(result)
        return result

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        self.executed_jobs.append(job)
        user_id_type = job.variant_ddl.column("user_id").type
        mode = job.variant_meta.mode
        order_by = job.variant_ddl.order_by or ""
        codecs = tuple((column.name, column.codec) for column in job.variant_ddl.columns)
        score = 0.1

        if mode == "order_by":
            score = 5.0 if "event_time" in order_by else 1.0
        elif mode == "types":
            score = 10.0 if user_id_type == "UInt32" else 2.0
        elif mode == "types_validation":
            score = 15.0 if user_id_type == "UInt32" else 3.0
        elif mode == "codecs":
            score = 7.0 if any(codec == "CODEC(ZSTD(1))" for _, codec in codecs) else 4.0
        elif mode == "codecs_validation":
            score = 20.0 if any(codec == "CODEC(ZSTD(1))" for _, codec in codecs) else 5.0
        elif mode == "indexes":
            score = 9.0 if len(job.variant_ddl.indexes) > 0 else 1.0
        elif mode == "indexes_validation":
            score = 25.0 if len(job.variant_ddl.indexes) > 0 else 2.0
        elif mode == "final_validation":
            score = 30.0 if len(job.variant_ddl.indexes) > 0 else 6.0

        result = BenchmarkVariantResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            variant_mode=mode,
            score=score,
            tested_table_indexes_sizes=str(len(job.variant_ddl.indexes)),
        )
        if self._store is not None:
            self._store.store_result(job, result)
        return result


class SkippingSourceExecutionAdapter(BenchmarkExecutionAdapter):
    """Адаптер, который помечает baseline как skipped (source table empty)."""

    def __init__(self) -> None:
        self.executed_jobs: List[VariantJob] = []
        self.source_jobs: List[SourceBenchmarkJob] = []

    def execute_source_benchmark(self, job: SourceBenchmarkJob) -> SourceBenchmarkResult:
        self.source_jobs.append(job)
        return SourceBenchmarkResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            source_table_ddl=job.source_table_ddl.to_ddl(),
            score=None,
            metrics={
                "status": "skipped",
                "skip_reason": "source_table_empty",
                "total_n_rows_in_source_table": 0,
            },
        )

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        self.executed_jobs.append(job)
        raise AssertionError("variant jobs не должны исполняться, если baseline skipped")


class AsyncSelfPersistingSequentialAdapter(BenchmarkExecutionAdapter):
    """
    Имитирует async execution:
    - launcher только отправляет задания;
    - реальные результаты сразу пишет self-провайдер (как будто воркер).
    """

    def __init__(self, store: BenchmarkResultStore) -> None:
        """Сохраняет ссылку на store, который имитирует внешнее хранилище воркера."""
        self._store = store
        self.executed_jobs: List[VariantJob] = []

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        """Имитирует dispatch и немедленную запись результата со стороны воркера."""
        self.executed_jobs.append(job)
        user_id_type = job.variant_ddl.column("user_id").type
        if job.variant_meta.mode == "types":
            score = 10.0 if user_id_type == "UInt32" else 1.0
        else:
            score = 0.5

        worker_result = BenchmarkVariantResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            variant_mode=job.variant_meta.mode,
            score=score,
            extra_json='{"persisted_by":"worker"}',
        )
        # Эмулируем запись из воркера во внешнее хранилище.
        self._store.store_result(job, worker_result)

        # Возвращаем подтверждение отправки инициатору запуска.
        return BenchmarkVariantResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            score=None,
            variant_mode=job.variant_meta.mode,
            extra_json='{"status":"dispatched"}',
        )


class AsyncDispatchOnlyAdapter(BenchmarkExecutionAdapter):
    """Имитирует async dispatch без сохранения на стороне runner/воркера."""

    def __init__(self) -> None:
        """Инициализирует коллекцию отправленных jobs."""
        self.executed_jobs: List[VariantJob] = []

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        """Возвращает ответ о dispatch без фактического выполнения."""
        self.executed_jobs.append(job)
        return BenchmarkVariantResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            score=None,
            variant_mode=job.variant_meta.mode,
            extra_json='{"status":"dispatched"}',
        )


class RecordingTableExecutionStrategy(TableExecutionStrategy):
    """Стратегия выполнения таблицы, которая только фиксирует факт вызова."""

    def __init__(self) -> None:
        """Хранит историю вызовов стратегии."""
        self.calls: List[tuple[str, str, int]] = []

    def execute_table(
        self,
        runner,
        table_plan,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
    ) -> None:
        """Записывает факт вызова без запуска variant jobs."""
        del runner, benchmark_started_at
        self.calls.append((table_plan.benchmark_id, table_plan.table, benchmark_run_id))


class NoTopVariantsResultStore(BenchmarkResultStore):
    """Хранилище, которое сохраняет stage1, но всегда возвращает пустой top-N."""

    def __init__(self) -> None:
        """Создаёт in-memory список результатов для stage1."""
        self.records: List[BenchmarkVariantResult] = []

    def store_result(self, job: VariantJob, result: BenchmarkVariantResult) -> None:
        """Сохраняет результат в локальный список."""
        self.records.append(result)

    def get_top_type_variants(
        self,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        top_n: int,
    ) -> List[TopTypeVariant]:
        """Всегда возвращает пустой список top-N (для проверки timeout-пути)."""
        return []


class PlannerEngineRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        """Готовит общий metadata provider и connection для тестов."""
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
        """Собирает минимальный корневой конфиг для одного benchmark."""
        conn = self.connection.model_copy(update={"dbms": dbms})
        return BenchmarkRootConfig(
            connections=[conn],
            benchmarks=[benchmark],
            rule_banks={},
            default_rule_banks={},
            celery=CeleryConfig(workers=9, threads_per_worker=5),
        )

    def test_table_selector_deduplicates_manual_tables(self) -> None:
        """Проверяет, что table selector deduplicates manual tables."""
        benchmark = BenchmarkConfig(
            id="bench_selector",
            connection_id="prod_ch",
            strategy="types_strategy",
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
        """Проверяет, что planner applies table level overrides."""
        benchmark = BenchmarkConfig(
            id="bench_overrides",
            connection_id="prod_ch",
            strategy="combined_strategy",
            scoring={
                "mode": "expression",
                "expression": "1.5",
            },
            databases=["analytics"],
            tables=["events"],
            test_database="bench_global",
            max_iterations=10,
            sequential_top_n_limits=InsertRowsLimitsConfig(
                order_by=4,
                types=3,
                codecs=2,
                indexes=1,
            ),
            max_winners_per_parent_limits=InsertRowsLimitsConfig(
                types=2,
                codecs=2,
                indexes=1,
            ),
            max_benchmarks_limits=InsertRowsLimitsConfig(
                types=40,
                indexes=30,
                sequential=20,
            ),
            insert_rows_limit=1_000_000,
            source_insert_rows_limit=600_000,
            index_granularity_values=[8192, 16384],
            source_insert_rows_limits=InsertRowsLimitsConfig(sequential=500_000),
            insert_rows_limits=InsertRowsLimitsConfig(
                types=400_000,
                indexes=200_000,
                combined=800_000,
            ),
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
                    test_database="bench_events",
                    strategy="sequential_topn_strategy",
                    max_iterations=2,
                    sequential_top_n_limits=InsertRowsLimitsConfig(
                        types=2,
                        indexes=1,
                    ),
                    max_winners_per_parent_limits=InsertRowsLimitsConfig(
                        types=3,
                        codecs=1,
                    ),
                    max_benchmarks_limits=InsertRowsLimitsConfig(
                        types=5,
                        indexes=6,
                    ),
                    insert_rows_limit=25_000,
                    source_insert_rows_limit=120_000,
                    index_granularity_values=[4096, 8192, 4096],
                    source_insert_rows_limits=InsertRowsLimitsConfig(sequential=90_000),
                    insert_rows_limits=InsertRowsLimitsConfig(
                        indexes=50_000,
                        sequential=70_000,
                    ),
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
                        test_queries=[
                            QueryConfigItem(
                                query="SELECT sum(revenue) FROM {table}",
                                warmup_queries=["SELECT 1 FROM {table}"],
                            )
                        ],
                    ),
                    scoring={
                        "mode": "expression",
                        "expression": "2.5",
                    },
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
        self.assertEqual(plan.test_database, "bench_events")
        self.assertEqual(plan.max_iterations, 2)
        self.assertIsNotNone(plan.sequential_top_n_limits)
        self.assertEqual(plan.sequential_top_n_limits.for_mode("order_by"), 4)
        self.assertEqual(plan.sequential_top_n_limits.for_mode("types"), 2)
        self.assertEqual(plan.sequential_top_n_limits.for_mode("codecs"), 2)
        self.assertEqual(plan.sequential_top_n_limits.for_mode("indexes"), 1)
        self.assertIsNotNone(plan.max_winners_per_parent_limits)
        self.assertEqual(plan.max_winners_per_parent_limits.for_mode("types"), 3)
        self.assertEqual(plan.max_winners_per_parent_limits.for_mode("codecs"), 1)
        self.assertEqual(plan.max_winners_per_parent_limits.for_mode("indexes"), 1)
        self.assertIsNotNone(plan.max_benchmarks_limits)
        self.assertEqual(plan.max_benchmarks_limits.types, 5)
        self.assertEqual(plan.max_benchmarks_limits.indexes, 6)
        self.assertEqual(plan.max_benchmarks_limits.sequential, 20)
        self.assertEqual(plan.insert_rows_limit, 25_000)
        self.assertEqual(plan.source_insert_rows_limit, 120_000)
        self.assertIsNotNone(plan.source_insert_rows_limits)
        self.assertEqual(plan.source_insert_rows_limits.sequential, 90_000)
        self.assertIsNotNone(plan.insert_rows_limits)
        self.assertEqual(plan.insert_rows_limits.types, 400_000)
        self.assertEqual(plan.insert_rows_limits.indexes, 50_000)
        self.assertEqual(plan.insert_rows_limits.combined, 800_000)
        self.assertEqual(plan.insert_rows_limits.sequential, 70_000)
        self.assertEqual(plan.index_granularity_values, [4096, 8192])
        self.assertEqual(plan.scoring.mode, "expression")
        self.assertEqual(plan.scoring.expression, "2.5")
        self.assertEqual(plan.queries.mode, "manual")
        self.assertEqual(plan.celery.workers, 9)
        self.assertEqual(plan.celery.threads_per_worker, 5)

    def test_planner_takes_order_by_rules_from_resolved_rules(self) -> None:
        """Проверяет, что planner прокидывает order_by_rules из rules-блока."""
        benchmark = BenchmarkConfig(
            id="bench_order_by_rules_from_rules",
            connection_id="prod_ch",
            strategy="sequential_phased_topn_strategy",
            databases=["analytics"],
            tables=["events"],
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(by_type="UInt64", by_name="user_id", types=["UInt64"])
                ],
                codec_rules=[
                    CodecRuleConfig(
                        by_type="UInt64",
                        by_name="user_id",
                        codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"],
                    )
                ],
                order_by_rules=OrderByRulesConfig(
                    first_column="event_time",
                    candidates=["user_id", "revenue"],
                    auto_generate_candidates=False,
                ),
            ),
            queries=QueriesConfig(
                mode="manual",
                test_queries=[
                    QueryConfigItem(query="SELECT count() FROM {table} WHERE user_id > 0")
                ],
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )

        plans = list(planner.iter_table_plans())
        self.assertEqual(len(plans), 1)
        plan = plans[0]
        self.assertEqual(plan.order_by_first, "event_time")
        self.assertEqual(plan.order_by_candidates, ["user_id", "revenue"])
        self.assertFalse(plan.order_by_auto_generate_candidates)
        self.assertEqual(len(plan.rules.column_rules), 1)
        self.assertEqual(
            plan.rules.column_rules[0].alternatives.codecs,
            ["CODEC(LZ4)", "CODEC(ZSTD(1))"],
        )

    def test_planner_applies_rule_modes_from_benchmark(self) -> None:
        """Проверяет, что planner applies rule modes from benchmark."""
        benchmark = BenchmarkConfig(
            id="bench_rule_modes",
            connection_id="prod_ch",
            strategy="types_strategy",
            databases=["analytics"],
            tables=["events"],
            column_rules_mode="global_bank_with_inline_priority",
            index_rules_mode="global_bank_only",
            global_rules=RulesConfig(rule_bank="bank_a"),
            table_rules=[
                TableRuleConfig(
                    database="analytics",
                    table="events",
                    rules=RulesConfig(
                        column_rules=[
                            ColumnRuleConfig(
                                by_type="DateTime",
                                codecs=["CODEC(DoubleDelta, ZSTD(3))"],
                            )
                        ],
                        index_rules=[
                            IndexRuleConfig(
                                by_type="DateTime",
                                indexes=[IndexConfig(type="minmax", granularity=8)],
                            )
                        ],
                    ),
                )
            ],
        )
        root = BenchmarkRootConfig(
            connections=[self.connection],
            benchmarks=[benchmark],
            rule_banks={
                "bank_a": RuleBankConfig(
                    column_rules=[
                        ColumnRuleConfig(
                            by_type="UInt64",
                            types=["UInt64", "UInt32"],
                        )
                    ],
                    index_rules=[
                        IndexRuleConfig(
                            by_type="UInt64",
                            indexes=[IndexConfig(type="minmax", granularity=4)],
                        )
                    ],
                )
            },
            default_rule_banks={},
            celery=CeleryConfig(workers=9, threads_per_worker=5),
        )
        planner = BenchmarkPlanner(
            config=root,
            providers_by_connection_id={"prod_ch": self.provider},
        )

        plan = next(planner.iter_table_plans())
        self.assertEqual([rule.by_type for rule in plan.rules.column_rules], ["DateTime", "UInt64"])
        self.assertEqual([rule.by_type for rule in plan.rules.index_rules], ["UInt64"])

    def test_planner_raises_when_no_rules_can_be_resolved(self) -> None:
        """Проверяет, что planner raises when no rules can be resolved."""
        benchmark = BenchmarkConfig(
            id="bench_no_rules",
            connection_id="prod_ch",
            strategy="types_strategy",
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

    def test_planner_provider_for_connection_raises_for_missing_provider(self) -> None:
        """Проверяет, что planner provider for connection raises for missing provider."""
        benchmark = BenchmarkConfig(
            id="bench_missing_provider",
            connection_id="prod_ch",
            strategy="types_strategy",
            databases=["analytics"],
            tables=["events"],
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])
                ]
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={},
        )

        with self.assertRaisesRegex(ValueError, "не зарегистрирован"):
            planner.provider_for_connection("prod_ch")

    def test_planner_benchmark_filter_keeps_only_selected_ids(self) -> None:
        """Проверяет, что planner benchmark filter keeps only selected ids."""
        common_rules = RulesConfig(
            column_rules=[ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])]
        )
        bench_a = BenchmarkConfig(
            id="bench_a",
            connection_id="prod_ch",
            strategy="types_strategy",
            databases=["analytics"],
            tables=["events"],
            global_rules=common_rules,
        )
        bench_b = BenchmarkConfig(
            id="bench_b",
            connection_id="prod_ch",
            strategy="types_strategy",
            databases=["analytics"],
            tables=["sessions"],
            global_rules=common_rules,
        )
        root = BenchmarkRootConfig(
            connections=[self.connection],
            benchmarks=[bench_a, bench_b],
            rule_banks={},
            default_rule_banks={},
            celery=CeleryConfig(workers=1, threads_per_worker=1),
        )
        planner = BenchmarkPlanner(
            config=root,
            providers_by_connection_id={"prod_ch": self.provider},
        )

        plans = list(planner.iter_table_plans(benchmark_ids=["bench_b"]))
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].benchmark_id, "bench_b")
        self.assertEqual(plans[0].table, "sessions")

    def test_engine_builds_jobs_and_renders_table_placeholders(self) -> None:
        """Проверяет, что engine builds jobs and renders table placeholders."""
        benchmark = BenchmarkConfig(
            id="bench_types",
            connection_id="prod_ch",
            strategy="types_strategy",
            scoring={
                "mode": "expression",
                "expression": "3.14",
            },
            databases=["analytics"],
            tables=["events"],
            max_iterations=1,
            insert_rows_limit=777,
            insert_rows_limits=InsertRowsLimitsConfig(types=123),
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
                test_queries=[
                    QueryConfigItem(
                        query="SELECT count() FROM {table} /* bench={benchmark_id} */",
                        select_operations_count=2,
                        warmup_queries=["SELECT 1 FROM {table} /* warm={benchmark_id} */"],
                    )
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
        self.assertIsNotNone(job.benchmark_started_at)
        self.assertEqual(job.benchmark_started_at.tzinfo, timezone.utc)
        self.assertEqual(job.total_variants, 1)
        self.assertEqual(job.variant_meta.global_index, 0)
        self.assertEqual(job.insert_rows_limit, 123)
        self.assertEqual(job.scoring.mode, "expression")
        self.assertEqual(job.scoring.expression, "3.14")
        self.assertEqual(job.variant_database, "analytics")
        self.assertTrue(job.variant_table.startswith("events__bench__bench_types__"))
        self.assertEqual(job.variant_ddl.name, f"analytics.{job.variant_table}")
        self.assertIn(job.variant_table, job.query_plan.test_queries[0].warmup_queries[0])
        self.assertIn(job.variant_table, job.query_plan.test_queries[0].query)
        self.assertIn("bench_types", job.query_plan.test_queries[0].query)
        self.assertIn("bench_types", job.query_plan.test_queries[0].warmup_queries[0])
        self.assertNotIn("{table}", job.query_plan.test_queries[0].warmup_queries[0])
        self.assertNotIn("{table}", job.query_plan.test_queries[0].query)
        self.assertNotIn("{benchmark_id}", job.query_plan.test_queries[0].warmup_queries[0])
        self.assertNotIn("{benchmark_id}", job.query_plan.test_queries[0].query)

    def test_engine_source_benchmark_job_prefers_source_insert_rows_limit(self) -> None:
        """Проверяет, что source baseline использует отдельный source_insert_rows_limit."""
        benchmark = BenchmarkConfig(
            id="bench_source_insert_limit",
            connection_id="prod_ch",
            strategy="sequential_topn_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=1,
            insert_rows_limit=777,
            source_insert_rows_limit=333,
            insert_rows_limits=InsertRowsLimitsConfig(sequential=555),
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(
                        by_type="UInt64",
                        by_name="user_id",
                        types=["UInt64", "UInt32"],
                    )
                ],
                index_rules=[
                    IndexRuleConfig(
                        by_type="UInt32",
                        by_name="user_id",
                        indexes=[IndexConfig(type="minmax", granularity=4)],
                    )
                ],
            ),
            queries=QueriesConfig(
                mode="manual",
                test_queries=[QueryConfigItem(query="SELECT count() FROM {table}", select_operations_count=1)],
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        table_plan = next(engine.iter_table_plans())
        source_job = engine.build_source_benchmark_job(
            table_plan=table_plan,
            benchmark_run_id=1,
            benchmark_started_at=datetime(2026, 2, 25, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(source_job.insert_rows_limit, 333)

    def test_engine_source_benchmark_job_prefers_source_insert_rows_limits_by_mode(self) -> None:
        """Проверяет приоритет source_insert_rows_per_operation_limits для baseline."""
        benchmark = BenchmarkConfig(
            id="bench_source_insert_limits_by_mode",
            connection_id="prod_ch",
            strategy="sequential_topn_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=1,
            insert_rows_limit=777,
            insert_rows_limits=InsertRowsLimitsConfig(sequential=555),
            source_insert_rows_limits=InsertRowsLimitsConfig(sequential=444),
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(
                        by_type="UInt64",
                        by_name="user_id",
                        types=["UInt64", "UInt32"],
                    )
                ],
                index_rules=[
                    IndexRuleConfig(
                        by_type="UInt32",
                        by_name="user_id",
                        indexes=[IndexConfig(type="minmax", granularity=4)],
                    )
                ],
            ),
            queries=QueriesConfig(
                mode="manual",
                test_queries=[QueryConfigItem(query="SELECT count() FROM {table}", select_operations_count=1)],
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        table_plan = next(engine.iter_table_plans())
        source_job = engine.build_source_benchmark_job(
            table_plan=table_plan,
            benchmark_run_id=1,
            benchmark_started_at=datetime(2026, 2, 25, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(source_job.insert_rows_limit, 444)

    def test_engine_source_benchmark_job_falls_back_to_standard_insert_limits(self) -> None:
        """Проверяет fallback baseline-лимита к insert_rows_limits/insert_rows_limit."""
        benchmark = BenchmarkConfig(
            id="bench_source_insert_limit_fallback",
            connection_id="prod_ch",
            strategy="sequential_topn_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=1,
            insert_rows_limit=777,
            insert_rows_limits=InsertRowsLimitsConfig(sequential=555),
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(
                        by_type="UInt64",
                        by_name="user_id",
                        types=["UInt64", "UInt32"],
                    )
                ],
                index_rules=[
                    IndexRuleConfig(
                        by_type="UInt32",
                        by_name="user_id",
                        indexes=[IndexConfig(type="minmax", granularity=4)],
                    )
                ],
            ),
            queries=QueriesConfig(
                mode="manual",
                test_queries=[QueryConfigItem(query="SELECT count() FROM {table}", select_operations_count=1)],
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        table_plan = next(engine.iter_table_plans())
        source_job = engine.build_source_benchmark_job(
            table_plan=table_plan,
            benchmark_run_id=1,
            benchmark_started_at=datetime(2026, 2, 25, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(source_job.insert_rows_limit, 555)

    def test_engine_uses_test_database_for_variant_tables_and_queries(self) -> None:
        """Проверяет, что engine использует test_database для variant-таблиц."""
        benchmark = BenchmarkConfig(
            id="bench_test_database",
            connection_id="prod_ch",
            strategy="types_strategy",
            databases=["analytics"],
            tables=["events"],
            test_database="bench_tmp",
            max_iterations=1,
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(
                        by_type="UInt64",
                        by_name="user_id",
                        types=["UInt64", "UInt32"],
                    )
                ]
            ),
            queries=QueriesConfig(
                mode="manual",
                test_queries=[
                    QueryConfigItem(
                        query="SELECT count() FROM {table}",
                        select_operations_count=1,
                        warmup_queries=["SELECT 1 FROM {table}"],
                    )
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
        self.assertEqual(job.source_database, "analytics")
        self.assertEqual(job.variant_database, "bench_tmp")
        self.assertEqual(job.variant_ddl.name, f"bench_tmp.{job.variant_table}")
        self.assertIn("`bench_tmp`.", job.query_plan.test_queries[0].warmup_queries[0])
        self.assertIn("`bench_tmp`.", job.query_plan.test_queries[0].query)

    def test_engine_auto_column_order_uses_compressed_size_desc(self) -> None:
        """Проверяет, что engine auto column order uses compressed size desc."""
        provider = StaticMetadataProvider(
            {"analytics": {"events": EVENTS_DDL}},
            column_sizes_by_db_table={
                "analytics": {
                    "events": {
                        "event_time": 10_000,
                        "user_id": 100,
                        "revenue": 10,
                    }
                }
            },
        )
        benchmark = BenchmarkConfig(
            id="bench_auto_column_order",
            connection_id="prod_ch",
            strategy="types_strategy",
            column_order_mode="compressed_size_desc",
            databases=["analytics"],
            tables=["events"],
            max_iterations=4,
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(
                        by_type="UInt64",
                        by_name="user_id",
                        types=["UInt64", "UInt32"],
                    ),
                    ColumnRuleConfig(
                        by_type="DateTime",
                        by_name="event_time",
                        types=["DateTime", "Date32"],
                    ),
                ]
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": provider},
        )
        engine = BenchmarkEngine(planner=planner)

        jobs = list(engine.iter_variant_jobs())
        self.assertEqual(len(jobs), 4)

        # При порядке event_time -> user_id второй вариант меняет user_id,
        # а event_time ещё остаётся исходным.
        second = jobs[1].variant_ddl
        self.assertEqual(second.column("event_time").type, "DateTime")
        self.assertEqual(second.column("user_id").type, "UInt32")

        third = jobs[2].variant_ddl
        self.assertEqual(third.column("event_time").type, "Date32")
        self.assertEqual(third.column("user_id").type, "UInt64")

    def test_engine_indexes_mode_uses_column_order_for_priority(self) -> None:
        """Проверяет, что engine indexes mode uses column order for priority."""
        provider = StaticMetadataProvider(
            {"analytics": {"events": EVENTS_DDL}},
            column_sizes_by_db_table={
                "analytics": {
                    "events": {
                        "event_time": 10_000,
                        "user_id": 100,
                    }
                }
            },
        )
        benchmark = BenchmarkConfig(
            id="bench_auto_index_order",
            connection_id="prod_ch",
            strategy="indexes_strategy",
            column_order_mode="compressed_size_desc",
            databases=["analytics"],
            tables=["events"],
            max_iterations=2,
            insert_rows_limits=InsertRowsLimitsConfig(indexes=222),
            global_rules=RulesConfig(
                index_rules=[
                    IndexRuleConfig(
                        by_type="DateTime",
                        by_name="event_time",
                        indexes=[IndexConfig(type="minmax", granularity=4)],
                    ),
                    IndexRuleConfig(
                        by_type="UInt64",
                        by_name="user_id",
                        indexes=[IndexConfig(type="minmax", granularity=4)],
                    ),
                ]
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": provider},
        )
        engine = BenchmarkEngine(planner=planner)

        jobs = list(engine.iter_variant_jobs())
        self.assertEqual(len(jobs), 2)

        first_indexes = [idx.expr for idx in jobs[0].variant_ddl.indexes]
        second_indexes = [idx.expr for idx in jobs[1].variant_ddl.indexes]
        self.assertEqual(first_indexes, ["user_id"])
        self.assertEqual(second_indexes, ["event_time"])
        self.assertTrue(all(job.insert_rows_limit == 222 for job in jobs))

    def test_engine_resolve_insert_rows_limit_supports_future_variant_modes(self) -> None:
        """Проверяет, что engine resolve insert rows limit supports future variant modes."""
        table_plan = TableBenchmarkPlan(
            benchmark_id="bench_future_mode_limits",
            connection_id="prod_ch",
            connection_dbms="clickhouse",
            database="analytics",
            table="events",
            strategy="types_strategy",
            mode="types",
            max_iterations=1,
            sequential_top_n=1,
            insert_rows_limit=999,
            insert_rows_limits=InsertRowsLimitsConfig.model_validate(
                {
                    "types": 111,
                    "future_mode_x": 444,
                }
            ),
            column_order_mode=None,
            rules=ResolvedRules(
                column_rules=[],
                index_rules=[],
                column_order={},
            ),
            queries=QueriesConfig(
                mode="manual",
                test_queries=[QueryConfigItem(query="SELECT 1 FROM {table}")],
            ),
            celery=CeleryConfig(workers=1, threads_per_worker=1),
        )

        # Извлекаем лимит для нового режима варианта напрямую по ключу.
        self.assertEqual(
            BenchmarkEngine.resolve_insert_rows_limit(
                table_plan=table_plan,
                variant_mode="future_mode_x",
                job_mode="types",
            ),
            444,
        )
        # Если ключа для режима варианта нет — берём запасной путь через режим задания.
        self.assertEqual(
            BenchmarkEngine.resolve_insert_rows_limit(
                table_plan=table_plan,
                variant_mode="unknown_variant_mode",
                job_mode="types",
            ),
            111,
        )

    def test_query_plan_builder_supports_auto_and_auto_with_manual(self) -> None:
        """Проверяет, что query plan builder supports auto and auto with manual."""
        table = TableDDL.from_ddl(EVENTS_DDL)
        builder = QueryPlanBuilder()

        auto_plan = builder.build(table, QueriesConfig(mode="auto"))
        self.assertGreater(len(auto_plan.test_queries), 0)

        manual_query = "SELECT 42 FROM {table}"
        mixed_plan = builder.build(
            table,
            QueriesConfig(
                mode="auto_with_manual",
                test_queries=[QueryConfigItem(query=manual_query)],
            ),
        )
        mixed_sqls = [q.query for q in mixed_plan.test_queries]
        self.assertIn(manual_query, mixed_sqls)
        self.assertGreater(len(mixed_plan.test_queries), len(auto_plan.test_queries))

    def test_fetcher_metadata_provider_handles_optional_fetch_column_sizes(self) -> None:
        """Проверяет, что fetcher metadata provider handles optional fetch column sizes."""
        class FetcherNoSizes:
            def list_databases(self) -> List[str]:
                """Возвращает фиксированный список БД."""
                return ["analytics"]

            def list_tables(self, database: str) -> List[str]:
                """Возвращает фиксированный список таблиц."""
                return ["events"]

            def fetch_ddl(self, database: str, table: str) -> TableDDL:
                """Возвращает тестовый DDL таблицы."""
                return TableDDL.from_ddl(EVENTS_DDL)

        class FetcherWithSizes(FetcherNoSizes):
            def fetch_column_sizes(self, database: str, table: str) -> Dict[str, int]:
                """Возвращает тестовые размеры колонок."""
                return {"event_time": 1000}

        provider_without_sizes = FetcherMetadataProvider(FetcherNoSizes())
        provider_with_sizes = FetcherMetadataProvider(FetcherWithSizes())

        self.assertEqual(provider_without_sizes.fetch_column_sizes("analytics", "events"), {})
        self.assertEqual(
            provider_with_sizes.fetch_column_sizes("analytics", "events"),
            {"event_time": 1000},
        )
        ddl = provider_with_sizes.fetch_table_ddl("analytics", "events")
        self.assertEqual(ddl.name, "analytics.events")

    def test_result_store_validates_result_identity(self) -> None:
        """Проверяет, что result store validates result identity."""
        benchmark = BenchmarkConfig(
            id="bench_result_store_validations",
            connection_id="prod_ch",
            strategy="types_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=1,
            global_rules=RulesConfig(
                column_rules=[ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])]
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        job = next(engine.iter_variant_jobs())
        store = InMemoryBenchmarkResultStore()

        with self.assertRaisesRegex(ValueError, "benchmark_run_id"):
            store.store_result(
                job,
                BenchmarkVariantResult(
                    benchmark_run_id=job.benchmark_run_id + 1,
                    benchmark_id=job.benchmark_id,
                    source_database=job.source_database,
                    source_table=job.source_table,
                    variant_table=job.variant_table,
                ),
            )

        with self.assertRaisesRegex(ValueError, "benchmark_started_at"):
            store.store_result(
                job,
                BenchmarkVariantResult(
                    benchmark_run_id=job.benchmark_run_id,
                    benchmark_started_at=job.benchmark_started_at.replace(
                        hour=(job.benchmark_started_at.hour + 1) % 24
                    ),
                    benchmark_id=job.benchmark_id,
                    source_database=job.source_database,
                    source_table=job.source_table,
                    variant_table=job.variant_table,
                ),
            )

        with self.assertRaisesRegex(ValueError, "benchmark_id"):
            store.store_result(
                job,
                BenchmarkVariantResult(
                    benchmark_run_id=job.benchmark_run_id,
                    benchmark_id="other_bench",
                    source_database=job.source_database,
                    source_table=job.source_table,
                    variant_table=job.variant_table,
                ),
            )

    def test_result_store_top_variants_sorts_and_handles_non_positive_topn(self) -> None:
        """Проверяет, что result store top variants sorts and handles non positive topn."""
        benchmark = BenchmarkConfig(
            id="bench_result_store_topn",
            connection_id="prod_ch",
            strategy="types_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=2,
            global_rules=RulesConfig(
                column_rules=[ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])]
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        jobs = list(engine.iter_variant_jobs())
        self.assertEqual(len(jobs), 2)

        store = InMemoryBenchmarkResultStore()
        store.store_result(
            jobs[0],
            BenchmarkVariantResult(
                benchmark_run_id=jobs[0].benchmark_run_id,
                benchmark_id=jobs[0].benchmark_id,
                source_database=jobs[0].source_database,
                source_table=jobs[0].source_table,
                variant_table=jobs[0].variant_table,
                score=None,
            ),
        )
        store.store_result(
            jobs[1],
            BenchmarkVariantResult(
                benchmark_run_id=jobs[1].benchmark_run_id,
                benchmark_id=jobs[1].benchmark_id,
                source_database=jobs[1].source_database,
                source_table=jobs[1].source_table,
                variant_table=jobs[1].variant_table,
                score=10.0,
            ),
        )

        self.assertEqual(
            store.get_top_type_variants(
                benchmark_run_id=1,
                benchmark_id="bench_result_store_topn",
                source_database="analytics",
                source_table="events",
                top_n=0,
            ),
            [],
        )

        top = store.get_top_type_variants(
            benchmark_run_id=1,
            benchmark_id="bench_result_store_topn",
            source_database="analytics",
            source_table="events",
            top_n=2,
        )
        self.assertEqual([item.variant_index for item in top], [1, 0])

    def test_runner_passes_jobs_to_execution_adapter(self) -> None:
        """Проверяет, что runner passes jobs to execution adapter."""
        benchmark = BenchmarkConfig(
            id="bench_run",
            connection_id="prod_ch",
            strategy="types_strategy",
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
            result_store.records[0].benchmark_started_at,
            adapter.executed_jobs[0].benchmark_started_at,
        )
        self.assertEqual(
            result_store.records[0].variant_table,
            adapter.executed_jobs[0].variant_table,
        )
        self.assertEqual(result_store.records[0].score, 1.0)
        self.assertEqual(
            result_store.records[0].variant_params["mode"],
            adapter.executed_jobs[0].variant_meta.mode,
        )
        self.assertEqual(
            result_store.records[0].variant_params["global_index"],
            adapter.executed_jobs[0].variant_meta.global_index,
        )
        self.assertIn("column_choices", result_store.records[0].variant_params)
        self.assertTrue(
            result_store.records[0].tested_table_ddl.startswith("CREATE TABLE")
        )

    def test_runner_propagates_table_index_granularity_to_variant_params(self) -> None:
        """Проверяет, что table index_granularity проходит в variant_params и DDL."""
        benchmark = BenchmarkConfig(
            id="bench_index_granularity_variant_params",
            connection_id="prod_ch",
            strategy="indexes_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=10,
            index_granularity_values=[8192, 16384],
            global_rules=RulesConfig(
                index_rules=[
                    IndexRuleConfig(
                        by_type="UInt64",
                        indexes=[IndexConfig(type="minmax", granularity=4)],
                    )
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
        # Для одного column-rule в indexes режиме: (1 index) * 2 granularity = 2.
        self.assertEqual(len(adapter.executed_jobs), 2)
        self.assertEqual(len(result_store.records), 2)

        granularities = {
            record.variant_params.get("table_index_granularity")
            for record in result_store.records
        }
        self.assertEqual(granularities, {8192, 16384})
        for record in result_store.records:
            table_index_granularity = record.variant_params.get("table_index_granularity")
            self.assertIsInstance(table_index_granularity, int)
            self.assertIn(
                f"SETTINGS index_granularity = {table_index_granularity}",
                record.tested_table_ddl,
            )

    def test_runner_executes_source_benchmark_before_variants_and_propagates_it(self) -> None:
        """Проверяет baseline на source DDL и его прокидывание в variant jobs."""
        benchmark = BenchmarkConfig(
            id="bench_source_baseline",
            connection_id="prod_ch",
            strategy="types_strategy",
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
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=InMemoryBenchmarkResultStore(),
        )

        run_id = runner.run()
        self.assertEqual(run_id, 1)
        self.assertEqual(adapter.call_sequence, ["source", "variant"])
        self.assertEqual(len(adapter.source_jobs), 1)
        self.assertEqual(len(adapter.source_results), 1)
        self.assertEqual(len(adapter.executed_jobs), 1)

        source_result = adapter.source_results[0]
        job = adapter.executed_jobs[0]
        source_benchmark = job.source_benchmark
        self.assertIsNotNone(source_benchmark)
        if source_benchmark is None:
            self.fail("source_benchmark должен быть установлен в variant job")
        self.assertEqual(source_benchmark.baseline_id, source_result.baseline_id)
        self.assertEqual(source_benchmark.benchmark_run_id, job.benchmark_run_id)
        self.assertEqual(source_benchmark.benchmark_id, job.benchmark_id)
        self.assertEqual(source_benchmark.source_database, job.source_database)
        self.assertEqual(source_benchmark.source_table, job.source_table)

    def test_runner_skips_table_plan_when_source_baseline_is_skipped(self) -> None:
        """Проверяет, что runner пропускает table-plan при skipped baseline."""
        benchmark = BenchmarkConfig(
            id="bench_skip_empty_source",
            connection_id="prod_ch",
            strategy="types_strategy",
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
        adapter = SkippingSourceExecutionAdapter()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=InMemoryBenchmarkResultStore(),
        )

        run_id = runner.run()
        self.assertEqual(run_id, 1)
        self.assertEqual(len(adapter.source_jobs), 1)
        self.assertEqual(len(adapter.executed_jobs), 0)

    def test_result_store_prefers_worker_variant_params_and_ddl_when_provided(self) -> None:
        """Проверяет, что result store сохраняет worker-side variant params/DDL."""
        benchmark = BenchmarkConfig(
            id="bench_result_store_worker_params",
            connection_id="prod_ch",
            strategy="types_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=1,
            global_rules=RulesConfig(
                column_rules=[ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])]
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        job = next(engine.iter_variant_jobs())
        store = InMemoryBenchmarkResultStore()

        store.store_result(
            job,
            BenchmarkVariantResult(
                benchmark_run_id=job.benchmark_run_id,
                benchmark_id=job.benchmark_id,
                source_database=job.source_database,
                source_table=job.source_table,
                variant_table=job.variant_table,
                variant_params={"worker_variant_key": "worker_variant_value"},
                source_table_ddl="CREATE TABLE analytics.events (...)",
                tested_table_ddl="CREATE TABLE analytics.events__v (...)",
                score=0.42,
            ),
        )

        self.assertEqual(len(store.records), 1)
        row = store.records[0]
        self.assertEqual(row.source_db_name, "analytics")
        self.assertEqual(row.source_table_name, "events")
        self.assertIsNotNone(row.id)
        self.assertEqual(
            row.variant_params,
            {"worker_variant_key": "worker_variant_value"},
        )
        self.assertEqual(
            row.source_table_ddl,
            "CREATE TABLE analytics.events (...)",
        )
        self.assertEqual(
            row.tested_table_ddl,
            "CREATE TABLE analytics.events__v (...)",
        )

    def test_runner_allows_missing_result_store_for_non_sequential_strategies(self) -> None:
        """Проверяет, что result_store опционален для non-sequential стратегий."""
        benchmark = BenchmarkConfig(
            id="bench_run_without_store",
            connection_id="prod_ch",
            strategy="types_strategy",
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
        adapter = AsyncDispatchOnlyAdapter()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
        )

        run_id = runner.run()
        self.assertEqual(run_id, 1)
        self.assertEqual(len(adapter.executed_jobs), 1)

    def test_sequential_strategy_requires_result_store_when_missing(self) -> None:
        """Проверяет, что sequential top-N требует result_store для top-N отбора."""
        benchmark = BenchmarkConfig(
            id="bench_sequential_without_store",
            connection_id="prod_ch",
            strategy="sequential_topn_strategy",
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
                    )
                ],
                index_rules=[
                    IndexRuleConfig(
                        by_type="UInt32",
                        by_name="user_id",
                        indexes=[IndexConfig(type="minmax", granularity=4)],
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
        adapter = AsyncDispatchOnlyAdapter()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
        )

        with self.assertRaisesRegex(ValueError, "требует result_store"):
            runner.run()
        self.assertEqual(len(adapter.executed_jobs), 0)

    def test_runner_rejects_non_positive_explicit_run_id(self) -> None:
        """Проверяет, что runner rejects non positive explicit run id."""
        benchmark = BenchmarkConfig(
            id="bench_bad_run_id",
            connection_id="prod_ch",
            strategy="types_strategy",
            databases=["analytics"],
            tables=["events"],
            global_rules=RulesConfig(
                column_rules=[ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])]
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=RecordingExecutionAdapter(),
            result_store=InMemoryBenchmarkResultStore(),
        )

        with self.assertRaisesRegex(ValueError, "должен быть > 0"):
            runner.run(benchmark_run_id=0)

    def test_runner_stops_before_dispatch_when_scoring_expression_invalid(self) -> None:
        """Проверяет, что pre-run validation останавливает запуск при битой формуле."""
        benchmark = BenchmarkConfig(
            id="bench_invalid_expression",
            connection_id="prod_ch",
            strategy="types_strategy",
            scoring={
                "mode": "expression",
                "expression": "unknown_root.select.time_ms_percentiles[0]",
            },
            databases=["analytics"],
            tables=["events"],
            global_rules=RulesConfig(
                column_rules=[ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])]
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        adapter = RecordingExecutionAdapter()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=InMemoryBenchmarkResultStore(),
        )

        with self.assertRaisesRegex(ValueError, "Валидация scoring.expression не пройдена"):
            runner.run()
        self.assertEqual(len(adapter.source_jobs), 0)
        self.assertEqual(len(adapter.executed_jobs), 0)

    def test_runner_assigns_single_serial_run_id_per_run(self) -> None:
        """Проверяет, что runner assigns single serial run id per run."""
        benchmark = BenchmarkConfig(
            id="bench_run_id_serial",
            connection_id="prod_ch",
            strategy="types_strategy",
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

    def test_runner_assigns_single_run_start_time_per_run(self) -> None:
        """Проверяет, что runner assigns single run start time per run."""
        benchmark = BenchmarkConfig(
            id="bench_run_started_at",
            connection_id="prod_ch",
            strategy="types_strategy",
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

        timestamps = iter(
            [
                datetime(2026, 2, 24, 10, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 2, 24, 10, 5, 0, tzinfo=timezone.utc),
            ]
        )
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=result_store,
            run_started_at_provider=lambda: next(timestamps),
        )

        run1 = runner.run()
        run1_jobs = list(adapter.executed_jobs)
        run1_records = list(result_store.records)
        run1_started_at = datetime(2026, 2, 24, 10, 0, 0, tzinfo=timezone.utc)

        run2 = runner.run()
        run2_jobs = adapter.executed_jobs[len(run1_jobs) :]
        run2_records = result_store.records[len(run1_records) :]
        run2_started_at = datetime(2026, 2, 24, 10, 5, 0, tzinfo=timezone.utc)

        self.assertEqual(run1, 1)
        self.assertEqual(run2, 2)
        self.assertTrue(run1_jobs)
        self.assertTrue(run2_jobs)
        self.assertTrue(all(job.benchmark_started_at == run1_started_at for job in run1_jobs))
        self.assertTrue(all(job.benchmark_started_at == run2_started_at for job in run2_jobs))
        self.assertTrue(
            all(record.benchmark_started_at == run1_started_at for record in run1_records)
        )
        self.assertTrue(
            all(record.benchmark_started_at == run2_started_at for record in run2_records)
        )
        self.assertEqual(runner.last_benchmark_started_at, run2_started_at)

    def test_runner_executes_benchmarks_in_lexicographic_id_order(self) -> None:
        """Проверяет, что runner executes benchmarks in lexicographic id order."""
        benchmark_z = BenchmarkConfig(
            id="bench_z",
            connection_id="prod_ch",
            strategy="types_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=1,
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])
                ]
            ),
        )
        benchmark_a = BenchmarkConfig(
            id="bench_a",
            connection_id="prod_ch",
            strategy="types_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=1,
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])
                ]
            ),
        )
        root = BenchmarkRootConfig(
            connections=[self.connection],
            benchmarks=[benchmark_z, benchmark_a],  # специально не по алфавиту
            rule_banks={},
            default_rule_banks={},
            celery=CeleryConfig(workers=2, threads_per_worker=1),
        )
        planner = BenchmarkPlanner(
            config=root,
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

        runner.run()

        executed_benchmark_ids = [job.benchmark_id for job in adapter.executed_jobs]
        self.assertEqual(executed_benchmark_ids, ["bench_a", "bench_z"])

    def test_runner_can_register_strategy_execution_strategy(self) -> None:
        """Проверяет, что runner can register strategy execution strategy."""
        benchmark = BenchmarkConfig(
            id="bench_custom_mode_strategy",
            connection_id="prod_ch",
            strategy="types_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=1,
            global_rules=RulesConfig(
                column_rules=[ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])]
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        adapter = RecordingExecutionAdapter()
        result_store = InMemoryBenchmarkResultStore()
        strategy = RecordingTableExecutionStrategy()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=result_store,
        )
        runner.register_table_execution_strategy(
            "types_strategy",
            strategy,
            overwrite=True,
        )

        run_id = runner.run()
        self.assertEqual(run_id, 1)
        self.assertEqual(strategy.calls, [("bench_custom_mode_strategy", "events", 1)])
        self.assertEqual(len(adapter.executed_jobs), 0)
        self.assertEqual(len(result_store.records), 0)

    def test_runner_accepts_constructor_strategy_execution_strategies(self) -> None:
        """Проверяет, что runner accepts constructor strategy execution strategies."""
        benchmark = BenchmarkConfig(
            id="bench_ctor_custom_mode_strategy",
            connection_id="prod_ch",
            strategy="types_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=1,
            global_rules=RulesConfig(
                column_rules=[ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])]
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        adapter = RecordingExecutionAdapter()
        result_store = InMemoryBenchmarkResultStore()
        strategy = RecordingTableExecutionStrategy()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=result_store,
            table_execution_strategies={"types_strategy": strategy},
        )

        run_id = runner.run()
        self.assertEqual(run_id, 1)
        self.assertEqual(strategy.calls, [("bench_ctor_custom_mode_strategy", "events", 1)])
        self.assertEqual(len(adapter.executed_jobs), 0)
        self.assertEqual(len(result_store.records), 0)

    def test_runner_uses_strategy_field_from_config(self) -> None:
        """Проверяет, что runner uses strategy field from config."""
        common_rules = RulesConfig(
            column_rules=[ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])],
            index_rules=[
                IndexRuleConfig(
                    by_type="UInt64",
                    indexes=[IndexConfig(type="minmax", granularity=4)],
                )
            ],
        )
        benchmarks = [
            BenchmarkConfig(
                id="bench_strategy_types",
                connection_id="prod_ch",
                strategy="types_strategy",
                databases=["analytics"],
                tables=["events"],
                max_iterations=1,
                global_rules=common_rules,
            ),
            BenchmarkConfig(
                id="bench_strategy_indexes",
                connection_id="prod_ch",
                strategy="indexes_strategy",
                databases=["analytics"],
                tables=["events"],
                max_iterations=1,
                global_rules=common_rules,
            ),
            BenchmarkConfig(
                id="bench_strategy_combined",
                connection_id="prod_ch",
                strategy="combined_strategy",
                databases=["analytics"],
                tables=["events"],
                max_iterations=1,
                global_rules=common_rules,
            ),
        ]
        planner = BenchmarkPlanner(
            config=BenchmarkRootConfig(
                connections=[self.connection],
                benchmarks=benchmarks,
                rule_banks={},
                default_rule_banks={},
                celery=CeleryConfig(workers=2, threads_per_worker=1),
            ),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        adapter = RecordingExecutionAdapter()
        result_store = InMemoryBenchmarkResultStore()
        types_strategy = RecordingTableExecutionStrategy()
        indexes_strategy = RecordingTableExecutionStrategy()
        combined_strategy = RecordingTableExecutionStrategy()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=result_store,
            table_execution_strategies={
                "types_strategy": types_strategy,
                "indexes_strategy": indexes_strategy,
                "combined_strategy": combined_strategy,
            },
        )

        run_id = runner.run()
        self.assertEqual(run_id, 1)
        self.assertEqual(
            types_strategy.calls,
            [("bench_strategy_types", "events", 1)],
        )
        self.assertEqual(
            indexes_strategy.calls,
            [("bench_strategy_indexes", "events", 1)],
        )
        self.assertEqual(
            combined_strategy.calls,
            [("bench_strategy_combined", "events", 1)],
        )
        self.assertEqual(len(adapter.executed_jobs), 0)
        self.assertEqual(len(result_store.records), 0)

    def test_runner_uses_injected_default_table_execution_strategy(self) -> None:
        """Проверяет, что runner uses injected default table execution strategy."""
        benchmark = BenchmarkConfig(
            id="bench_custom_default_strategy",
            connection_id="prod_ch",
            strategy="types_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=1,
            global_rules=RulesConfig(
                column_rules=[ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])]
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        adapter = RecordingExecutionAdapter()
        result_store = InMemoryBenchmarkResultStore()
        default_strategy = RecordingTableExecutionStrategy()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=result_store,
            default_table_execution_strategy=default_strategy,
        )
        # Убираем встроенную стратегию для types, чтобы проверить резервное поведение.
        runner._table_execution_strategies.pop("types_strategy")

        run_id = runner.run()
        self.assertEqual(run_id, 1)
        self.assertEqual(default_strategy.calls, [("bench_custom_default_strategy", "events", 1)])
        self.assertEqual(len(adapter.executed_jobs), 0)
        self.assertEqual(len(result_store.records), 0)

    def test_runner_rejects_duplicate_strategy_execution_strategy_without_overwrite(self) -> None:
        """Проверяет, что runner rejects duplicate strategy execution strategy without overwrite."""
        benchmark = BenchmarkConfig(
            id="bench_duplicate_strategy",
            connection_id="prod_ch",
            strategy="types_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=1,
            global_rules=RulesConfig(
                column_rules=[ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])]
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=RecordingExecutionAdapter(),
            result_store=InMemoryBenchmarkResultStore(),
        )

        with self.assertRaisesRegex(ValueError, "уже зарегистрирована"):
            runner.register_table_execution_strategy(
                "sequential_topn_strategy",
                RecordingTableExecutionStrategy(),
            )

    def test_runner_register_strategy_execution_strategy_rejects_empty_key(self) -> None:
        """Проверяет, что runner register strategy execution strategy rejects empty key."""
        benchmark = BenchmarkConfig(
            id="bench_empty_mode_strategy",
            connection_id="prod_ch",
            strategy="types_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=1,
            global_rules=RulesConfig(
                column_rules=[ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])]
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=RecordingExecutionAdapter(),
            result_store=InMemoryBenchmarkResultStore(),
        )

        with self.assertRaisesRegex(ValueError, "не должен быть пустым"):
            runner.register_table_execution_strategy(
                "   ",
                RecordingTableExecutionStrategy(),
            )

    def test_runner_register_strategy_execution_strategy_allows_overwrite(self) -> None:
        """Проверяет, что runner register strategy execution strategy allows overwrite."""
        benchmark = BenchmarkConfig(
            id="bench_override_sequential_strategy",
            connection_id="prod_ch",
            strategy="sequential_topn_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=1,
            sequential_top_n=1,
            global_rules=RulesConfig(
                column_rules=[ColumnRuleConfig(by_type="UInt64", types=["UInt64", "UInt32"])],
                index_rules=[
                    IndexRuleConfig(
                        by_type="UInt64",
                        indexes=[IndexConfig(type="minmax", granularity=4)],
                    )
                ],
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        adapter = RecordingExecutionAdapter()
        result_store = InMemoryBenchmarkResultStore()
        sequential_override = RecordingTableExecutionStrategy()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=result_store,
        )
        runner.register_table_execution_strategy(
            "sequential_topn_strategy",
            sequential_override,
            overwrite=True,
        )

        run_id = runner.run()
        self.assertEqual(run_id, 1)
        self.assertEqual(
            sequential_override.calls,
            [("bench_override_sequential_strategy", "events", 1)],
        )
        self.assertEqual(len(adapter.executed_jobs), 0)
        self.assertEqual(len(result_store.records), 0)

    def test_runner_uses_max_id_provider_as_source_of_run_ids(self) -> None:
        """Проверяет, что runner uses max id provider as source of run ids."""
        benchmark = BenchmarkConfig(
            id="bench_run_id_from_max",
            connection_id="prod_ch",
            strategy="types_strategy",
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
            """Возвращает текущее максимальное значение run_id из фикстуры."""
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

    def test_max_id_provider_rejects_negative_observed_max(self) -> None:
        """Проверяет, что max id provider rejects negative observed max."""
        provider = MaxIdBenchmarkRunIdProvider(max_id_getter=lambda: -1)
        with self.assertRaisesRegex(ValueError, "отрицательный benchmark id"):
            provider.next_benchmark_run_id()

    def test_sequential_mode_runs_indexes_for_top_n_type_variants(self) -> None:
        """Проверяет, что sequential mode runs indexes for top n type variants."""
        benchmark = BenchmarkConfig(
            id="bench_sequential_topn",
            connection_id="prod_ch",
            strategy="sequential_topn_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=10,
            sequential_top_n=1,
            insert_rows_limit=999,
            insert_rows_limits=InsertRowsLimitsConfig(
                types=111,
                indexes=222,
                sequential=333,
            ),
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

        # Этап 1: 2 варианта типов (UInt64/UInt32).
        # Этап 2: для top-1 (UInt32) запускаются 2 варианта индексов.
        self.assertEqual(run_id, 1)
        self.assertEqual(len(result_store.records), 4)
        self.assertEqual(len(adapter.executed_jobs), 4)
        self.assertTrue(all(r.benchmark_run_id == 1 for r in result_store.records))
        self.assertTrue(all(j.benchmark_run_id == 1 for j in adapter.executed_jobs))

        stages = [job.variant_meta.mode for job in adapter.executed_jobs]
        self.assertEqual(stages[:2], ["types", "types"])
        self.assertEqual(stages[2:], ["indexes", "indexes"])

        # Индексный этап должен идти по лучшему варианту типов (UInt32).
        indexed_job_types = [
            job.variant_ddl.column("user_id").type
            for job in adapter.executed_jobs
            if job.variant_meta.mode == "indexes"
        ]
        self.assertEqual(indexed_job_types, ["UInt32", "UInt32"])
        self.assertTrue(
            all(
                job.insert_rows_limit == 111
                for job in adapter.executed_jobs
                if job.variant_meta.mode == "types"
            )
        )
        self.assertTrue(
            all(
                job.insert_rows_limit == 222
                for job in adapter.executed_jobs
                if job.variant_meta.mode == "indexes"
            )
        )

        global_indexes = [job.variant_meta.global_index for job in adapter.executed_jobs]
        self.assertEqual(global_indexes, [0, 1, 2, 3])

        variant_tables = [job.variant_table for job in adapter.executed_jobs]
        self.assertEqual(len(variant_tables), len(set(variant_tables)))

    def test_sequential_phased_topn_strategy_runs_all_phases(self) -> None:
        """Проверяет, что sequential_phased_topn_strategy проходит все фазы."""
        benchmark = BenchmarkConfig(
            id="bench_sequential_phased_topn",
            connection_id="prod_ch",
            strategy="sequential_phased_topn_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=10,
            sequential_top_n=1,
            index_granularity_values=[8192, 16384],
            order_by_first="event_time",
            order_by_candidates=["user_id"],
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(
                        by_type="UInt64",
                        by_name="user_id",
                        types=["UInt64", "UInt32"],
                        codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"],
                    )
                ],
                index_rules=[
                    IndexRuleConfig(
                        by_type="UInt32",
                        by_name="user_id",
                        indexes=[
                            IndexConfig(
                                type="minmax",
                                granularity=[1, 2],
                                index_granularity_values=[8192, 16384],
                            )
                        ],
                    )
                ],
            ),
            queries=QueriesConfig(
                mode="manual",
                test_queries=[
                    QueryConfigItem(
                        query="SELECT count() FROM {table} WHERE user_id > 0"
                    )
                ],
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        adapter = SequentialPhasedScoringAdapter()
        store = InMemoryBenchmarkResultStore()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=store,
        )

        run_id = runner.run()
        self.assertEqual(run_id, 1)
        self.assertGreater(len(adapter.executed_jobs), 0)

        modes = [job.variant_meta.mode for job in adapter.executed_jobs]
        required_modes = {
            "order_by",
            "types",
            "types_validation",
            "codecs",
            "codecs_validation",
            "indexes",
            "indexes_validation",
            "final_validation",
        }
        self.assertTrue(required_modes.issubset(set(modes)))

        first_occurrence = {mode: modes.index(mode) for mode in required_modes}
        self.assertLess(first_occurrence["order_by"], first_occurrence["types"])
        self.assertLess(first_occurrence["types"], first_occurrence["types_validation"])
        self.assertLess(first_occurrence["types_validation"], first_occurrence["codecs"])
        self.assertLess(first_occurrence["codecs"], first_occurrence["codecs_validation"])
        self.assertLess(first_occurrence["codecs_validation"], first_occurrence["indexes"])
        self.assertLess(first_occurrence["indexes"], first_occurrence["indexes_validation"])
        self.assertLess(first_occurrence["indexes_validation"], first_occurrence["final_validation"])

        index_jobs = [job for job in adapter.executed_jobs if job.variant_meta.mode == "indexes"]
        self.assertTrue(index_jobs)
        self.assertTrue(
            any(job.variant_meta.table_index_granularity == 8192 for job in index_jobs)
        )
        self.assertTrue(
            any(job.variant_meta.table_index_granularity == 16384 for job in index_jobs)
        )
        index_granularities = {
            job.variant_ddl.indexes[0].granularity
            for job in index_jobs
            if job.variant_ddl.indexes
        }
        self.assertTrue({"1", "2"}.issubset(index_granularities))

        index_validation_jobs = [
            job
            for job in adapter.executed_jobs
            if job.variant_meta.mode == "indexes_validation"
        ]
        self.assertGreaterEqual(len(index_validation_jobs), 2)

    def test_sequential_phased_topn_strategy_supports_stage_specific_top_n(self) -> None:
        """Проверяет, что top-N можно задавать отдельно для каждой фазы."""
        benchmark = BenchmarkConfig(
            id="bench_sequential_phased_topn_stage_specific",
            connection_id="prod_ch",
            strategy="sequential_phased_topn_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=10,
            sequential_top_n=2,
            sequential_top_n_limits=InsertRowsLimitsConfig(
                types=1,
                codecs=1,
                indexes=1,
                final_validation=1,
            ),
            index_granularity_values=[8192, 16384],
            order_by_first="event_time",
            order_by_candidates=["user_id"],
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(
                        by_type="UInt64",
                        by_name="user_id",
                        types=["UInt64", "UInt32"],
                        codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"],
                    )
                ],
                index_rules=[
                    IndexRuleConfig(
                        by_type="UInt32",
                        by_name="user_id",
                        indexes=[
                            IndexConfig(
                                type="minmax",
                                granularity=[1, 2],
                                index_granularity_values=[8192, 16384],
                            )
                        ],
                    )
                ],
            ),
            queries=QueriesConfig(
                mode="manual",
                test_queries=[
                    QueryConfigItem(
                        query="SELECT count() FROM {table} WHERE user_id > 0"
                    )
                ],
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        adapter = SequentialPhasedScoringAdapter()
        store = InMemoryBenchmarkResultStore()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=store,
        )

        run_id = runner.run()
        self.assertEqual(run_id, 1)

        order_jobs = [
            job for job in adapter.executed_jobs if job.variant_meta.mode == "order_by"
        ]
        types_validation_jobs = [
            job
            for job in adapter.executed_jobs
            if job.variant_meta.mode == "types_validation"
        ]
        codecs_validation_jobs = [
            job
            for job in adapter.executed_jobs
            if job.variant_meta.mode == "codecs_validation"
        ]

        # При sequential_top_n=2 order_by и types_validation остаются по 2 (по parent-веткам).
        self.assertEqual(len(order_jobs), 2)
        self.assertEqual(len(types_validation_jobs), 2)
        # Но дальше работает stage-specific лимит types=1 => в codecs идет только 1 победитель.
        self.assertEqual(len(codecs_validation_jobs), 1)

    def test_sequential_phased_topn_strategy_supports_multiple_winners_per_parent(self) -> None:
        """Проверяет, что max_winners_per_parent_limits реально даёт >1 кандидата на parent."""
        benchmark = BenchmarkConfig(
            id="bench_sequential_phased_topn_per_parent",
            connection_id="prod_ch",
            strategy="sequential_phased_topn_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=10,
            sequential_top_n=1,
            sequential_top_n_limits=InsertRowsLimitsConfig(
                order_by=1,
                types=1,
                codecs=1,
                indexes=1,
                final_validation=1,
            ),
            max_winners_per_parent_limits=InsertRowsLimitsConfig(
                types=3,
                codecs=3,
                indexes=3,
            ),
            index_granularity_values=[8192, 16384],
            order_by_first="event_time",
            order_by_candidates=["user_id"],
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(
                        by_type="UInt64",
                        by_name="user_id",
                        types=["UInt64", "UInt32"],
                        codecs=["CODEC(LZ4)", "CODEC(ZSTD(1))"],
                    )
                ],
                index_rules=[
                    IndexRuleConfig(
                        by_type="UInt32",
                        by_name="user_id",
                        indexes=[
                            IndexConfig(
                                type="minmax",
                                granularity=[1, 2],
                                index_granularity_values=[8192, 16384],
                            )
                        ],
                    )
                ],
            ),
            queries=QueriesConfig(
                mode="manual",
                test_queries=[
                    QueryConfigItem(
                        query="SELECT count() FROM {table} WHERE user_id > 0"
                    )
                ],
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        adapter = SequentialPhasedScoringAdapter()
        store = InMemoryBenchmarkResultStore()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=store,
        )

        run_id = runner.run()
        self.assertEqual(run_id, 1)

        index_validation_jobs = [
            job
            for job in adapter.executed_jobs
            if job.variant_meta.mode == "indexes_validation"
        ]
        # Для одного parent при лимите 3 ожидаем не меньше 3 финальных кандидатов индексов.
        self.assertGreaterEqual(len(index_validation_jobs), 3)

    def test_sequential_mode_propagates_source_benchmark_to_all_stage_jobs(self) -> None:
        """Проверяет, что baseline source benchmark доступен во всех sequential jobs."""
        benchmark = BenchmarkConfig(
            id="bench_sequential_source_baseline",
            connection_id="prod_ch",
            strategy="sequential_topn_strategy",
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
                    )
                ],
                index_rules=[
                    IndexRuleConfig(
                        by_type="UInt64",
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
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=InMemoryBenchmarkResultStore(),
        )

        run_id = runner.run()
        self.assertEqual(run_id, 1)
        self.assertEqual(adapter.call_sequence[0], "source")
        self.assertEqual(adapter.call_sequence.count("source"), 1)
        self.assertGreater(len(adapter.executed_jobs), 0)
        self.assertEqual(len(adapter.source_results), 1)

        baseline_id = adapter.source_results[0].baseline_id
        self.assertTrue(all(job.source_benchmark is not None for job in adapter.executed_jobs))
        propagated_baseline_ids = {
            job.source_benchmark.baseline_id
            for job in adapter.executed_jobs
            if job.source_benchmark is not None
        }
        self.assertEqual(propagated_baseline_ids, {baseline_id})

    def test_sequential_mode_uses_stage_limits_with_table_override(self) -> None:
        """Проверяет, что sequential mode uses stage limits with table override."""
        benchmark = BenchmarkConfig(
            id="bench_sequential_stage_limits_override",
            connection_id="prod_ch",
            strategy="combined_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=10,
            sequential_top_n=1,
            insert_rows_limit=999,
            insert_rows_limits=InsertRowsLimitsConfig(
                types=111,
                indexes=222,
                combined=444,
                sequential=333,
            ),
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
            table_rules=[
                TableRuleConfig(
                    database="analytics",
                    table="events",
                    strategy="sequential_topn_strategy",
                    insert_rows_limits=InsertRowsLimitsConfig(indexes=777),
                )
            ],
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
        self.assertEqual(run_id, 1)
        self.assertEqual(len(adapter.executed_jobs), 4)
        self.assertTrue(
            all(
                job.insert_rows_limit == 111
                for job in adapter.executed_jobs
                if job.variant_meta.mode == "types"
            )
        )
        self.assertTrue(
            all(
                job.insert_rows_limit == 777
                for job in adapter.executed_jobs
                if job.variant_meta.mode == "indexes"
            )
        )
        self.assertTrue(
            all(job.insert_rows_limit in {111, 777} for job in adapter.executed_jobs)
        )

    def test_sequential_mode_waits_on_external_store(self) -> None:
        """Проверяет, что sequential mode ждёт внешнее store и затем запускает index-stage."""
        benchmark = BenchmarkConfig(
            id="bench_sequential_external_store_wait",
            connection_id="prod_ch",
            strategy="sequential_topn_strategy",
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
        result_store = InMemoryBenchmarkResultStore()
        adapter = AsyncSelfPersistingSequentialAdapter(store=result_store)
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=result_store,
        )

        run_id = runner.run()
        self.assertEqual(run_id, 1)
        self.assertEqual(len(adapter.executed_jobs), 4)
        self.assertEqual(len(result_store.records), 4)
        self.assertEqual(
            [job.variant_meta.mode for job in adapter.executed_jobs],
            ["types", "types", "indexes", "indexes"],
        )
        self.assertEqual(
            [
                job.variant_ddl.column("user_id").type
                for job in adapter.executed_jobs
                if job.variant_meta.mode == "indexes"
            ],
            ["UInt32", "UInt32"],
        )

    def test_types_strategy_dispatch_only_does_not_store_in_runner(self) -> None:
        """Проверяет, что types strategy в async-dispatch режиме не пишет в store."""
        benchmark = BenchmarkConfig(
            id="bench_types_dispatch_only",
            connection_id="prod_ch",
            strategy="types_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=10,
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
                test_queries=[QueryConfigItem(query="SELECT count() FROM {table}")],
            ),
        )
        planner = BenchmarkPlanner(
            config=self._root(benchmark),
            providers_by_connection_id={"prod_ch": self.provider},
        )
        engine = BenchmarkEngine(planner=planner)
        adapter = AsyncDispatchOnlyAdapter()
        store = InMemoryBenchmarkResultStore()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=store,
        )

        run_id = runner.run()
        self.assertEqual(run_id, 1)
        self.assertEqual([job.variant_meta.mode for job in adapter.executed_jobs], ["types", "types"])
        self.assertEqual(len(store.records), 0)

    def test_indexes_strategy_dispatch_only_does_not_store_in_runner(self) -> None:
        """Проверяет, что indexes strategy в async-dispatch режиме не пишет в store."""
        benchmark = BenchmarkConfig(
            id="bench_indexes_dispatch_only",
            connection_id="prod_ch",
            strategy="indexes_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=10,
            global_rules=RulesConfig(
                index_rules=[
                    IndexRuleConfig(
                        by_type="UInt64",
                        by_name="user_id",
                        indexes=[
                            IndexConfig(type="minmax", granularity=4),
                            IndexConfig(type="bloom_filter(0.01)", granularity=2),
                        ],
                    )
                ]
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
        adapter = AsyncDispatchOnlyAdapter()
        store = InMemoryBenchmarkResultStore()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=store,
        )

        run_id = runner.run()
        self.assertEqual(run_id, 1)
        self.assertEqual(
            [job.variant_meta.mode for job in adapter.executed_jobs],
            ["indexes", "indexes"],
        )
        self.assertEqual(len(store.records), 0)

    def test_combined_strategy_dispatch_only_does_not_store_in_runner(self) -> None:
        """Проверяет, что combined strategy в async-dispatch режиме не пишет в store."""
        benchmark = BenchmarkConfig(
            id="bench_combined_dispatch_only",
            connection_id="prod_ch",
            strategy="combined_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=10,
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(
                        by_type="UInt64",
                        by_name="user_id",
                        types=["UInt64", "UInt32"],
                    )
                ],
                index_rules=[
                    IndexRuleConfig(
                        by_type="UInt64",
                        by_name="user_id",
                        indexes=[IndexConfig(type="minmax", granularity=4)],
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
        adapter = AsyncDispatchOnlyAdapter()
        store = InMemoryBenchmarkResultStore()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=store,
        )

        run_id = runner.run()
        self.assertEqual(run_id, 1)
        self.assertTrue(adapter.executed_jobs)
        self.assertTrue(all(job.variant_meta.mode == "combined" for job in adapter.executed_jobs))
        self.assertEqual(len(store.records), 0)

    def test_sequential_mode_times_out_when_top_variants_never_appear(self) -> None:
        """Проверяет, что sequential mode ждёт top variants и падает по timeout."""
        benchmark = BenchmarkConfig(
            id="bench_sequential_no_top",
            connection_id="prod_ch",
            strategy="sequential_topn_strategy",
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
        result_store = NoTopVariantsResultStore()
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=result_store,
        )

        original_timeout = sequential_topn_strategy_impl._TYPE_STAGE_WAIT_TIMEOUT_SEC
        original_poll = sequential_topn_strategy_impl._TYPE_STAGE_WAIT_POLL_INTERVAL_SEC
        sequential_topn_strategy_impl._TYPE_STAGE_WAIT_TIMEOUT_SEC = 0.05
        sequential_topn_strategy_impl._TYPE_STAGE_WAIT_POLL_INTERVAL_SEC = 0.01
        try:
            with self.assertRaises(TimeoutError):
                runner.run()
        finally:
            sequential_topn_strategy_impl._TYPE_STAGE_WAIT_TIMEOUT_SEC = original_timeout
            sequential_topn_strategy_impl._TYPE_STAGE_WAIT_POLL_INTERVAL_SEC = original_poll
        self.assertEqual(len(adapter.executed_jobs), 2)  # только этап вариантов типов
        self.assertEqual(
            [job.variant_meta.mode for job in adapter.executed_jobs],
            ["types", "types"],
        )

    def test_sequential_mode_uses_sequential_insert_rows_limit_fallback(self) -> None:
        """Проверяет, что sequential mode uses sequential insert rows limit fallback."""
        benchmark = BenchmarkConfig(
            id="bench_sequential_insert_rows_fallback",
            connection_id="prod_ch",
            strategy="sequential_topn_strategy",
            databases=["analytics"],
            tables=["events"],
            max_iterations=10,
            sequential_top_n=1,
            insert_rows_limit=777,
            insert_rows_limits=InsertRowsLimitsConfig(sequential=555),
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(
                        by_type="UInt64",
                        by_name="user_id",
                        types=["UInt64", "UInt32"],
                    )
                ],
                index_rules=[
                    IndexRuleConfig(
                        by_type="UInt32",
                        by_name="user_id",
                        indexes=[IndexConfig(type="minmax", granularity=4)],
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
        self.assertEqual(run_id, 1)
        self.assertEqual(len(adapter.executed_jobs), 3)
        self.assertTrue(all(job.insert_rows_limit == 555 for job in adapter.executed_jobs))

    def test_sequential_mode_uses_dedicated_variant_caps_for_types_and_indexes(self) -> None:
        """Проверяет, что cap генерации типов/индексов не зависит от insert_operations_count."""
        benchmark = BenchmarkConfig(
            id="bench_sequential_stage_variant_caps",
            connection_id="prod_ch",
            strategy="sequential_topn_strategy",
            databases=["analytics"],
            tables=["events"],
            # Это число измерений, а не лимит числа variant jobs.
            max_iterations=3,
            sequential_top_n=1,
            max_benchmarks_limits=InsertRowsLimitsConfig(
                types=2,
                indexes=4,
            ),
            global_rules=RulesConfig(
                column_rules=[
                    ColumnRuleConfig(
                        by_type="UInt64",
                        by_name="user_id",
                        types=["UInt64", "UInt32"],
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
                    ),
                    IndexRuleConfig(
                        by_type="Nullable(Decimal(18,4))",
                        by_name="revenue",
                        indexes=[
                            IndexConfig(type="set(128)", granularity=2),
                            IndexConfig(type="bloom_filter(0.01)", granularity=2),
                        ],
                    ),
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
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=adapter,
            result_store=InMemoryBenchmarkResultStore(),
        )

        run_id = runner.run()
        self.assertEqual(run_id, 1)
        type_jobs = [job for job in adapter.executed_jobs if job.variant_meta.mode == "types"]
        index_jobs = [job for job in adapter.executed_jobs if job.variant_meta.mode == "indexes"]
        self.assertEqual(len(type_jobs), 2)
        self.assertEqual(len(index_jobs), 4)


if __name__ == "__main__":
    unittest.main()
