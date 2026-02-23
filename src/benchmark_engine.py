"""
Core orchestration слоя бенчмарка (planner -> engine -> runner).

Поток данных в этом модуле:
  1) `BenchmarkPlanner` разворачивает JSON-конфиг в table-level планы;
  2) `BenchmarkEngine` по каждому плану строит DDL-варианты и query-планы;
  3) `BenchmarkRunner` передаёт VariantJob в адаптер фактического выполнения.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from clickhouse_ddl import TableDDL
from combiner import VariantMeta, iter_variants, total_variants
from models import (
    BenchmarkConfig,
    BenchmarkMode,
    BenchmarkRootConfig,
    CeleryConfig,
    ColumnOrderMode,
    ConnectionConfig,
    QueriesConfig,
    TableRuleConfig,
)
from naming import variant_table_name
from query_generator import generate_queries
from resolver import ResolvedRules, RuleResolver


class _FrozenModel(BaseModel):
    """Общая immutable-база для runtime DTO внутри движка."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        arbitrary_types_allowed=True,
    )


class TableTarget(_FrozenModel):
    """Конкретная таблица-цель (`database.table`) после раскрытия селекторов."""

    database: str
    table: str


class Query(_FrozenModel):
    """Тестовый SQL-запрос."""

    query: str


class QueryPlan(_FrozenModel):
    """Готовый набор warmup/test запросов для одной variant-таблицы."""

    warmup_queries: List[str]
    test_queries: List[Query]


class TableBenchmarkPlan(_FrozenModel):
    """
    Table-level план, сформированный planner'ом до этапа генерации вариантов.

    Этот объект уже учитывает merge:
      - global/table rules,
      - global/table max_iterations,
      - global/table column_order_mode,
      - global/table queries,
      - глобальный celery-конфиг запуска.
    """

    benchmark_id: str
    connection_id: str
    connection_dbms: str
    database: str
    table: str
    mode: BenchmarkMode
    max_iterations: int
    sequential_top_n: int
    column_order_mode: Optional[ColumnOrderMode]
    rules: ResolvedRules
    queries: QueriesConfig
    celery: CeleryConfig


class VariantJob(_FrozenModel):
    """
    Полная единица выполнения для конкретного варианта DDL.

    Содержит всё, что нужно execution-слою:
      - DDL variant-таблицы;
      - query-план;
      - runtime-параметры (mode, max_iterations, celery);
      - метаданные варианта (индекс, total и т.д.).
    """

    benchmark_run_id: int
    benchmark_id: str
    connection_id: str
    connection_dbms: str
    source_database: str
    source_table: str
    variant_table: str
    variant_meta: VariantMeta
    mode: BenchmarkMode
    max_iterations: int
    total_variants: int
    variant_ddl: TableDDL
    query_plan: QueryPlan
    celery: CeleryConfig


class BenchmarkVariantResult(_FrozenModel):
    """
    Результат выполнения одного `VariantJob`.

    Заполняется execution-адаптером и передаётся в result-store для персистентного
    сохранения (например, в БД).
    """

    benchmark_run_id: int
    benchmark_id: str
    source_database: str
    source_table: str
    variant_table: str
    variant_index: int
    score: Optional[float] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class StoredBenchmarkResult(_FrozenModel):
    """
    Нормализованная запись результата в persistence-слое.

    Это DTO для result-store, чтобы runner не хранил результаты в оперативной
    памяти и не зависел от конкретной схемы таблиц в БД.
    """

    benchmark_run_id: int
    benchmark_id: str
    source_database: str
    source_table: str
    variant_table: str
    variant_index: int
    variant_mode: str
    score: Optional[float] = None
    variant_ddl: TableDDL
    payload: Dict[str, Any] = Field(default_factory=dict)


class TopTypeVariant(_FrozenModel):
    """Кандидат из top-N type/codeс этапа для перехода на index-этап."""

    variant_index: int
    variant_ddl: TableDDL
    score: Optional[float] = None


