"""
Модуль оркестрации слоёв бенчмарка (planner -> engine -> runner).

Поток данных в этом модуле:
  1) `BenchmarkPlanner` разворачивает JSON-конфиг в table-level планы;
  2) `BenchmarkEngine` по каждому плану строит DDL-варианты и query-планы;
  3) `BenchmarkRunner` передаёт VariantJob в адаптер фактического выполнения.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Tuple
from uuid import uuid4

import src.benchmark_runtime.implementations.table_strategy.sequential_phased_topn as sequential_phased_topn_strategy_impl
from src.clickhouse_ddl import TableDDL
from src.combiner import VariantMeta, iter_variants, total_variants
from src.models import (
    BenchmarkConfig,
    BenchmarkMode,
    ScoringConfig,
    BenchmarkStrategy,
    BenchmarkRootConfig,
    ConnectionConfig,
    InsertRowsLimitsConfig,
    STRATEGY_TO_MODE,
    QueriesConfig,
    TableRuleConfig,
)
from src.benchmark_runtime.execution import BenchmarkExecutionAdapter, NoopExecutionAdapter
from src.benchmark_runtime.metadata import FetcherMetadataProvider, MetadataProvider
from src.benchmark_runtime.result_store import (
    BenchmarkResultStore,
    InMemoryBenchmarkResultStore,
)
from src.benchmark_runtime.run_id import (
    BenchmarkRunIdProvider,
    InMemoryBenchmarkRunIdProvider,
    MaxIdBenchmarkRunIdProvider,
)
from src.benchmark_runtime.table_strategy import (
    CombinedTableExecutionStrategy,
    DefaultTableExecutionStrategy,
    IndexesTableExecutionStrategy,
    SequentialPhasedTopNTableExecutionStrategy,
    SequentialTopNTableExecutionStrategy,
    TableExecutionStrategy,
    TypesTableExecutionStrategy,
)
from src.benchmark_runtime.types import (
    BenchmarkVariantResult,
    Query,
    QueryPlan,
    SourceBenchmarkJob,
    SourceBenchmarkResult,
    StoredBenchmarkResult,
    TableBenchmarkPlan,
    TableTarget,
    TopTypeVariant,
    VariantJob,
)
from src.naming import variant_table_name
from src.query_generator import generate_queries
from src.resolver import RuleResolver
from src.scoring_validation import collect_scoring_formula_issues

logger = logging.getLogger(__name__)


def _log_runner_build_metadata(
    *,
    benchmark_run_id: int,
    run_started_at: datetime,
) -> None:
    """Пишет build metadata в лог на старте BenchmarkRunner.run()."""
    build_date = os.getenv("BENCH_BUILD_DATETIME") or run_started_at.isoformat()
    git_commit = os.getenv("BENCH_GIT_COMMIT") or "unknown"
    git_branch = os.getenv("BENCH_GIT_BRANCH") or "unknown"

    logger.info("=== Build metadata ===")
    logger.info("Build date: %s", build_date)
    logger.info("Git commit: %s", git_commit)
    logger.info("Git branch: %s", git_branch)
    logger.info("Benchmark run id: %d", benchmark_run_id)
    logger.info("======================")


class TableSelector:
    """
    Разворачивает селекторы из `BenchmarkConfig` в список `TableTarget`.

    Поддерживает все варианты:
      - `databases="*"`/`tables="*"`;
      - ручной список БД;
      - ручной список таблиц (общий или словарь по БД).
    """

    def select_targets(
        self,
        benchmark: BenchmarkConfig,
        provider: MetadataProvider,
    ) -> List[TableTarget]:
        """Возвращает список таблиц без дубликатов для конкретного benchmark."""
        databases = self._resolve_databases(benchmark, provider)
        targets = self._resolve_tables(benchmark, databases, provider)
        deduplicated = self._deduplicate(targets)
        logger.debug(
            "TableSelector: benchmark=%s, databases=%d, targets=%d",
            benchmark.id,
            len(databases),
            len(deduplicated),
        )
        return deduplicated

    @staticmethod
    def _resolve_databases(
        benchmark: BenchmarkConfig, provider: MetadataProvider
    ) -> List[str]:
        """Разрешает селектор `databases` в конкретный список имён БД."""
        if benchmark.databases == "*":
            return provider.list_databases()
        return list(benchmark.databases)

    @staticmethod
    def _resolve_tables(
        benchmark: BenchmarkConfig,
        databases: List[str],
        provider: MetadataProvider,
    ) -> List[TableTarget]:
        """Разрешает селектор `tables` для уже выбранного списка БД."""
        selector = benchmark.tables
        targets: List[TableTarget] = []

        if selector == "*":
            for database in databases:
                for table in provider.list_tables(database):
                    targets.append(TableTarget(database=database, table=table))
            return targets

        if isinstance(selector, list):
            for database in databases:
                for table in selector:
                    targets.append(TableTarget(database=database, table=table))
            return targets

        for database in databases:
            table_selector = selector.get(database)
            if table_selector is None:
                continue
            if table_selector == "*":
                table_names = provider.list_tables(database)
            else:
                table_names = table_selector
            for table in table_names:
                targets.append(TableTarget(database=database, table=table))
        return targets

    @staticmethod
    def _deduplicate(targets: List[TableTarget]) -> List[TableTarget]:
        """Удаляет дубли `(database, table)` при объединении разных селекторов."""
        seen: set[Tuple[str, str]] = set()
        result: List[TableTarget] = []
        for target in targets:
            key = (target.database, target.table)
            if key in seen:
                continue
            seen.add(key)
            result.append(target)
        return result


class QueryPlanBuilder:
    """
    Строит план запросов для одной таблицы на основе `QueriesConfig`.

    Сначала формирует набор запросов с шаблоном `{table}`,
    затем этот шаблон подставляется в имя конкретной variant-таблицы.
    """

    def build(self, table_ddl: TableDDL, queries_config: QueriesConfig) -> QueryPlan:
        """
        Собирает сырой план запросов (ещё без подстановки имени таблицы).

        В режиме `auto` использует `query_generator`,
        в `manual` — только пользовательские запросы,
        в `auto_with_manual` — объединяет оба набора.
        """
        mode = queries_config.mode

        auto_queries = [
            Query(
                query_id=f"auto_query_{index}",
                query=q.query,
                cache_mode="warm",
            )
            for index, q in enumerate(generate_queries(table_ddl))
        ]
        manual_queries = [
            Query(
                query_id=q.query_id or f"manual_query_{index}",
                query=q.query,
                cache_mode=q.cache_mode,
                select_operations_count=q.select_operations_count,
                warmup_queries=list(q.warmup_queries),
            )
            for index, q in enumerate(queries_config.test_queries)
        ]

        if mode == "auto":
            tests = auto_queries
        elif mode == "manual":
            tests = manual_queries
        else:
            tests = auto_queries + manual_queries

        plan = QueryPlan(test_queries=self._ensure_unique_query_ids(tests))
        logger.debug(
            "QueryPlanBuilder: table=%s, mode=%s, tests=%d",
            table_ddl.name,
            queries_config.mode,
            len(plan.test_queries),
        )
        return plan

    @staticmethod
    def _ensure_unique_query_ids(queries: List[Query]) -> List[Query]:
        """Гарантирует уникальность query_id в финальном query-plan."""
        seen: set[str] = set()
        normalized: list[Query] = []
        for index, query in enumerate(queries):
            candidate = query.query_id.strip() if query.query_id.strip() else f"query_{index}"
            if candidate not in seen:
                seen.add(candidate)
                normalized.append(query.model_copy(update={"query_id": candidate}))
                continue

            suffix = 1
            while f"{candidate}_{suffix}" in seen:
                suffix += 1
            deduplicated_id = f"{candidate}_{suffix}"
            seen.add(deduplicated_id)
            normalized.append(query.model_copy(update={"query_id": deduplicated_id}))
        return normalized

    @staticmethod
    def render_for_table(
        plan: QueryPlan,
        database: str,
        table: str,
        benchmark_id: str = "",
    ) -> QueryPlan:
        """
        Подставляет реальное имя таблицы в каждый запрос плана.

        Используется перед отправкой `VariantJob` в execution-адаптер.
        """
        full_table_name = f"`{database}`.`{table}`"
        benchmark_id_value = benchmark_id

        def _render_sql(sql: str) -> str:
            return (
                sql.replace("{table}", full_table_name)
                .replace("{benchmark_id}", benchmark_id_value)
            )

        tests = [
            Query(
                query_id=planned.query_id,
                query=_render_sql(planned.query),
                cache_mode=planned.cache_mode,
                select_operations_count=planned.select_operations_count,
                warmup_queries=[_render_sql(warmup_query) for warmup_query in planned.warmup_queries],
            )
            for planned in plan.test_queries
        ]
        return QueryPlan(test_queries=tests)


class BenchmarkPlanner:
    """
    Формирует table-level планы из корневого конфига.

    На этом этапе происходит ключевой merge:
      - выбор целевых таблиц;
      - merge global/local rules;
      - выбор strategy/insert_operations_count/queries с учетом table override;
      - привязка глобального celery-конфига.
    """

    def __init__(
        self,
        config: BenchmarkRootConfig,
        providers_by_connection_id: Dict[str, MetadataProvider],
        table_selector: Optional[TableSelector] = None,
        rule_resolver: Optional[RuleResolver] = None,
    ) -> None:
        """Инициализирует planner и фиксирует доступные metadata providers."""
        self._config = config
        self._providers = dict(providers_by_connection_id)
        self._connections: Dict[str, ConnectionConfig] = {
            conn.id: conn for conn in config.connections
        }
        self._table_selector = table_selector or TableSelector()
        self._rule_resolver = rule_resolver or RuleResolver(
            banks=config.rule_banks,
            default_rule_banks=config.default_rule_banks,
        )

    def provider_for_connection(self, connection_id: str) -> MetadataProvider:
        """Возвращает provider по `connection_id` или бросает понятную ошибку."""
        if connection_id not in self._providers:
            raise ValueError(
                f"MetadataProvider для connection_id={connection_id!r} не зарегистрирован"
            )
        return self._providers[connection_id]

    def iter_table_plans(
        self,
        benchmark_ids: Optional[Sequence[str]] = None,
    ) -> Iterator[TableBenchmarkPlan]:
        """
        Итерирует планы уровня таблиц для выбранных benchmark_id.

        Это последняя стадия перед генерацией вариантов DDL:
        дальше engine работает уже только с `TableBenchmarkPlan`.
        """
        benchmark_filter = set(benchmark_ids) if benchmark_ids else None
        ordered_benchmarks = sorted(self._config.benchmarks, key=lambda b: b.id)

        for benchmark in ordered_benchmarks:
            if benchmark_filter and benchmark.id not in benchmark_filter:
                continue

            connection = self._connections[benchmark.connection_id]
            provider = self.provider_for_connection(benchmark.connection_id)
            table_targets = self._table_selector.select_targets(benchmark, provider)

            for target in table_targets:
                table_rule = self._find_table_rule(benchmark, target)
                merged_rules = self._rule_resolver.merge(
                    benchmark.global_rules,
                    table_rule.rules if table_rule else None,
                )
                resolved_rules = self._rule_resolver.resolve(
                    merged_rules,
                    dbms=connection.dbms,
                    column_rules_mode=benchmark.column_rules_mode,
                    index_rules_mode=benchmark.index_rules_mode,
                    global_rules=benchmark.global_rules,
                )

                if not resolved_rules.column_rules and not resolved_rules.index_rules:
                    raise ValueError(
                        f"benchmark={benchmark.id!r}, table={target.database}.{target.table}: "
                        "не найдено ни column_rules, ни index_rules "
                        "(укажи правила или default_rule_banks)"
                    )

                mode: BenchmarkMode = (
                    self._resolve_mode(benchmark=benchmark, table_rule=table_rule)
                )
                strategy: BenchmarkStrategy = (
                    self._resolve_strategy(benchmark=benchmark, table_rule=table_rule)
                )
                insert_operations_count = (
                    table_rule.insert_operations_count
                    if table_rule and table_rule.insert_operations_count is not None
                    else benchmark.insert_operations_count
                )
                sequential_top_n = (
                    table_rule.sequential_top_n
                    if table_rule and table_rule.sequential_top_n is not None
                    else benchmark.sequential_top_n
                )
                sequential_top_n_limits = self._merge_insert_rows_limits(
                    benchmark_insert_rows_limits=benchmark.sequential_top_n_limits,
                    table_insert_rows_limits=(
                        table_rule.sequential_top_n_limits if table_rule else None
                    ),
                )
                final_validation_input_top_n = (
                    table_rule.final_validation_input_top_n
                    if table_rule and table_rule.final_validation_input_top_n is not None
                    else benchmark.final_validation_input_top_n
                )
                max_winners_per_parent_limits = self._merge_insert_rows_limits(
                    benchmark_insert_rows_limits=benchmark.max_winners_per_parent_limits,
                    table_insert_rows_limits=(
                        table_rule.max_winners_per_parent_limits if table_rule else None
                    ),
                )
                insert_rows_limit = (
                    table_rule.insert_rows_limit
                    if table_rule and table_rule.insert_rows_limit is not None
                    else benchmark.insert_rows_limit
                )
                source_insert_rows_limit = (
                    table_rule.source_insert_rows_limit
                    if table_rule and table_rule.source_insert_rows_limit is not None
                    else benchmark.source_insert_rows_limit
                )
                source_insert_rows_limits = self._merge_insert_rows_limits(
                    benchmark_insert_rows_limits=benchmark.source_insert_rows_limits,
                    table_insert_rows_limits=(
                        table_rule.source_insert_rows_limits if table_rule else None
                    ),
                )
                index_granularity_values = (
                    table_rule.index_granularity_values
                    if table_rule and table_rule.index_granularity_values is not None
                    else benchmark.index_granularity_values
                )
                max_benchmarks_limits = self._merge_insert_rows_limits(
                    benchmark_insert_rows_limits=benchmark.max_benchmarks_limits,
                    table_insert_rows_limits=(
                        table_rule.max_benchmarks_limits if table_rule else None
                    ),
                )
                insert_rows_limits = self._merge_insert_rows_limits(
                    benchmark_insert_rows_limits=benchmark.insert_rows_limits,
                    table_insert_rows_limits=(
                        table_rule.insert_rows_limits if table_rule else None
                    ),
                )
                column_order_mode = (
                    table_rule.column_order_mode
                    if table_rule and table_rule.column_order_mode is not None
                    else benchmark.column_order_mode
                )
                queries = (
                    table_rule.queries
                    if table_rule and table_rule.queries is not None
                    else benchmark.queries
                )
                test_database = (
                    table_rule.test_database
                    if table_rule and table_rule.test_database is not None
                    else benchmark.test_database
                )
                scoring = self._resolve_scoring(
                    benchmark=benchmark,
                    table_rule=table_rule,
                )
                order_by_first = (
                    table_rule.order_by_first
                    if table_rule and table_rule.order_by_first is not None
                    else benchmark.order_by_first
                )
                order_by_candidates = (
                    list(table_rule.order_by_candidates)
                    if table_rule and table_rule.order_by_candidates is not None
                    else (
                        list(benchmark.order_by_candidates)
                        if benchmark.order_by_candidates is not None
                        else None
                    )
                )
                if order_by_first is None:
                    order_by_first = resolved_rules.order_by_first
                if order_by_candidates is None and resolved_rules.order_by_candidates is not None:
                    order_by_candidates = list(resolved_rules.order_by_candidates)
                order_by_auto_generate_candidates = (
                    resolved_rules.order_by_auto_generate_candidates
                )

                yield TableBenchmarkPlan(
                    benchmark_id=benchmark.id,
                    connection_id=connection.id,
                    connection_dbms=connection.dbms,
                    database=target.database,
                    test_database=test_database,
                    table=target.table,
                    strategy=strategy,
                    mode=mode,
                    insert_operations_count=insert_operations_count,
                    sequential_top_n=sequential_top_n,
                    sequential_top_n_limits=sequential_top_n_limits,
                    final_validation_input_top_n=final_validation_input_top_n,
                    max_winners_per_parent_limits=max_winners_per_parent_limits,
                    insert_rows_limit=insert_rows_limit,
                    source_insert_rows_limit=source_insert_rows_limit,
                    source_insert_rows_limits=source_insert_rows_limits,
                    insert_rows_limits=insert_rows_limits,
                    max_benchmarks_limits=max_benchmarks_limits,
                    index_granularity_values=index_granularity_values,
                    column_order_mode=column_order_mode,
                    order_by_first=order_by_first,
                    order_by_candidates=order_by_candidates,
                    order_by_auto_generate_candidates=order_by_auto_generate_candidates,
                    scoring=scoring,
                    rules=resolved_rules,
                    queries=queries,
                    celery=self._config.celery,
                )
                logger.debug(
                    "BenchmarkPlanner: table plan создан "
                    "(benchmark=%s, strategy=%s, mode=%s, table=%s.%s, test_db=%s)",
                    benchmark.id,
                    strategy,
                    mode,
                    target.database,
                    target.table,
                    test_database or target.database,
                )

    def iter_benchmarks(
        self,
        benchmark_ids: Optional[Sequence[str]] = None,
    ) -> Iterator[BenchmarkConfig]:
        """Итерирует benchmark-конфиги с учётом фильтра benchmark_ids."""
        benchmark_filter = set(benchmark_ids) if benchmark_ids else None
        for benchmark in sorted(self._config.benchmarks, key=lambda b: b.id):
            if benchmark_filter and benchmark.id not in benchmark_filter:
                continue
            yield benchmark

    @staticmethod
    def _find_table_rule(
        benchmark: BenchmarkConfig,
        target: TableTarget,
    ) -> Optional[TableRuleConfig]:
        """Ищет table-level override для конкретной таблицы."""
        for table_rule in benchmark.table_rules:
            if table_rule.database == target.database and table_rule.table == target.table:
                return table_rule
        return None

    @staticmethod
    def _merge_insert_rows_limits(
        benchmark_insert_rows_limits: Optional[InsertRowsLimitsConfig],
        table_insert_rows_limits: Optional[InsertRowsLimitsConfig],
    ) -> Optional[InsertRowsLimitsConfig]:
        """Объединяет table-level mode-лимиты поверх benchmark-level mode-лимитов."""
        if table_insert_rows_limits is not None:
            return table_insert_rows_limits.merged_over(benchmark_insert_rows_limits)
        if benchmark_insert_rows_limits is not None:
            return benchmark_insert_rows_limits.model_copy(deep=True)
        return None

    @staticmethod
    def _resolve_strategy(
        benchmark: BenchmarkConfig,
        table_rule: Optional[TableRuleConfig],
    ) -> BenchmarkStrategy:
        """
        Возвращает эффективную strategy для таблицы.

        Приоритет:
          1) table_rule.strategy;
          2) benchmark.strategy.
        """
        if table_rule is not None:
            if table_rule.strategy is not None:
                return table_rule.strategy
        return benchmark.strategy

    @staticmethod
    def _resolve_mode(
        benchmark: BenchmarkConfig,
        table_rule: Optional[TableRuleConfig],
    ) -> BenchmarkMode:
        """Возвращает эффективный режим комбинатора для выбранной strategy."""
        strategy = BenchmarkPlanner._resolve_strategy(
            benchmark=benchmark,
            table_rule=table_rule,
        )
        return STRATEGY_TO_MODE[strategy]

    @staticmethod
    def _resolve_scoring(
        benchmark: BenchmarkConfig,
        table_rule: Optional[TableRuleConfig],
    ) -> ScoringConfig:
        """
        Возвращает эффективный scoring-конфиг для таблицы.

        Приоритет:
          1) table_rule.scoring;
          2) benchmark.scoring.
        """
        if table_rule is not None and table_rule.scoring is not None:
            return table_rule.scoring.model_copy(deep=True)
        return benchmark.scoring.model_copy(deep=True)


class BenchmarkEngine:
    """
    Преобразует `TableBenchmarkPlan` в поток `VariantJob`.

    Для каждой исходной таблицы:
      1) читает исходный DDL;
      2) генерирует DDL-варианты через combiner;
      3) готовит план запросов для каждой variant-таблицы.
    """

    def __init__(
        self,
        planner: BenchmarkPlanner,
        query_builder: Optional[QueryPlanBuilder] = None,
    ) -> None:
        """Принимает planner и опциональный билдер query-плана."""
        self._planner = planner
        self._query_builder = query_builder or QueryPlanBuilder()

    def iter_table_plans(
        self,
        benchmark_ids: Optional[Sequence[str]] = None,
    ) -> Iterator[TableBenchmarkPlan]:
        """Проксирует table-level планы из planner для runner-оркестрации."""
        yield from self._planner.iter_table_plans(benchmark_ids=benchmark_ids)

    def iter_benchmarks(
        self,
        benchmark_ids: Optional[Sequence[str]] = None,
    ) -> Iterator[BenchmarkConfig]:
        """Проксирует benchmark-конфиги из planner."""
        yield from self._planner.iter_benchmarks(benchmark_ids=benchmark_ids)

    def prepare_table_context(
        self,
        table_plan: TableBenchmarkPlan,
    ) -> Tuple[TableDDL, QueryPlan]:
        """Загружает исходный DDL и строит план запросов с шаблоном `{table}`."""
        provider = self._planner.provider_for_connection(table_plan.connection_id)
        source_ddl = provider.fetch_table_ddl(
            database=table_plan.database,
            table=table_plan.table,
        )
        raw_query_plan = self._query_builder.build(source_ddl, table_plan.queries)
        logger.debug(
            "BenchmarkEngine: подготовлен table context "
            "(benchmark=%s, table=%s.%s, strategy=%s)",
            table_plan.benchmark_id,
            table_plan.database,
            table_plan.table,
            table_plan.strategy,
        )
        return source_ddl, raw_query_plan

    def build_source_benchmark_job(
        self,
        table_plan: TableBenchmarkPlan,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
    ) -> SourceBenchmarkJob:
        """
        Собирает baseline-job для исходного DDL таблицы.

        Этот job выполняется перед генерацией variant jobs и его результат
        прокидывается в каждый `VariantJob` как `source_benchmark`.
        """
        source_ddl, raw_query_plan = self.prepare_table_context(table_plan)
        prepared_source_ddl = source_ddl.copy()
        prepared_source_ddl.name = f"{table_plan.database}.{table_plan.table}"
        rendered_query_plan = self._query_builder.render_for_table(
            plan=raw_query_plan,
            database=table_plan.database,
            table=table_plan.table,
            benchmark_id=table_plan.benchmark_id,
        )
        source_insert_rows_limit = None
        if table_plan.source_insert_rows_limits is not None:
            source_insert_rows_limit = table_plan.source_insert_rows_limits.for_mode(
                table_plan.mode
            )
        if source_insert_rows_limit is None:
            source_insert_rows_limit = table_plan.source_insert_rows_limit
        if source_insert_rows_limit is None:
            source_insert_rows_limit = self.resolve_insert_rows_limit(
                table_plan=table_plan,
                variant_mode=table_plan.mode,
                job_mode=table_plan.mode,
            )
        logger.debug(
            "BenchmarkEngine: source baseline job собран "
            "(benchmark=%s, table=%s.%s, run_id=%d, source_insert_rows_limit=%s)",
            table_plan.benchmark_id,
            table_plan.database,
            table_plan.table,
            benchmark_run_id,
            source_insert_rows_limit,
        )

        return SourceBenchmarkJob(
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
            benchmark_id=table_plan.benchmark_id,
            benchmark_strategy=table_plan.strategy,
            connection_id=table_plan.connection_id,
            connection_dbms=table_plan.connection_dbms,
            source_database=table_plan.database,
            test_database=table_plan.test_database,
            source_table=table_plan.table,
            source_table_ddl=prepared_source_ddl,
            query_plan=rendered_query_plan,
            insert_operations_count=table_plan.insert_operations_count,
            insert_rows_limit=source_insert_rows_limit,
            scoring=table_plan.scoring,
            celery=table_plan.celery,
        )

    def resolve_column_order(
        self,
        table_plan: TableBenchmarkPlan,
        source_ddl: TableDDL,
    ) -> Dict[str, int]:
        """
        Возвращает эффективный `column_order` для текущей таблицы.

        Если включён `column_order_mode="compressed_size_desc"`, порядок колонок
        строится автоматически по убыванию сжатого размера колонки в исходной
        таблице (`provider.fetch_column_sizes`). Иначе используется order из правил.
        """
        configured_order = dict(table_plan.rules.column_order)
        if table_plan.column_order_mode != "compressed_size_desc":
            return configured_order

        provider = self._planner.provider_for_connection(table_plan.connection_id)
        column_sizes = provider.fetch_column_sizes(
            database=table_plan.database,
            table=table_plan.table,
        )
        if not column_sizes:
            return configured_order

        matched_columns: List[str] = []
        for column in source_ddl.columns:
            matched_by_column_rule = any(
                rule.matches(column) for rule in table_plan.rules.column_rules
            )
            matched_by_index_rule = any(
                rule.matches(column) for rule in table_plan.rules.index_rules
            )
            if matched_by_column_rule or matched_by_index_rule:
                matched_columns.append(column.name)

        if not matched_columns:
            return configured_order

        ranked_columns = sorted(
            matched_columns,
            key=lambda name: (-int(column_sizes.get(name, 0)), name),
        )
        return {name: idx + 1 for idx, name in enumerate(ranked_columns)}

    def build_variant_job(
        self,
        table_plan: TableBenchmarkPlan,
        raw_query_plan: QueryPlan,
        variant_ddl: TableDDL,
        variant_meta: VariantMeta,
        total_variants: int,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
        job_mode: Optional[BenchmarkMode] = None,
        source_benchmark: Optional[SourceBenchmarkResult] = None,
    ) -> VariantJob:
        """Собирает `VariantJob` из подготовленного variant DDL и его метаданных."""
        effective_variant_meta = variant_meta
        if not str(variant_meta.execution_uuid or "").strip():
            effective_variant_meta = variant_meta.model_copy(
                update={"execution_uuid": uuid4().hex}
            )

        variant_database = table_plan.test_database or table_plan.database
        variant_table = variant_table_name(
            original_table=table_plan.table,
            benchmark_id=table_plan.benchmark_id,
            variant_index=effective_variant_meta.global_index,
        )
        prepared_ddl = variant_ddl.copy()
        prepared_ddl.name = f"{variant_database}.{variant_table}"

        rendered_query_plan = self._query_builder.render_for_table(
            plan=raw_query_plan,
            database=variant_database,
            table=variant_table,
            benchmark_id=table_plan.benchmark_id,
        )

        effective_insert_rows_limit = self.resolve_insert_rows_limit(
            table_plan=table_plan,
            variant_mode=effective_variant_meta.mode,
            job_mode=job_mode,
        )

        return VariantJob(
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
            benchmark_id=table_plan.benchmark_id,
            benchmark_strategy=table_plan.strategy,
            connection_id=table_plan.connection_id,
            connection_dbms=table_plan.connection_dbms,
            source_database=table_plan.database,
            variant_database=variant_database,
            source_table=table_plan.table,
            variant_table=variant_table,
            variant_meta=effective_variant_meta,
            mode=job_mode if job_mode is not None else table_plan.mode,
            insert_operations_count=table_plan.insert_operations_count,
            insert_rows_limit=effective_insert_rows_limit,
            total_variants=total_variants,
            variant_ddl=prepared_ddl,
            source_benchmark=source_benchmark,
            query_plan=rendered_query_plan,
            scoring=table_plan.scoring,
            celery=table_plan.celery,
        )

    @staticmethod
    def resolve_insert_rows_limit(
        table_plan: TableBenchmarkPlan,
        variant_mode: str,
        job_mode: Optional[BenchmarkMode] = None,
    ) -> Optional[int]:
        """
        Возвращает итоговый лимит вставки строк для конкретного variant job.

        Приоритет:
          1) `insert_rows_limits[variant_mode]`;
          2) `insert_rows_limits[job_mode or table_plan.mode]`;
          3) `insert_rows_limit` (общий fallback).
        """
        mode_limits = table_plan.insert_rows_limits
        if mode_limits is None:
            return table_plan.insert_rows_limit

        variant_mode_limit = mode_limits.for_mode(variant_mode)
        if variant_mode_limit is not None:
            return variant_mode_limit

        effective_job_mode = job_mode if job_mode is not None else table_plan.mode
        job_mode_limit = mode_limits.for_mode(effective_job_mode)
        if job_mode_limit is not None:
            return job_mode_limit

        return table_plan.insert_rows_limit

    @staticmethod
    def resolve_variant_generation_limit(
        table_plan: TableBenchmarkPlan,
        variant_mode: str,
        job_mode: Optional[BenchmarkMode] = None,
    ) -> Optional[int]:
        """
        Возвращает лимит числа variant jobs для указанной стадии генерации.

        Приоритет:
          1) `max_benchmarks_limits[variant_mode]`;
          2) `max_benchmarks_limits[job_mode or table_plan.mode]`;
          3) fallback `insert_operations_count`.
        """
        normalized_variant_mode = str(variant_mode).strip().lower()
        limits_by_mode = table_plan.max_benchmarks_limits
        if limits_by_mode is not None:
            variant_mode_limit = limits_by_mode.for_mode(normalized_variant_mode)
            if variant_mode_limit is not None:
                return variant_mode_limit
            effective_job_mode = job_mode if job_mode is not None else table_plan.mode
            job_mode_limit = limits_by_mode.for_mode(effective_job_mode)
            if job_mode_limit is not None:
                return job_mode_limit

        return table_plan.insert_operations_count

    def iter_variant_jobs_for_table_plan(
        self,
        table_plan: TableBenchmarkPlan,
        benchmark_run_id: int = 1,
        benchmark_started_at: Optional[datetime] = None,
        source_benchmark: Optional[SourceBenchmarkResult] = None,
    ) -> Iterator[VariantJob]:
        """
        Генерирует VariantJob для одного `TableBenchmarkPlan`.

        Для `sequential` здесь отдаётся только type/codec стадия.
        Индексная стадия зависит от score и оркестрируется в `BenchmarkRunner`.
        """
        run_started_at = benchmark_started_at or datetime.now(timezone.utc)
        source_ddl, raw_query_plan = self.prepare_table_context(table_plan)
        effective_column_order = self.resolve_column_order(table_plan, source_ddl)
        variant_mode: BenchmarkMode = (
            "types" if table_plan.mode == "sequential" else table_plan.mode
        )
        variant_generation_limit = self.resolve_variant_generation_limit(
            table_plan=table_plan,
            variant_mode=variant_mode,
        )
        capped_total = total_variants(
            table=source_ddl,
            mode=variant_mode,
            column_rules=table_plan.rules.column_rules,
            index_rules=table_plan.rules.index_rules,
            column_order=effective_column_order,
            table_index_granularity_values=table_plan.index_granularity_values,
            max_iterations=variant_generation_limit,
        )
        logger.info(
            "BenchmarkEngine: генерация variant jobs "
            "(benchmark=%s, strategy=%s, mode=%s, table=%s.%s, total=%d)",
            table_plan.benchmark_id,
            table_plan.strategy,
            variant_mode,
            table_plan.database,
            table_plan.table,
            capped_total,
        )
        if capped_total == 0:
            logger.warning(
                "BenchmarkEngine: нет вариантов для table=%s.%s, benchmark=%s",
                table_plan.database,
                table_plan.table,
                table_plan.benchmark_id,
            )

        for variant_ddl, variant_meta in iter_variants(
            table=source_ddl,
            mode=variant_mode,
            column_rules=table_plan.rules.column_rules,
            index_rules=table_plan.rules.index_rules,
            column_order=effective_column_order,
            table_index_granularity_values=table_plan.index_granularity_values,
            max_iterations=variant_generation_limit,
        ):
            yield self.build_variant_job(
                table_plan=table_plan,
                raw_query_plan=raw_query_plan,
                variant_ddl=variant_ddl,
                variant_meta=variant_meta,
                total_variants=capped_total,
                benchmark_run_id=benchmark_run_id,
                benchmark_started_at=run_started_at,
                source_benchmark=source_benchmark,
            )

    def iter_variant_jobs(
        self,
        benchmark_ids: Optional[Sequence[str]] = None,
        benchmark_run_id: int = 1,
        benchmark_started_at: Optional[datetime] = None,
    ) -> Iterator[VariantJob]:
        """Итерирует полностью подготовленные задания на выполнение вариантов."""
        run_started_at = benchmark_started_at or datetime.now(timezone.utc)
        for table_plan in self.iter_table_plans(benchmark_ids=benchmark_ids):
            yield from self.iter_variant_jobs_for_table_plan(
                table_plan,
                benchmark_run_id=benchmark_run_id,
                benchmark_started_at=run_started_at,
            )


class BenchmarkRunner:
    """
    Верхнеуровневый фасад запуска бенчмарка.

    Объединяет генерацию заданий и их выполнение в один метод `run`.
    Для каждой strategy уровня таблицы выбирается реализация исполнения.
    """

    def __init__(
        self,
        engine: BenchmarkEngine,
        execution_adapter: BenchmarkExecutionAdapter,
        result_store: Optional[BenchmarkResultStore] = None,
        run_id_provider: Optional[BenchmarkRunIdProvider] = None,
        run_started_at_provider: Optional[Callable[[], datetime]] = None,
        table_execution_strategies: Optional[Dict[str, TableExecutionStrategy]] = None,
        default_table_execution_strategy: Optional[TableExecutionStrategy] = None,
    ) -> None:
        """
        Сохраняет engine и адаптер выполнения.

        `result_store` опционален. Он нужен стратегиям, которые читают top-N
        (например, `sequential_topn_strategy`).
        """
        self._engine = engine
        self._execution_adapter = execution_adapter
        self._result_store = result_store
        self._run_id_provider = run_id_provider or InMemoryBenchmarkRunIdProvider()
        self._run_started_at_provider = (
            run_started_at_provider or (lambda: datetime.now(timezone.utc))
        )
        self._last_benchmark_started_at: Optional[datetime] = None
        self._active_source_benchmark: Optional[SourceBenchmarkResult] = None
        self._execution_adapter.bind_result_store(result_store)
        self._default_table_execution_strategy = (
            default_table_execution_strategy or DefaultTableExecutionStrategy()
        )
        self._table_execution_strategies: Dict[str, TableExecutionStrategy] = {
            "types_strategy": TypesTableExecutionStrategy(),
            "indexes_strategy": IndexesTableExecutionStrategy(),
            "combined_strategy": CombinedTableExecutionStrategy(),
            "sequential_topn_strategy": SequentialTopNTableExecutionStrategy(),
            "sequential_phased_topn_strategy": SequentialPhasedTopNTableExecutionStrategy(),
        }
        if table_execution_strategies:
            for strategy_key, strategy in table_execution_strategies.items():
                self.register_table_execution_strategy(
                    strategy_key=strategy_key,
                    strategy=strategy,
                    overwrite=True,
                )

    def register_table_execution_strategy(
        self,
        strategy_key: str,
        strategy: TableExecutionStrategy,
        *,
        overwrite: bool = False,
    ) -> None:
        """
        Регистрирует стратегию выполнения уровня таблицы.

        Использует strategy-key из `BenchmarkConfig.strategy`.
        """
        normalized_strategy_key = self._canonical_strategy_key(strategy_key)
        if not normalized_strategy_key:
            raise ValueError("strategy key не должен быть пустым")
        if (
            normalized_strategy_key in self._table_execution_strategies
            and not overwrite
        ):
            raise ValueError(
                f"Стратегия выполнения для key={normalized_strategy_key!r} уже зарегистрирована. "
                "Используй overwrite=True для замены."
            )
        self._table_execution_strategies[normalized_strategy_key] = strategy
        logger.debug(
            "BenchmarkRunner: зарегистрирована table strategy key=%s (overwrite=%s)",
            normalized_strategy_key,
            overwrite,
        )

    def run(
        self,
        benchmark_ids: Optional[Sequence[str]] = None,
        benchmark_run_id: Optional[int] = None,
    ) -> int:
        """
        Выполняет все VariantJob и возвращает run-level `benchmark_run_id`.

        Для `strategy="sequential_topn_strategy"` используется двухфазный алгоритм:
          1) прогон type/codec-вариантов;
          2) выбор top-N через result-store и прогон индексных вариантов на их DDL.

        Для каждого вызова фиксируется единый `benchmark_started_at` (UTC datetime),
        общий для всех benchmark/table/jobs в рамках этого запуска.

        Перед исполнением любой strategy для таблицы runner всегда запускает
        baseline-бенчмарк исходного DDL (`execute_source_benchmark`) и затем
        прокидывает его результат в каждый `VariantJob.source_benchmark`.
        """
        self._validate_scoring_formulas_before_run(benchmark_ids=benchmark_ids)
        run_id = benchmark_run_id if benchmark_run_id is not None else self._next_run_id()
        if run_id <= 0:
            raise ValueError(f"benchmark_run_id должен быть > 0, получено: {run_id}")
        run_started_at = self._next_run_started_at()
        self._last_benchmark_started_at = run_started_at
        _log_runner_build_metadata(
            benchmark_run_id=run_id,
            run_started_at=run_started_at,
        )
        logger.info(
            "BenchmarkRunner: старт run (run_id=%d, started_at=%s, benchmark_ids=%s)",
            run_id,
            run_started_at.isoformat(),
            list(benchmark_ids) if benchmark_ids else "all",
        )
        raw_fixed_global_progress = os.getenv("BENCH_GLOBAL_PROGRESS_FIXED_TOTAL", "").strip()
        fixed_global_progress_enabled: Optional[bool]
        if not raw_fixed_global_progress:
            fixed_global_progress_enabled = None
        elif raw_fixed_global_progress.lower() in {"1", "true", "yes", "on"}:
            fixed_global_progress_enabled = True
        elif raw_fixed_global_progress.lower() in {"0", "false", "no", "off"}:
            fixed_global_progress_enabled = False
        else:
            fixed_global_progress_enabled = None
        if fixed_global_progress_enabled is None:
            fixed_global_progress_enabled = not self._contains_phased_strategy(
                benchmark_ids=benchmark_ids
            )
        global_progress_total: Optional[int] = None
        if fixed_global_progress_enabled:
            global_progress_total = self._estimate_global_progress_target(
                benchmark_ids=benchmark_ids
            )
            logger.info(
                "BenchmarkRunner: global progress mode=fixed (target=%d)",
                global_progress_total,
            )
        else:
            logger.info("BenchmarkRunner: global progress mode=dynamic")
        open_global_progress_hook = getattr(
            self._execution_adapter,
            "open_global_progress_scope",
            None,
        )
        if callable(open_global_progress_hook):
            scope_name = (
                f"GLOBAL run {run_id}: "
                f"{','.join(benchmark_ids) if benchmark_ids else 'all'}"
            )
            try:
                open_global_progress_hook(
                    scope_name=scope_name,
                    total_tasks=global_progress_total,
                )
            except TypeError as exc:
                if "total_tasks" not in str(exc):
                    raise
                open_global_progress_hook(scope_name=scope_name)

        try:
            for table_plan in self._engine.iter_table_plans(benchmark_ids=benchmark_ids):
                strategy_key = self._canonical_strategy_key(table_plan.strategy)
                strategy = self._table_execution_strategies.get(
                    strategy_key,
                    self._default_table_execution_strategy,
                )
                logger.info(
                    "BenchmarkRunner: старт table plan "
                    "(run_id=%d, benchmark=%s, table=%s.%s, strategy=%s)",
                    run_id,
                    table_plan.benchmark_id,
                    table_plan.database,
                    table_plan.table,
                    strategy_key,
                )
                self._active_source_benchmark = self._execute_source_benchmark(
                    table_plan=table_plan,
                    benchmark_run_id=run_id,
                    benchmark_started_at=run_started_at,
                )
                try:
                    self._register_benchmark_run_start_if_supported(
                        table_plan=table_plan,
                        benchmark_run_id=run_id,
                        benchmark_started_at=run_started_at,
                        source_benchmark=self._active_source_benchmark,
                    )
                    if self._is_source_benchmark_skipped(self._active_source_benchmark):
                        logger.warning(
                            "BenchmarkRunner: table plan пропущен, baseline сообщил skip "
                            "(run_id=%d, benchmark=%s, table=%s.%s, reason=%s)",
                            run_id,
                            table_plan.benchmark_id,
                            table_plan.database,
                            table_plan.table,
                            self._active_source_benchmark.metrics.get("skip_reason", "unknown"),
                        )
                        continue
                    strategy.execute_table(
                        runner=self,
                        table_plan=table_plan,
                        benchmark_run_id=run_id,
                        benchmark_started_at=run_started_at,
                    )
                    logger.info(
                        "BenchmarkRunner: завершён table plan "
                        "(run_id=%d, benchmark=%s, table=%s.%s)",
                        run_id,
                        table_plan.benchmark_id,
                        table_plan.database,
                        table_plan.table,
                    )
                finally:
                    self._register_benchmark_run_finish_if_supported(
                        table_plan=table_plan,
                        benchmark_run_id=run_id,
                    )
                    finalize_progress_hook = getattr(
                        self._execution_adapter,
                        "finalize_progress_scope",
                        None,
                    )
                    if callable(finalize_progress_hook):
                        finalize_progress_hook(wait=False)
                    self._active_source_benchmark = None
        finally:
            finalize_global_progress_hook = getattr(
                self._execution_adapter,
                "finalize_global_progress_scope",
                None,
            )
            if callable(finalize_global_progress_hook):
                finalize_global_progress_hook(wait=False)
        logger.info("BenchmarkRunner: run завершён (run_id=%d)", run_id)
        return run_id

    @property
    def last_benchmark_started_at(self) -> Optional[datetime]:
        """Возвращает стартовое время последнего run-level запуска."""
        return self._last_benchmark_started_at

    def _execute_regular_table(
        self,
        table_plan: TableBenchmarkPlan,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
    ) -> None:
        """Стандартное выполнение table-plan: прогон всех VariantJob из engine."""
        source_benchmark = self._require_active_source_benchmark()
        dispatched_jobs = 0
        for job in self._engine.iter_variant_jobs_for_table_plan(
            table_plan,
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
            source_benchmark=source_benchmark,
        ):
            self._execute_and_store(job)
            dispatched_jobs += 1
        logger.info(
            "BenchmarkRunner: table plan dispatch завершён "
            "(run_id=%d, benchmark=%s, table=%s.%s, jobs=%d)",
            benchmark_run_id,
            table_plan.benchmark_id,
            table_plan.database,
            table_plan.table,
            dispatched_jobs,
        )

    def _execute_source_benchmark(
        self,
        table_plan: TableBenchmarkPlan,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
    ) -> SourceBenchmarkResult:
        """
        Выполняет baseline-бенчмарк исходного DDL для table-plan.

        Результат используется как контекст для всех variant jobs текущей таблицы.
        """
        logger.info(
            "BenchmarkRunner: запуск baseline "
            "(run_id=%d, benchmark=%s, table=%s.%s)",
            benchmark_run_id,
            table_plan.benchmark_id,
            table_plan.database,
            table_plan.table,
        )
        job = self._engine.build_source_benchmark_job(
            table_plan=table_plan,
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
        )
        result = self._execution_adapter.execute_source_benchmark(job)
        self._validate_source_benchmark_result(
            job=job,
            result=result,
        )
        logger.info(
            "BenchmarkRunner: baseline завершён "
            "(run_id=%d, benchmark=%s, table=%s.%s, baseline_id=%s, score=%s)",
            benchmark_run_id,
            table_plan.benchmark_id,
            table_plan.database,
            table_plan.table,
            result.baseline_id,
            result.score,
        )
        return result

    def _register_benchmark_run_start_if_supported(
        self,
        *,
        table_plan: TableBenchmarkPlan,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
        source_benchmark: SourceBenchmarkResult,
    ) -> None:
        """Регистрирует run-контекст (если store это поддерживает)."""
        if self._result_store is None:
            return
        metrics = source_benchmark.metrics or {}
        query_metrics = metrics.get("source_table_select_metrics_by_query", []) or []
        benchmark_queries: list[Query] = []
        for idx, payload in enumerate(query_metrics):
            if not isinstance(payload, dict):
                continue
            query_text = str(payload.get("query", "")).strip()
            if not query_text:
                continue
            select_operations_count: Optional[int] = None
            raw_select_operations_count = payload.get("select_operations_count")
            if raw_select_operations_count is not None:
                try:
                    select_operations_count = int(raw_select_operations_count)
                except Exception:
                    select_operations_count = None
            benchmark_queries.append(
                Query(
                    query_id=str(payload.get("query_id") or f"query_{idx}"),
                    query=query_text,
                    cache_mode=str(payload.get("cache_mode") or "warm"),
                    select_operations_count=select_operations_count,
                    warmup_queries=[
                        str(item)
                        for item in (payload.get("warmup_queries") or [])
                        if str(item).strip()
                    ],
                )
            )
        total_rows = metrics.get("total_n_rows_in_source_table")
        normalized_total_rows = int(total_rows) if total_rows is not None else None
        try:
            self._result_store.register_benchmark_run_start(
                benchmark_run_id=benchmark_run_id,
                benchmark_started_at=benchmark_started_at,
                table_plan=table_plan,
                source_table_ddl=source_benchmark.source_table_ddl,
                benchmark_queries=benchmark_queries,
                total_rows=normalized_total_rows,
                scoring=table_plan.scoring,
            )
        except Exception:
            logger.exception(
                "BenchmarkRunner: ошибка register_benchmark_run_start "
                "(run_id=%d, benchmark=%s, table=%s.%s)",
                benchmark_run_id,
                table_plan.benchmark_id,
                table_plan.database,
                table_plan.table,
            )

    def _register_benchmark_run_finish_if_supported(
        self,
        *,
        table_plan: TableBenchmarkPlan,
        benchmark_run_id: int,
    ) -> None:
        """Фиксирует завершение run-контекста (если store это поддерживает)."""
        if self._result_store is None:
            return
        try:
            self._result_store.register_benchmark_run_finish(
                benchmark_run_id=benchmark_run_id,
                table_plan=table_plan,
                benchmark_finished_at=datetime.now(timezone.utc),
            )
        except Exception:
            logger.exception(
                "BenchmarkRunner: ошибка register_benchmark_run_finish "
                "(run_id=%d, benchmark=%s, table=%s.%s)",
                benchmark_run_id,
                table_plan.benchmark_id,
                table_plan.database,
                table_plan.table,
            )

    def _require_active_source_benchmark(self) -> SourceBenchmarkResult:
        """Возвращает baseline-результат текущего table-plan или падает."""
        if self._active_source_benchmark is None:
            raise RuntimeError(
                "source benchmark context отсутствует: "
                "runner должен сначала выполнить _execute_source_benchmark"
            )
        return self._active_source_benchmark

    @staticmethod
    def _validate_source_benchmark_result(
        job: SourceBenchmarkJob,
        result: SourceBenchmarkResult,
    ) -> None:
        """Проверяет идентичность baseline-результата от execution adapter."""
        if result.benchmark_run_id != job.benchmark_run_id:
            raise ValueError(
                "source benchmark result.benchmark_run_id "
                "не совпадает с job.benchmark_run_id"
            )
        if result.benchmark_id != job.benchmark_id:
            raise ValueError(
                "source benchmark result.benchmark_id "
                "не совпадает с job.benchmark_id"
            )
        if result.source_database != job.source_database:
            raise ValueError(
                "source benchmark result.source_database "
                "не совпадает с job.source_database"
            )
        if result.source_table != job.source_table:
            raise ValueError(
                "source benchmark result.source_table "
                "не совпадает с job.source_table"
            )
        if (
            result.benchmark_started_at is not None
            and result.benchmark_started_at != job.benchmark_started_at
        ):
            raise ValueError(
                "source benchmark result.benchmark_started_at "
                "не совпадает с job.benchmark_started_at"
            )

    @staticmethod
    def _is_source_benchmark_skipped(result: SourceBenchmarkResult) -> bool:
        """Возвращает `True`, если baseline помечен как пропущенный."""
        status = result.metrics.get("status")
        if not isinstance(status, str):
            return False
        return status.strip().lower() == "skipped"

    @staticmethod
    def _canonical_strategy_key(raw_key: str) -> str:
        """Нормализует strategy key."""
        normalized = raw_key.strip()
        return normalized

    def _next_run_id(self) -> int:
        """Берёт следующий serial benchmark run id у настроенного provider."""
        return self._run_id_provider.next_benchmark_run_id()

    def _next_run_started_at(self) -> datetime:
        """
        Возвращает время старта всего run в UTC.

        Если provider вернул naive datetime, трактуем его как UTC.
        """
        started_at = self._run_started_at_provider()
        if started_at.tzinfo is None:
            return started_at.replace(tzinfo=timezone.utc)
        return started_at.astimezone(timezone.utc)

    def _estimate_global_progress_target(
        self,
        benchmark_ids: Optional[Sequence[str]],
    ) -> int:
        """
        Предварительно считает фиксированный максимум задач для global progress-bar.

        Важно: значение не меняется по ходу run. Для sequential top-N считается
        верхняя оценка stage2 (сумма крупнейших индексных веток для top-N).
        """
        total_jobs = 0
        for table_plan in self._engine.iter_table_plans(benchmark_ids=benchmark_ids):
            table_jobs = self._estimate_table_jobs_upper_bound(table_plan)
            total_jobs += max(0, table_jobs)
        logger.info(
            "BenchmarkRunner: предрасчёт global progress target (tasks=%d)",
            total_jobs,
        )
        return total_jobs

    def _contains_phased_strategy(
        self,
        *,
        benchmark_ids: Optional[Sequence[str]],
    ) -> bool:
        """Возвращает True, если среди выбранных benchmark есть phased-стратегия."""
        for benchmark in self._engine.iter_benchmarks(benchmark_ids=benchmark_ids):
            if self._canonical_strategy_key(benchmark.strategy) == "sequential_phased_topn_strategy":
                return True
        return False

    def _estimate_table_jobs_upper_bound(self, table_plan: TableBenchmarkPlan) -> int:
        """Считает верхнюю оценку числа variant jobs для одного table-plan."""
        strategy_key = self._canonical_strategy_key(table_plan.strategy)
        if strategy_key == "sequential_topn_strategy":
            return self._estimate_sequential_topn_jobs_upper_bound(table_plan=table_plan)
        if strategy_key == "sequential_phased_topn_strategy":
            return self._estimate_sequential_phased_topn_jobs_upper_bound(
                table_plan=table_plan
            )

        variant_mode: BenchmarkMode = (
            "types" if table_plan.mode == "sequential" else table_plan.mode
        )
        variant_generation_limit = self._engine.resolve_variant_generation_limit(
            table_plan=table_plan,
            variant_mode=variant_mode,
        )
        if variant_generation_limit is None:
            return max(0, int(table_plan.insert_operations_count))
        return max(0, int(variant_generation_limit))

    def _estimate_sequential_topn_jobs_upper_bound(
        self,
        *,
        table_plan: TableBenchmarkPlan,
    ) -> int:
        """
        Считает fixed upper bound для `sequential_topn_strategy`.

        Для скорости используется лимитный upper bound:
        `types_limit + min(top_n, types_limit) * indexes_limit`.
        """
        type_generation_limit = self._engine.resolve_variant_generation_limit(
            table_plan=table_plan,
            variant_mode="types",
            job_mode="sequential",
        )
        if type_generation_limit is None:
            type_total = max(0, int(table_plan.insert_operations_count))
        else:
            type_total = max(0, int(type_generation_limit))
        if type_total <= 0:
            return 0

        top_n = min(table_plan.sequential_top_n, type_total)
        if top_n <= 0:
            return type_total

        index_generation_limit = self._engine.resolve_variant_generation_limit(
            table_plan=table_plan,
            variant_mode="indexes",
            job_mode="sequential",
        )
        if index_generation_limit is None:
            index_total_per_variant_upper = max(0, int(table_plan.insert_operations_count))
        else:
            index_total_per_variant_upper = max(0, int(index_generation_limit))

        return type_total + (top_n * index_total_per_variant_upper)

    def _estimate_sequential_phased_topn_jobs_upper_bound(
        self,
        *,
        table_plan: TableBenchmarkPlan,
    ) -> int:
        """
        Считает fixed upper bound для `sequential_phased_topn_strategy`.

        Для phased-стратегии считаем upper-bound по фактической логике фаз:
        ORDER BY -> types -> codecs -> indexes -> final_validation.

        Важно:
        - больше не учитываем legacy-этапы `*_validation` (их нет в текущем пайплайне);
        - фазы `types/codecs/indexes` оцениваются по реальным candidate-правилам.
        """
        source_ddl, raw_query_plan = self._engine.prepare_table_context(table_plan)
        order_by_expressions = sequential_phased_topn_strategy_impl._build_order_by_candidates(
            runner=self,
            table_plan=table_plan,
            source_ddl=source_ddl,
            raw_query_plan=raw_query_plan,
        )
        order_by_limit = len(order_by_expressions)
        if order_by_limit <= 0:
            return 0

        top_n_order_by = self._resolve_sequential_stage_top_n(
            table_plan=table_plan,
            stage_mode="order_by",
        )
        top_n_types = self._resolve_sequential_stage_top_n(
            table_plan=table_plan,
            stage_mode="types",
        )
        top_n_codecs = self._resolve_sequential_stage_top_n(
            table_plan=table_plan,
            stage_mode="codecs",
        )
        top_n_indexes = self._resolve_sequential_stage_top_n(
            table_plan=table_plan,
            stage_mode="indexes",
        )
        top_n_final_validation = self._resolve_sequential_stage_top_n(
            table_plan=table_plan,
            stage_mode="final_validation",
        )
        top_n_final_validation_input = self._resolve_sequential_final_validation_input_top_n(
            table_plan=table_plan,
            fallback_top_n=top_n_final_validation,
        )
        max_winners_per_parent_types = self._resolve_sequential_stage_max_winners_per_parent(
            table_plan=table_plan,
            stage_mode="types",
        )
        max_winners_per_parent_codecs = self._resolve_sequential_stage_max_winners_per_parent(
            table_plan=table_plan,
            stage_mode="codecs",
        )
        max_winners_per_parent_indexes = self._resolve_sequential_stage_max_winners_per_parent(
            table_plan=table_plan,
            stage_mode="indexes",
        )

        winners_order_by = min(order_by_limit, top_n_order_by)
        total_jobs = order_by_limit

        type_jobs_per_parent = self._estimate_phased_type_jobs_per_parent(
            table_plan=table_plan,
            source_ddl=source_ddl,
        )
        if type_jobs_per_parent > 0:
            total_jobs += winners_order_by * type_jobs_per_parent
            winners_types = min(
                top_n_types,
                winners_order_by * max_winners_per_parent_types,
            )
        else:
            winners_types = winners_order_by

        codec_jobs_per_parent = self._estimate_phased_codec_jobs_per_parent_upper(
            table_plan=table_plan,
            source_ddl=source_ddl,
        )
        if codec_jobs_per_parent > 0:
            total_jobs += winners_types * codec_jobs_per_parent
            winners_codecs = min(
                top_n_codecs,
                winners_types * max_winners_per_parent_codecs,
            )
        else:
            winners_codecs = winners_types

        index_jobs_per_parent, index_table_granularity_variants_upper = (
            self._estimate_phased_index_jobs_per_parent_upper(
                table_plan=table_plan,
                source_ddl=source_ddl,
                raw_query_plan=raw_query_plan,
                order_by_expressions=order_by_expressions,
            )
        )
        if index_jobs_per_parent > 0:
            total_jobs += winners_codecs * index_jobs_per_parent
            winners_indexes = min(
                top_n_indexes,
                winners_codecs * max_winners_per_parent_indexes,
            )
        else:
            winners_indexes = winners_codecs

        final_candidates = min(winners_indexes, top_n_final_validation_input)
        global_table_granularity_variants = len(table_plan.index_granularity_values or [])
        final_variants_per_candidate = max(
            1,
            int(global_table_granularity_variants),
            int(index_table_granularity_variants_upper),
        )
        total_jobs += final_candidates * final_variants_per_candidate
        return max(0, int(total_jobs))

    @staticmethod
    def _resolve_sequential_stage_top_n(
        *,
        table_plan: TableBenchmarkPlan,
        stage_mode: str,
    ) -> int:
        """Возвращает top-N победителей для конкретной фазы sequential_phased."""
        limits = table_plan.sequential_top_n_limits
        if limits is not None:
            stage_limit = limits.for_mode(stage_mode)
            if stage_limit is not None:
                return max(1, int(stage_limit))
            sequential_limit = limits.for_mode("sequential")
            if sequential_limit is not None:
                return max(1, int(sequential_limit))
        return max(1, int(table_plan.sequential_top_n))

    @staticmethod
    def _resolve_sequential_final_validation_input_top_n(
        *,
        table_plan: TableBenchmarkPlan,
        fallback_top_n: int,
    ) -> int:
        """Возвращает число кандидатов, которые берём из предыдущей фазы в final_validation."""
        explicit = table_plan.final_validation_input_top_n
        if explicit is not None:
            return max(1, int(explicit))
        return max(1, int(fallback_top_n))

    @staticmethod
    def _resolve_sequential_stage_max_winners_per_parent(
        *,
        table_plan: TableBenchmarkPlan,
        stage_mode: str,
    ) -> int:
        """Возвращает max-winners-per-parent лимит для указанной phased-фазы."""
        limits = table_plan.max_winners_per_parent_limits
        if limits is not None:
            stage_limit = limits.for_mode(stage_mode)
            if stage_limit is not None:
                return max(1, int(stage_limit))
            sequential_limit = limits.for_mode("sequential")
            if sequential_limit is not None:
                return max(1, int(sequential_limit))
        return 1

    @staticmethod
    def _estimate_phased_possible_types_for_column(
        *,
        table_plan: TableBenchmarkPlan,
        column_name: str,
        current_type: str,
    ) -> List[str]:
        """Список возможных типов колонки после type-фазы."""
        candidates = sequential_phased_topn_strategy_impl._resolve_type_candidates_for_column(
            table_plan=table_plan,
            column_name=column_name,
            current_type=current_type,
        )
        if not candidates:
            return [current_type]
        deduped: List[str] = []
        for candidate in candidates:
            normalized = str(candidate).strip()
            if not normalized:
                continue
            if normalized in deduped:
                continue
            deduped.append(normalized)
        return deduped or [current_type]

    def _estimate_phased_type_jobs_per_parent(
        self,
        *,
        table_plan: TableBenchmarkPlan,
        source_ddl: TableDDL,
    ) -> int:
        """Количество tasks на одного parent в type-фазе."""
        del self
        jobs = 0
        for column in source_ddl.columns:
            type_candidates = sequential_phased_topn_strategy_impl._resolve_type_candidates_for_column(
                table_plan=table_plan,
                column_name=column.name,
                current_type=column.type,
            )
            if len(type_candidates) <= 1:
                continue
            jobs += len(type_candidates)
        return max(0, int(jobs))

    def _estimate_phased_codec_jobs_per_parent_upper(
        self,
        *,
        table_plan: TableBenchmarkPlan,
        source_ddl: TableDDL,
    ) -> int:
        """
        Верхняя граница количества codec-tasks на одного parent.

        Для каждой колонки берём максимум числа codec-кандидатов по возможным типам.
        """
        jobs = 0
        for column in source_ddl.columns:
            max_codec_candidates_for_column = 0
            possible_types = self._estimate_phased_possible_types_for_column(
                table_plan=table_plan,
                column_name=column.name,
                current_type=column.type,
            )
            for tested_type in possible_types:
                baseline_codec = column.codec if tested_type == column.type else None
                codec_candidates = (
                    sequential_phased_topn_strategy_impl._resolve_codec_candidates_for_column(
                        table_plan=table_plan,
                        column_name=column.name,
                        current_type=tested_type,
                        current_codec=baseline_codec,
                    )
                )
                max_codec_candidates_for_column = max(
                    max_codec_candidates_for_column,
                    len(codec_candidates),
                )
            if max_codec_candidates_for_column <= 1:
                continue
            jobs += max_codec_candidates_for_column
        return max(0, int(jobs))

    def _estimate_phased_index_jobs_per_parent_upper(
        self,
        *,
        table_plan: TableBenchmarkPlan,
        source_ddl: TableDDL,
        raw_query_plan: QueryPlan,
        order_by_expressions: Sequence[str],
    ) -> Tuple[int, int]:
        """
        Верхняя граница количества index-tasks на одного parent.

        Возвращает:
        1) max index-tasks на одного parent;
        2) max вариантов table index_granularity на один финальный кандидат.
        """
        column_names = [column.name for column in source_ddl.columns]
        query_filter_columns = (
            sequential_phased_topn_strategy_impl._extract_filter_columns_from_query_plan(
                raw_query_plan,
                column_names,
            )
        )

        max_options_by_column: Dict[str, int] = {}
        max_table_granularity_variants = 1

        for column in source_ddl.columns:
            max_options_for_column = 0
            possible_types = self._estimate_phased_possible_types_for_column(
                table_plan=table_plan,
                column_name=column.name,
                current_type=column.type,
            )
            for tested_type in possible_types:
                ddl_variant = source_ddl.copy()
                tested_column = ddl_variant.column(column.name)
                if tested_column is None:
                    continue
                tested_column.type = tested_type
                if tested_type != column.type:
                    tested_column.codec = None
                options = sequential_phased_topn_strategy_impl._resolve_index_options_for_column(
                    table_plan=table_plan,
                    base_ddl=ddl_variant,
                    column_name=column.name,
                )
                max_options_for_column = max(max_options_for_column, len(options))
                for option in options:
                    allowed_values_count = len(option.allowed_table_index_granularity_values or [])
                    option_granularity_variants = max(
                        allowed_values_count,
                        1 if option.table_index_granularity is not None else 0,
                    )
                    max_table_granularity_variants = max(
                        max_table_granularity_variants,
                        option_granularity_variants,
                    )
            max_options_by_column[column.name] = max_options_for_column

        max_jobs_per_parent = 0
        for order_by_expr in order_by_expressions:
            order_by_components = {
                sequential_phased_topn_strategy_impl._normalize_identifier(component)
                for component in sequential_phased_topn_strategy_impl._parse_order_by_components(
                    order_by_expr
                )
            }
            candidate_columns = [
                column_name
                for column_name in query_filter_columns
                if column_name not in order_by_components
            ]
            if not candidate_columns:
                candidate_columns = [
                    column_name
                    for column_name in column_names
                    if column_name not in order_by_components
                ]
            jobs_for_expression = sum(
                max_options_by_column.get(column_name, 0) for column_name in candidate_columns
            )
            max_jobs_per_parent = max(max_jobs_per_parent, jobs_for_expression)

        return max(0, int(max_jobs_per_parent)), max(1, int(max_table_granularity_variants))

    def _validate_scoring_formulas_before_run(
        self,
        benchmark_ids: Optional[Sequence[str]],
    ) -> None:
        """
        Валидирует scoring.expression до старта run.

        Если найдены ошибки, пишет warning в лог и останавливает запуск.
        """
        selected_benchmarks = list(self._engine.iter_benchmarks(benchmark_ids=benchmark_ids))
        issues = collect_scoring_formula_issues(selected_benchmarks)
        if not issues:
            return

        logger.warning(
            "BenchmarkRunner: обнаружены ошибки scoring.expression. Запуск benchmark остановлен."
        )
        for issue in issues:
            logger.warning("Scoring validation: %s", issue)
        raise ValueError(
            "Валидация scoring.expression не пройдена: benchmark run остановлен"
        )

    def _execute_and_store(self, job: VariantJob) -> None:
        """
        Выполняет/диспачит вариант.

        Важно: runner не сохраняет результаты. Сохранение выполняет backend/воркер
        внутри execution adapter реализации.
        """
        logger.debug(
            "BenchmarkRunner: dispatch variant job "
            "(run_id=%d, benchmark=%s, table=%s.%s, variant=%s, mode=%s, index=%d)",
            job.benchmark_run_id,
            job.benchmark_id,
            job.source_database,
            job.source_table,
            job.variant_table,
            job.variant_meta.mode,
            job.variant_meta.global_index,
        )
        self._execution_adapter.execute_variant(job)
