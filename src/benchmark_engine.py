"""
Модуль оркестрации слоёв бенчмарка (planner -> engine -> runner).

Поток данных в этом модуле:
  1) `BenchmarkPlanner` разворачивает JSON-конфиг в table-level планы;
  2) `BenchmarkEngine` по каждому плану строит DDL-варианты и query-планы;
  3) `BenchmarkRunner` передаёт VariantJob в адаптер фактического выполнения.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from src.clickhouse_ddl import TableDDL
from src.combiner import VariantMeta, iter_variants, total_variants
from src.models import (
    BenchmarkConfig,
    BenchmarkMode,
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
    SequentialTopNDispatchIndexesTableExecutionStrategy,
    SequentialTopNDispatchTypesTableExecutionStrategy,
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
        return self._deduplicate(targets)

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
        warmups = list(queries_config.warmup_queries)

        auto_queries = [Query(query=q.query) for q in generate_queries(table_ddl)]
        manual_queries = [Query(query=q.query) for q in queries_config.test_queries]

        if mode == "auto":
            tests = auto_queries
        elif mode == "manual":
            tests = manual_queries
        else:
            tests = auto_queries + manual_queries

        return QueryPlan(warmup_queries=warmups, test_queries=tests)

    @staticmethod
    def render_for_table(
        plan: QueryPlan,
        database: str,
        table: str,
    ) -> QueryPlan:
        """
        Подставляет реальное имя таблицы в каждый запрос плана.

        Используется перед отправкой `VariantJob` в execution-адаптер.
        """
        full_table_name = f"`{database}`.`{table}`"
        warmups = [query.replace("{table}", full_table_name) for query in plan.warmup_queries]
        tests = [
            Query(query=planned.query.replace("{table}", full_table_name))
            for planned in plan.test_queries
        ]
        return QueryPlan(warmup_queries=warmups, test_queries=tests)


class BenchmarkPlanner:
    """
    Формирует table-level планы из корневого конфига.

    На этом этапе происходит ключевой merge:
      - выбор целевых таблиц;
      - merge global/local rules;
      - выбор strategy/max_iterations/queries с учетом table override;
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
                max_iterations = (
                    table_rule.max_iterations
                    if table_rule and table_rule.max_iterations is not None
                    else benchmark.max_iterations
                )
                sequential_top_n = (
                    table_rule.sequential_top_n
                    if table_rule and table_rule.sequential_top_n is not None
                    else benchmark.sequential_top_n
                )
                insert_rows_limit = (
                    table_rule.insert_rows_limit
                    if table_rule and table_rule.insert_rows_limit is not None
                    else benchmark.insert_rows_limit
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

                yield TableBenchmarkPlan(
                    benchmark_id=benchmark.id,
                    connection_id=connection.id,
                    connection_dbms=connection.dbms,
                    database=target.database,
                    test_database=test_database,
                    table=target.table,
                    strategy=strategy,
                    mode=mode,
                    max_iterations=max_iterations,
                    sequential_top_n=sequential_top_n,
                    insert_rows_limit=insert_rows_limit,
                    insert_rows_limits=insert_rows_limits,
                    column_order_mode=column_order_mode,
                    rules=resolved_rules,
                    queries=queries,
                    celery=self._config.celery,
                )

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
        )
        source_insert_rows_limit = self.resolve_insert_rows_limit(
            table_plan=table_plan,
            variant_mode=table_plan.mode,
            job_mode=table_plan.mode,
        )

        return SourceBenchmarkJob(
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
            benchmark_id=table_plan.benchmark_id,
            connection_id=table_plan.connection_id,
            connection_dbms=table_plan.connection_dbms,
            source_database=table_plan.database,
            source_table=table_plan.table,
            source_table_ddl=prepared_source_ddl,
            query_plan=rendered_query_plan,
            max_iterations=table_plan.max_iterations,
            insert_rows_limit=source_insert_rows_limit,
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
        variant_database = table_plan.test_database or table_plan.database
        variant_table = variant_table_name(
            original_table=table_plan.table,
            benchmark_id=table_plan.benchmark_id,
            variant_index=variant_meta.global_index,
        )
        prepared_ddl = variant_ddl.copy()
        prepared_ddl.name = f"{variant_database}.{variant_table}"

        rendered_query_plan = self._query_builder.render_for_table(
            plan=raw_query_plan,
            database=variant_database,
            table=variant_table,
        )

        effective_insert_rows_limit = self.resolve_insert_rows_limit(
            table_plan=table_plan,
            variant_mode=variant_meta.mode,
            job_mode=job_mode,
        )

        return VariantJob(
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
            benchmark_id=table_plan.benchmark_id,
            connection_id=table_plan.connection_id,
            connection_dbms=table_plan.connection_dbms,
            source_database=table_plan.database,
            variant_database=variant_database,
            source_table=table_plan.table,
            variant_table=variant_table,
            variant_meta=variant_meta,
            mode=job_mode if job_mode is not None else table_plan.mode,
            max_iterations=table_plan.max_iterations,
            insert_rows_limit=effective_insert_rows_limit,
            total_variants=total_variants,
            variant_ddl=prepared_ddl,
            source_benchmark=source_benchmark,
            query_plan=rendered_query_plan,
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
        capped_total = total_variants(
            table=source_ddl,
            mode=variant_mode,
            column_rules=table_plan.rules.column_rules,
            index_rules=table_plan.rules.index_rules,
            column_order=effective_column_order,
            max_iterations=table_plan.max_iterations,
        )

        for variant_ddl, variant_meta in iter_variants(
            table=source_ddl,
            mode=variant_mode,
            column_rules=table_plan.rules.column_rules,
            index_rules=table_plan.rules.index_rules,
            column_order=effective_column_order,
            max_iterations=table_plan.max_iterations,
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
        (например, `sequential_topn_strategy` и stage2 dispatch).
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
            "sequential_topn_stage1_dispatch_strategy": (
                SequentialTopNDispatchTypesTableExecutionStrategy()
            ),
            "sequential_topn_stage2_dispatch_strategy": (
                SequentialTopNDispatchIndexesTableExecutionStrategy()
            ),
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

        Для асинхронного потока без ожидания (fire-and-forget) можно использовать
        разделённые стратегии:
          - `sequential_topn_stage1_dispatch_strategy`
          - `sequential_topn_stage2_dispatch_strategy`
        где launcher только отправляет jobs, а store наполняют воркеры.

        Для каждого вызова фиксируется единый `benchmark_started_at` (UTC datetime),
        общий для всех benchmark/table/jobs в рамках этого запуска.

        Перед исполнением любой strategy для таблицы runner всегда запускает
        baseline-бенчмарк исходного DDL (`execute_source_benchmark`) и затем
        прокидывает его результат в каждый `VariantJob.source_benchmark`.
        """
        run_id = benchmark_run_id if benchmark_run_id is not None else self._next_run_id()
        if run_id <= 0:
            raise ValueError(f"benchmark_run_id должен быть > 0, получено: {run_id}")
        run_started_at = self._next_run_started_at()
        self._last_benchmark_started_at = run_started_at

        for table_plan in self._engine.iter_table_plans(benchmark_ids=benchmark_ids):
            strategy_key = self._canonical_strategy_key(table_plan.strategy)
            strategy = self._table_execution_strategies.get(
                strategy_key,
                self._default_table_execution_strategy,
            )
            self._active_source_benchmark = self._execute_source_benchmark(
                table_plan=table_plan,
                benchmark_run_id=run_id,
                benchmark_started_at=run_started_at,
            )
            try:
                strategy.execute_table(
                    runner=self,
                    table_plan=table_plan,
                    benchmark_run_id=run_id,
                    benchmark_started_at=run_started_at,
                )
            finally:
                self._active_source_benchmark = None
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
        for job in self._engine.iter_variant_jobs_for_table_plan(
            table_plan,
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
            source_benchmark=source_benchmark,
        ):
            self._execute_and_store(job)

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
        return result

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

    def _execute_and_store(self, job: VariantJob) -> None:
        """
        Выполняет/диспачит вариант.

        Важно: runner не сохраняет результаты. Сохранение выполняет backend/воркер
        внутри execution adapter реализации.
        """
        self._execution_adapter.execute_variant(job)

    def _execute_without_store(self, job: VariantJob) -> None:
        """
        Выполняет/диспачит вариант (совместимый алиас).

        Исторически этот метод использовался dispatch-only стратегиями.
        Сейчас runner нигде не пишет в store, поэтому поведение эквивалентно
        `_execute_and_store`.
        """
        self._execution_adapter.execute_variant(job)