class BenchmarkResultStore(ABC):
    """
    Контракт персистентного хранения результатов.

    В production реализации обычно пишут результаты в БД и читают top-N
    type-варианты SQL-запросом.
    """

    @abstractmethod
    def store_result(
        self,
        job: VariantJob,
        result: BenchmarkVariantResult,
    ) -> None:
        """Сохраняет результат выполнения одного `VariantJob`."""
        pass

    @abstractmethod
    def get_top_type_variants(
        self,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        top_n: int,
    ) -> List[TopTypeVariant]:
        """
        Возвращает top-N type/codec DDL для sequential-этапа индексов.

        Ожидаемый порядок: по score убыв., `score=None` в конце.
        """
        pass


class InMemoryBenchmarkResultStore(BenchmarkResultStore):
    """
    In-memory реализация result-store.

    Нужна для тестов и dry-run примеров. Для production следует заменить
    на DB-backed реализацию.
    """

    def __init__(self) -> None:
        self._records: List[StoredBenchmarkResult] = []

    @property
    def records(self) -> List[StoredBenchmarkResult]:
        """Возвращает копию сохранённых записей (удобно в тестах)."""
        return list(self._records)

    def store_result(
        self,
        job: VariantJob,
        result: BenchmarkVariantResult,
    ) -> None:
        """Сохраняет результат и снимок variant DDL в памяти."""
        if result.benchmark_run_id != job.benchmark_run_id:
            raise ValueError(
                "result.benchmark_run_id не совпадает с job.benchmark_run_id"
            )
        if result.benchmark_id != job.benchmark_id:
            raise ValueError("result.benchmark_id не совпадает с job.benchmark_id")

        self._records.append(
            StoredBenchmarkResult(
                benchmark_run_id=job.benchmark_run_id,
                benchmark_id=job.benchmark_id,
                source_database=job.source_database,
                source_table=job.source_table,
                variant_table=job.variant_table,
                variant_index=job.variant_meta.global_index,
                variant_mode=job.variant_meta.mode,
                score=result.score,
                variant_ddl=job.variant_ddl.copy(),
                payload=dict(result.payload),
            )
        )

    def get_top_type_variants(
        self,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        top_n: int,
    ) -> List[TopTypeVariant]:
        """Ранжирует сохранённые type-варианты и отдаёт top-N."""
        if top_n <= 0:
            return []

        candidates = [
            record
            for record in self._records
            if record.benchmark_run_id == benchmark_run_id
            and record.benchmark_id == benchmark_id
            and record.source_database == source_database
            and record.source_table == source_table
            and record.variant_mode == "types"
        ]
        ranked = sorted(
            candidates,
            key=lambda record: (
                record.score is None,
                -(record.score if record.score is not None else 0.0),
                record.variant_index,
            ),
        )
        return [
            TopTypeVariant(
                variant_index=record.variant_index,
                variant_ddl=record.variant_ddl.copy(),
                score=record.score,
            )
            for record in ranked[:top_n]
        ]


class MetadataProvider(ABC):
    """
    Абстракция доступа к метаданным источника.

    Позволяет planner/engine работать с любым backend'ом (реальный Fetcher,
    тестовый in-memory provider, mock и т.п.).
    """

    @abstractmethod
    def list_databases(self) -> List[str]:
        """Возвращает список доступных БД для селектора `databases="*"`."""
        pass

    @abstractmethod
    def list_tables(self, database: str) -> List[str]:
        """Возвращает таблицы БД для селектора `tables="*"`."""
        pass

    @abstractmethod
    def fetch_table_ddl(self, database: str, table: str) -> TableDDL:
        """Читает и парсит DDL исходной таблицы в `TableDDL`."""
        pass

    def fetch_column_sizes(self, database: str, table: str) -> Dict[str, int]:
        """
        Возвращает map `column_name -> compressed_bytes` для исходной таблицы.

        Базовая реализация возвращает пустой словарь; backend может переопределить
        метод для поддержки авто-вычисления `column_order`.
        """
        return {}


