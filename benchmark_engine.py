"""Class-based orchestration для планирования и выполнения DDL-бенчмарка."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from clickhouse_ddl import TableDDL
from combiner import VariantMeta, iter_variants, total_variants
from models import (
    BenchmarkConfig,
    BenchmarkMode,
    BenchmarkRootConfig,
    CeleryConfig,
    ConnectionConfig,
    QueriesConfig,
    TableRuleConfig,
)
from naming import variant_table_name
from query_generator import generate_queries
from resolver import ResolvedRules, RuleResolver


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        arbitrary_types_allowed=True,
    )


class TableTarget(_FrozenModel):
    database: str
    table: str


class WeightedQuery(_FrozenModel):
    query: str
    weight: float = 1.0


class QueryPlan(_FrozenModel):
    warmup_queries: List[str]
    test_queries: List[WeightedQuery]


class TableBenchmarkPlan(_FrozenModel):
    benchmark_id: str
    connection_id: str
    connection_dbms: str
    database: str
    table: str
    mode: BenchmarkMode
    max_iterations: int
    rules: ResolvedRules
    queries: QueriesConfig
    celery: CeleryConfig


class VariantJob(_FrozenModel):
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
    benchmark_id: str
    source_database: str
    source_table: str
    variant_table: str
    variant_index: int
    score: Optional[float] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class MetadataProvider(ABC):
    """Интерфейс получения метаданных/DDL из СУБД."""

    @abstractmethod
    def list_databases(self) -> List[str]:
        pass

    @abstractmethod
    def list_tables(self, database: str) -> List[str]:
        pass

    @abstractmethod
    def fetch_table_ddl(self, database: str, table: str) -> TableDDL:
        pass


class FetcherMetadataProvider(MetadataProvider):
    """Адаптер текущего Fetcher под новый интерфейс движка."""

    def __init__(self, fetcher: Any) -> None:
        self._fetcher = fetcher

    def list_databases(self) -> List[str]:
        return self._fetcher.list_databases()

    def list_tables(self, database: str) -> List[str]:
        return self._fetcher.list_tables(database)

    def fetch_table_ddl(self, database: str, table: str) -> TableDDL:
        return self._fetcher.fetch_ddl(database, table)


class TableSelector:
    """Определяет итоговый список таблиц под бенчмарк."""

    def select_targets(
        self,
        benchmark: BenchmarkConfig,
        provider: MetadataProvider,
    ) -> List[TableTarget]:
        databases = self._resolve_databases(benchmark, provider)
        targets = self._resolve_tables(benchmark, databases, provider)
        return self._deduplicate(targets)

    @staticmethod
    def _resolve_databases(
        benchmark: BenchmarkConfig, provider: MetadataProvider
    ) -> List[str]:
        if benchmark.databases == "*":
            return provider.list_databases()
        return list(benchmark.databases)

    @staticmethod
    def _resolve_tables(
        benchmark: BenchmarkConfig,
        databases: List[str],
        provider: MetadataProvider,
    ) -> List[TableTarget]:
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
    """Собирает warmup/test query plan из QueriesConfig."""

    def build(self, table_ddl: TableDDL, queries_config: QueriesConfig) -> QueryPlan:
        mode = queries_config.mode
        warmups = list(queries_config.warmup_queries)

        auto_queries = [WeightedQuery(query=q.query, weight=1.0) for q in generate_queries(table_ddl)]
        manual_queries = [
            WeightedQuery(query=q.query, weight=q.weight) for q in queries_config.test_queries
        ]

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
        full_table_name = f"`{database}`.`{table}`"
        warmups = [query.replace("{table}", full_table_name) for query in plan.warmup_queries]
        tests = [
            WeightedQuery(
                query=weighted.query.replace("{table}", full_table_name),
                weight=weighted.weight,
            )
            for weighted in plan.test_queries
        ]
        return QueryPlan(warmup_queries=warmups, test_queries=tests)


class BenchmarkPlanner:
    """Формирует table-level план бенчмарка."""

    def __init__(
        self,
        config: BenchmarkRootConfig,
        providers_by_connection_id: Dict[str, MetadataProvider],
        table_selector: Optional[TableSelector] = None,
        rule_resolver: Optional[RuleResolver] = None,
    ) -> None:
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
        if connection_id not in self._providers:
            raise ValueError(
                f"MetadataProvider для connection_id={connection_id!r} не зарегистрирован"
            )
        return self._providers[connection_id]

    def iter_table_plans(
        self,
        benchmark_ids: Optional[Sequence[str]] = None,
    ) -> Iterator[TableBenchmarkPlan]:
        benchmark_filter = set(benchmark_ids) if benchmark_ids else None

        for benchmark in self._config.benchmarks:
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
                queries = (
                    table_rule.queries
                    if table_rule and table_rule.queries is not None
                    else benchmark.queries
                )
                celery = benchmark.celery or self._config.celery

                yield TableBenchmarkPlan(
                    benchmark_id=benchmark.id,
                    connection_id=connection.id,
                    connection_dbms=connection.dbms,
                    database=target.database,
                    table=target.table,
                    mode=mode,
                    max_iterations=max_iterations,
                    rules=resolved_rules,
                    queries=queries,
                    celery=celery,
                )

    @staticmethod
    def _find_table_rule(
        benchmark: BenchmarkConfig,
        target: TableTarget,
    ) -> Optional[TableRuleConfig]:
        for table_rule in benchmark.table_rules:
            if table_rule.database == target.database and table_rule.table == target.table:
                return table_rule
        return None


class BenchmarkEngine:
    """Генерирует VariantJob с готовым DDL и query-plan."""

    def __init__(
        self,
        planner: BenchmarkPlanner,
        query_builder: Optional[QueryPlanBuilder] = None,
    ) -> None:
        self._planner = planner
        self._query_builder = query_builder or QueryPlanBuilder()

    def iter_variant_jobs(
        self,
        benchmark_ids: Optional[Sequence[str]] = None,
    ) -> Iterator[VariantJob]:
        for table_plan in self._planner.iter_table_plans(benchmark_ids=benchmark_ids):
            provider = self._planner.provider_for_connection(table_plan.connection_id)
            source_ddl = provider.fetch_table_ddl(
                database=table_plan.database,
                table=table_plan.table,
            )
            raw_query_plan = self._query_builder.build(source_ddl, table_plan.queries)
            capped_total = total_variants(
                table=source_ddl,
                mode=table_plan.mode,
                column_rules=table_plan.rules.column_rules,
                index_rules=table_plan.rules.index_rules,
                column_order=table_plan.rules.column_order,
                max_iterations=table_plan.max_iterations,
            )

            for variant_ddl, variant_meta in iter_variants(
                table=source_ddl,
                mode=table_plan.mode,
                column_rules=table_plan.rules.column_rules,
                index_rules=table_plan.rules.index_rules,
                column_order=table_plan.rules.column_order,
                max_iterations=table_plan.max_iterations,
            ):
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

                yield VariantJob(
                    benchmark_id=table_plan.benchmark_id,
                    connection_id=table_plan.connection_id,
                    connection_dbms=table_plan.connection_dbms,
                    source_database=table_plan.database,
                    source_table=table_plan.table,
                    variant_table=variant_table,
                    variant_meta=variant_meta,
                    mode=table_plan.mode,
                    max_iterations=table_plan.max_iterations,
                    total_variants=capped_total,
                    variant_ddl=prepared_ddl,
                    query_plan=rendered_query_plan,
                    celery=table_plan.celery,
                )


class BenchmarkExecutionAdapter(ABC):
    """
    Интерфейс интеграции с вашим существующим кодом выполнения/замеров.
    """

    @abstractmethod
    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        pass


class NoopExecutionAdapter(BenchmarkExecutionAdapter):
    """Заглушка, полезна для dry-run и отладки плана."""

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        return BenchmarkVariantResult(
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            variant_index=job.variant_meta.global_index,
            score=None,
            payload={"status": "planned_only"},
        )


class BenchmarkRunner:
    """Сквозной runner: планирует jobs и передаёт в execution adapter."""

    def __init__(
        self,
        engine: BenchmarkEngine,
        execution_adapter: BenchmarkExecutionAdapter,
    ) -> None:
        self._engine = engine
        self._execution_adapter = execution_adapter

    def run(
        self,
        benchmark_ids: Optional[Sequence[str]] = None,
    ) -> List[BenchmarkVariantResult]:
        results: List[BenchmarkVariantResult] = []
        for job in self._engine.iter_variant_jobs(benchmark_ids=benchmark_ids):
            results.append(self._execution_adapter.execute_variant(job))
        return results