class FetcherMetadataProvider(MetadataProvider):
    """Адаптер над существующим `Fetcher` для контракта `MetadataProvider`."""

    def __init__(self, fetcher: Any) -> None:
        """Сохраняет объект fetcher с совместимыми методами list*/fetch_ddl."""
        self._fetcher = fetcher

    def list_databases(self) -> List[str]:
        """Проксирует список БД из fetcher."""
        return self._fetcher.list_databases()

    def list_tables(self, database: str) -> List[str]:
        """Проксирует список таблиц по БД из fetcher."""
        return self._fetcher.list_tables(database)

    def fetch_table_ddl(self, database: str, table: str) -> TableDDL:
        """Проксирует получение DDL таблицы из fetcher."""
        return self._fetcher.fetch_ddl(database, table)

    def fetch_column_sizes(self, database: str, table: str) -> Dict[str, int]:
        """Проксирует получение размерности колонок из fetcher."""
        fetch_method = getattr(self._fetcher, "fetch_column_sizes", None)
        if fetch_method is None:
            return {}
        return fetch_method(database, table)


class TableSelector:
    """
    Разворачивает selectors из `BenchmarkConfig` в список `TableTarget`.

    Поддерживает все варианты:
      - `databases="*"`/`tables="*"`;
      - ручной список БД;
      - ручной список таблиц (общий или map по БД).
    """

    def select_targets(
        self,
        benchmark: BenchmarkConfig,
        provider: MetadataProvider,
    ) -> List[TableTarget]:
        """Возвращает deduplicated список таблиц для конкретного benchmark."""
        databases = self._resolve_databases(benchmark, provider)
        targets = self._resolve_tables(benchmark, databases, provider)
        return self._deduplicate(targets)

    @staticmethod
    def _resolve_databases(
        benchmark: BenchmarkConfig, provider: MetadataProvider
    ) -> List[str]:
        """Разрешает selector `databases` в конкретный список имён БД."""
        if benchmark.databases == "*":
            return provider.list_databases()
        return list(benchmark.databases)

    @staticmethod
    def _resolve_tables(
        benchmark: BenchmarkConfig,
        databases: List[str],
        provider: MetadataProvider,
    ) -> List[TableTarget]:
        """Разрешает selector `tables` для уже выбранного списка БД."""
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
    Строит query-plan для одной таблицы на основе `QueriesConfig`.

    Сначала формирует набор запросов с `{table}` placeholder,
    затем этот placeholder подставляется в имя конкретной variant-таблицы.
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
      - выбор mode/max_iterations/queries с учетом table override;
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
        Итерирует table-level планы для выбранных benchmark_id.

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
                    table_rule.mode if table_rule and table_rule.mode else benchmark.mode
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

                yield TableBenchmarkPlan(
                    benchmark_id=benchmark.id,
                    connection_id=connection.id,
                    connection_dbms=connection.dbms,
                    database=target.database,
                    table=target.table,
                    mode=mode,
                    max_iterations=max_iterations,
                    sequential_top_n=sequential_top_n,
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


class BenchmarkEngine:
    """
    Преобразует `TableBenchmarkPlan` в поток `VariantJob`.

    Для каждой исходной таблицы:
      1) читает исходный DDL;
      2) генерирует DDL-варианты через combiner;
      3) готовит query-план для каждой variant-таблицы.
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
        """Загружает исходный DDL и строит query-plan c placeholder'ом `{table}`."""
        provider = self._planner.provider_for_connection(table_plan.connection_id)
        source_ddl = provider.fetch_table_ddl(
            database=table_plan.database,
            table=table_plan.table,
        )
        raw_query_plan = self._query_builder.build(source_ddl, table_plan.queries)
        return source_ddl, raw_query_plan

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
            if any(rule.matches(column) for rule in table_plan.rules.column_rules):
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
        job_mode: Optional[BenchmarkMode] = None,
    ) -> VariantJob:
        """Собирает `VariantJob` из уже подготовленного variant DDL и meta."""
        variant_table = variant_table_name(
            original_table=table_plan.table,
            benchmark_id=table_plan.benchmark_id,
            variant_index=variant_meta.global_index,
        )
        prepared_ddl = variant_ddl.copy()
        prepared_ddl.name = f"{table_plan.database}.{variant_table}"

        rendered_query_plan = self._query_builder.render_for_table(
            plan=raw_query_plan,
            database=table_plan.database,
            table=variant_table,
        )

        return VariantJob(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            connection_id=table_plan.connection_id,
            connection_dbms=table_plan.connection_dbms,
            source_database=table_plan.database,
            source_table=table_plan.table,
            variant_table=variant_table,
            variant_meta=variant_meta,
            mode=job_mode if job_mode is not None else table_plan.mode,
            max_iterations=table_plan.max_iterations,
            total_variants=total_variants,
            variant_ddl=prepared_ddl,
            query_plan=rendered_query_plan,
            celery=table_plan.celery,
        )

    def iter_variant_jobs_for_table_plan(
        self,
        table_plan: TableBenchmarkPlan,
        benchmark_run_id: int = 1,
    ) -> Iterator[VariantJob]:
        """
        Генерирует VariantJob для одного `TableBenchmarkPlan`.

        Для `sequential` здесь отдаётся только type/codec стадия.
        Индексная стадия зависит от score и оркестрируется в `BenchmarkRunner`.
        """
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
            )

    def iter_variant_jobs(
        self,
        benchmark_ids: Optional[Sequence[str]] = None,
        benchmark_run_id: int = 1,
    ) -> Iterator[VariantJob]:
        """Итерирует fully prepared задания на выполнение каждого варианта."""
        for table_plan in self.iter_table_plans(benchmark_ids=benchmark_ids):
            yield from self.iter_variant_jobs_for_table_plan(
                table_plan,
                benchmark_run_id=benchmark_run_id,
            )


class BenchmarkExecutionAdapter(ABC):
    """
    Контракт между engine и реальным исполнителем бенчмарка.

    Любая интеграция (Celery, sync worker, внешний сервис) должна уметь
    принять `VariantJob` и вернуть `BenchmarkVariantResult`.
    """

    @abstractmethod
    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        """Выполняет один вариант и возвращает результат замеров."""
        pass


class NoopExecutionAdapter(BenchmarkExecutionAdapter):
    """Заглушка, полезна для dry-run и отладки плана."""

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        """Возвращает технический результат без фактического выполнения SQL."""
        return BenchmarkVariantResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            variant_index=job.variant_meta.global_index,
            score=None,
            payload={"status": "planned_only"},
        )


class BenchmarkRunIdProvider(ABC):
    """
    Источник run-level benchmark id.

    Контракт: вернуть целое число > 0, общее для всего текущего запуска конфига.
    """

    @abstractmethod
    def next_benchmark_run_id(self) -> int:
        """Возвращает следующий run id (обычно max(existing)+1)."""
        pass


class InMemoryBenchmarkRunIdProvider(BenchmarkRunIdProvider):
    """Простой serial run id provider в памяти процесса (1, 2, 3, ...)."""

    def __init__(self, start_from: int = 0) -> None:
        self._last_run_id = start_from

    def next_benchmark_run_id(self) -> int:
        self._last_run_id += 1
        return self._last_run_id


class MaxIdBenchmarkRunIdProvider(BenchmarkRunIdProvider):
    """
    Provider, который строит следующий run id из `max(existing_id)` в хранилище.

    `max_id_getter` должен вернуть максимальный уже сохранённый id или `None`,
    если записей ещё нет.
    """

    def __init__(self, max_id_getter: Callable[[], Optional[int]]) -> None:
        self._max_id_getter = max_id_getter
        self._reserved_last_id = 0

    def next_benchmark_run_id(self) -> int:
        observed_max = self._max_id_getter()
        observed = int(observed_max) if observed_max is not None else 0
        if observed < 0:
            raise ValueError(
                f"max_id_getter вернул отрицательный benchmark id: {observed}"
            )
        next_id = max(observed, self._reserved_last_id) + 1
        self._reserved_last_id = next_id
        return next_id


class BenchmarkRunner:
    """
    Верхнеуровневый фасад запуска бенчмарка.

    Объединяет генерацию заданий и их выполнение в один метод `run`.
    """

    def __init__(
        self,
        engine: BenchmarkEngine,
        execution_adapter: BenchmarkExecutionAdapter,
        result_store: BenchmarkResultStore,
        run_id_provider: Optional[BenchmarkRunIdProvider] = None,
    ) -> None:
        """Сохраняет engine, адаптер выполнения и persistence-хранилище."""
        self._engine = engine
        self._execution_adapter = execution_adapter
        self._result_store = result_store
        self._run_id_provider = run_id_provider or InMemoryBenchmarkRunIdProvider()

    def run(
        self,
        benchmark_ids: Optional[Sequence[str]] = None,
        benchmark_run_id: Optional[int] = None,
    ) -> int:
        """
        Выполняет все VariantJob и возвращает run-level `benchmark_run_id`.

        Для `mode="sequential"` используется двухфазный алгоритм:
          1) прогон type/codec-вариантов;
          2) выбор top-N через result-store и прогон индексных вариантов на их DDL.
        """
        run_id = benchmark_run_id if benchmark_run_id is not None else self._next_run_id()
        if run_id <= 0:
            raise ValueError(f"benchmark_run_id должен быть > 0, получено: {run_id}")

        for table_plan in self._engine.iter_table_plans(benchmark_ids=benchmark_ids):
            if table_plan.mode != "sequential":
                for job in self._engine.iter_variant_jobs_for_table_plan(
                    table_plan,
                    benchmark_run_id=run_id,
                ):
                    self._execute_and_store(job)
                continue

            self._run_sequential(table_plan, benchmark_run_id=run_id)
        return run_id

    def _run_sequential(
        self,
        table_plan: TableBenchmarkPlan,
        benchmark_run_id: int,
    ) -> None:
        """Адаптивный sequential: types -> persist -> top-N select -> indexes."""
        source_ddl, raw_query_plan = self._engine.prepare_table_context(table_plan)
        effective_column_order = self._engine.resolve_column_order(
            table_plan=table_plan,
            source_ddl=source_ddl,
        )

        type_total = total_variants(
            table=source_ddl,
            mode="types",
            column_rules=table_plan.rules.column_rules,
            index_rules=table_plan.rules.index_rules,
            column_order=effective_column_order,
            max_iterations=table_plan.max_iterations,
        )

        for variant_ddl, variant_meta in iter_variants(
            table=source_ddl,
            mode="types",
            column_rules=table_plan.rules.column_rules,
            index_rules=table_plan.rules.index_rules,
            column_order=effective_column_order,
            max_iterations=table_plan.max_iterations,
        ):
            ddl_text = variant_ddl.to_ddl()
            print(ddl_text)
            job = self._engine.build_variant_job(
                table_plan=table_plan,
                raw_query_plan=raw_query_plan,
                variant_ddl=variant_ddl,
                variant_meta=variant_meta,
                total_variants=type_total,
                benchmark_run_id=benchmark_run_id,
                job_mode="sequential",
            )
            self._execute_and_store(job)

        if type_total <= 0:
            return

        top_n = min(table_plan.sequential_top_n, type_total)
        top_variants = self._result_store.get_top_type_variants(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            source_database=table_plan.database,
            source_table=table_plan.table,
            top_n=top_n,
        )
        if not top_variants:
            return
        next_global_index = type_total

        for type_variant in top_variants:
            base_ddl = type_variant.variant_ddl.copy()
            index_total = total_variants(
                table=base_ddl,
                mode="indexes",
                column_rules=table_plan.rules.column_rules,
                index_rules=table_plan.rules.index_rules,
                column_order=effective_column_order,
                max_iterations=table_plan.max_iterations,
            )

            for variant_ddl, index_meta in iter_variants(
                table=base_ddl,
                mode="indexes",
                column_rules=table_plan.rules.column_rules,
                index_rules=table_plan.rules.index_rules,
                column_order=effective_column_order,
                max_iterations=table_plan.max_iterations,
            ):
                ddl_text = variant_ddl.to_ddl()
                print(ddl_text)
                index_meta.global_index = next_global_index
                next_global_index += 1
                index_job = self._engine.build_variant_job(
                    table_plan=table_plan,
                    raw_query_plan=raw_query_plan,
                    variant_ddl=variant_ddl,
                    variant_meta=index_meta,
                    total_variants=index_total,
                    benchmark_run_id=benchmark_run_id,
                    job_mode="sequential",
                )
                self._execute_and_store(index_job)

    def _next_run_id(self) -> int:
        """Берёт следующий serial benchmark run id у configured provider."""
        return self._run_id_provider.next_benchmark_run_id()

    def _execute_and_store(self, job: VariantJob) -> None:
        """Выполняет вариант и сразу персистит результат в result-store."""
        result = self._execution_adapter.execute_variant(job)
        self._result_store.store_result(job, result)
