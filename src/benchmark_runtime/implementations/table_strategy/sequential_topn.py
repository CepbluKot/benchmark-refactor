"""Реализации table-level стратегий для sequential top-N."""

from __future__ import annotations

from datetime import datetime
from time import monotonic, sleep
from typing import TYPE_CHECKING, Dict, Iterator, Tuple

from src.clickhouse_ddl import TableDDL
from src.combiner import iter_variants, total_variants

from ...contracts.table_strategy import TableExecutionStrategy
from ...types import (
    QueryPlan,
    SourceBenchmarkResult,
    TableBenchmarkPlan,
    TopTypeVariant,
    VariantJob,
)

if TYPE_CHECKING:
    from src.benchmark_engine import BenchmarkRunner
    from ...contracts.result_store import BenchmarkResultStore

_TYPE_STAGE_WAIT_POLL_INTERVAL_SEC = 0.5
_TYPE_STAGE_WAIT_TIMEOUT_SEC = 3600.0


def _require_result_store(
    runner: "BenchmarkRunner",
    strategy_key: str,
) -> "BenchmarkResultStore":
    """Проверяет, что у runner есть result store, обязательный для top-N отбора."""
    store = runner._result_store
    if store is None:
        raise ValueError(
            f"strategy={strategy_key!r} требует result_store "
            "(нужен top-N отбор type-вариантов)"
        )
    return store


def _prepare_table_context(
    runner: "BenchmarkRunner",
    table_plan: TableBenchmarkPlan,
) -> Tuple[TableDDL, QueryPlan, Dict[str, int]]:
    """Готовит исходный DDL, сырой query plan и эффективный порядок колонок."""
    source_ddl, raw_query_plan = runner._engine.prepare_table_context(table_plan)
    effective_column_order = runner._engine.resolve_column_order(
        table_plan=table_plan,
        source_ddl=source_ddl,
    )
    return source_ddl, raw_query_plan, effective_column_order


def _resolve_type_total(
    table_plan: TableBenchmarkPlan,
    source_ddl: TableDDL,
    effective_column_order: Dict[str, int],
) -> int:
    """Считает общее число вариантов для type-stage."""
    return total_variants(
        table=source_ddl,
        mode="types",
        column_rules=table_plan.rules.column_rules,
        index_rules=table_plan.rules.index_rules,
        column_order=effective_column_order,
        max_iterations=table_plan.max_iterations,
    )


def _iter_type_jobs(
    runner: "BenchmarkRunner",
    table_plan: TableBenchmarkPlan,
    source_ddl: TableDDL,
    raw_query_plan: QueryPlan,
    effective_column_order: Dict[str, int],
    type_total: int,
    benchmark_run_id: int,
    benchmark_started_at: datetime,
    source_benchmark: SourceBenchmarkResult,
) -> Iterator[VariantJob]:
    """Итерирует jobs первого этапа (`types`) для sequential top-N."""
    for variant_ddl, variant_meta in iter_variants(
        table=source_ddl,
        mode="types",
        column_rules=table_plan.rules.column_rules,
        index_rules=table_plan.rules.index_rules,
        column_order=effective_column_order,
        max_iterations=table_plan.max_iterations,
    ):
        yield runner._engine.build_variant_job(
            table_plan=table_plan,
            raw_query_plan=raw_query_plan,
            variant_ddl=variant_ddl,
            variant_meta=variant_meta,
            total_variants=type_total,
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
            job_mode="sequential",
            source_benchmark=source_benchmark,
        )


def _resolve_top_type_variants(
    runner: "BenchmarkRunner",
    table_plan: TableBenchmarkPlan,
    benchmark_run_id: int,
    type_total: int,
) -> list[TopTypeVariant]:
    """Читает top-N type-вариантов из result store без ожидания."""
    if type_total <= 0:
        return []
    store = _require_result_store(runner, strategy_key=table_plan.strategy)
    top_n = min(table_plan.sequential_top_n, type_total)
    return store.get_top_type_variants(
        benchmark_run_id=benchmark_run_id,
        benchmark_id=table_plan.benchmark_id,
        source_database=table_plan.database,
        source_table=table_plan.table,
        top_n=top_n,
    )


def _wait_for_type_stage_completion(
    runner: "BenchmarkRunner",
    table_plan: TableBenchmarkPlan,
    benchmark_run_id: int,
    type_total: int,
) -> list[TopTypeVariant]:
    """Ждёт завершения type-stage и возвращает ранжированный список вариантов."""
    if type_total <= 0:
        return []
    store = _require_result_store(runner, strategy_key=table_plan.strategy)

    deadline = monotonic() + _TYPE_STAGE_WAIT_TIMEOUT_SEC
    while True:
        ranked = store.get_top_type_variants(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            source_database=table_plan.database,
            source_table=table_plan.table,
            top_n=type_total,
        )
        if len(ranked) >= type_total:
            return ranked

        if monotonic() >= deadline:
            raise TimeoutError(
                "Ожидание завершения type-stage превысило timeout: "
                f"ожидалось={type_total}, готово={len(ranked)}, "
                f"benchmark={table_plan.benchmark_id}, "
                f"table={table_plan.database}.{table_plan.table}, "
                f"run_id={benchmark_run_id}"
            )
        sleep(_TYPE_STAGE_WAIT_POLL_INTERVAL_SEC)


def _iter_index_jobs_from_top_variants(
    runner: "BenchmarkRunner",
    table_plan: TableBenchmarkPlan,
    raw_query_plan: QueryPlan,
    effective_column_order: Dict[str, int],
    top_variants: list[TopTypeVariant],
    benchmark_run_id: int,
    benchmark_started_at: datetime,
    type_total: int,
    source_benchmark: SourceBenchmarkResult,
) -> Iterator[VariantJob]:
    """Итерирует jobs второго этапа (`indexes`) для выбранных top type-вариантов."""
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
            index_meta.global_index = next_global_index
            next_global_index += 1
            yield runner._engine.build_variant_job(
                table_plan=table_plan,
                raw_query_plan=raw_query_plan,
                variant_ddl=variant_ddl,
                variant_meta=index_meta,
                total_variants=index_total,
                benchmark_run_id=benchmark_run_id,
                benchmark_started_at=benchmark_started_at,
                job_mode="sequential",
                source_benchmark=source_benchmark,
            )


class SequentialTopNTableExecutionStrategy(TableExecutionStrategy):
    """Синхронная двухэтапная стратегия `sequential_topn_strategy`."""

    def execute_table(
        self,
        runner: "BenchmarkRunner",
        table_plan: TableBenchmarkPlan,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
    ) -> None:
        """Запускает type-stage, ждёт top-N и затем запускает index-stage."""
        _require_result_store(runner, strategy_key=table_plan.strategy)
        source_benchmark = runner._require_active_source_benchmark()
        source_ddl, raw_query_plan, effective_column_order = _prepare_table_context(
            runner=runner,
            table_plan=table_plan,
        )
        type_total = _resolve_type_total(
            table_plan=table_plan,
            source_ddl=source_ddl,
            effective_column_order=effective_column_order,
        )

        for job in _iter_type_jobs(
            runner=runner,
            table_plan=table_plan,
            source_ddl=source_ddl,
            raw_query_plan=raw_query_plan,
            effective_column_order=effective_column_order,
            type_total=type_total,
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
            source_benchmark=source_benchmark,
        ):
            runner._execute_and_store(job)

        ranked_type_variants = _wait_for_type_stage_completion(
            runner=runner,
            table_plan=table_plan,
            benchmark_run_id=benchmark_run_id,
            type_total=type_total,
        )
        top_n = min(table_plan.sequential_top_n, type_total)
        top_variants = ranked_type_variants[:top_n]
        if not top_variants:
            return

        for job in _iter_index_jobs_from_top_variants(
            runner=runner,
            table_plan=table_plan,
            raw_query_plan=raw_query_plan,
            effective_column_order=effective_column_order,
            top_variants=top_variants,
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
            type_total=type_total,
            source_benchmark=source_benchmark,
        ):
            runner._execute_and_store(job)


class SequentialTopNDispatchTypesTableExecutionStrategy(TableExecutionStrategy):
    """
    Dispatch-only стратегия для stage-1 sequential top-N.

    Предназначена для асинхронного сценария:
      - launcher только отправляет type jobs;
      - результаты сохраняются в БД Celery-воркерами.
    """

    def execute_table(
        self,
        runner: "BenchmarkRunner",
        table_plan: TableBenchmarkPlan,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
    ) -> None:
        """Отправляет только type-stage jobs без runner-side сохранения."""
        source_benchmark = runner._require_active_source_benchmark()
        source_ddl, raw_query_plan, effective_column_order = _prepare_table_context(
            runner=runner,
            table_plan=table_plan,
        )
        type_total = _resolve_type_total(
            table_plan=table_plan,
            source_ddl=source_ddl,
            effective_column_order=effective_column_order,
        )
        for job in _iter_type_jobs(
            runner=runner,
            table_plan=table_plan,
            source_ddl=source_ddl,
            raw_query_plan=raw_query_plan,
            effective_column_order=effective_column_order,
            type_total=type_total,
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
            source_benchmark=source_benchmark,
        ):
            runner._execute_without_store(job)


class SequentialTopNDispatchIndexesTableExecutionStrategy(TableExecutionStrategy):
    """
    Dispatch-only стратегия для stage-2 sequential top-N.

    Ожидает, что type-stage уже завершён и top-N типовых вариантов
    доступен в result store (обычно это внешнее DB-хранилище).
    """

    def execute_table(
        self,
        runner: "BenchmarkRunner",
        table_plan: TableBenchmarkPlan,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
    ) -> None:
        """Отправляет index-stage jobs для top-N type-вариантов из store."""
        source_benchmark = runner._require_active_source_benchmark()
        source_ddl, raw_query_plan, effective_column_order = _prepare_table_context(
            runner=runner,
            table_plan=table_plan,
        )
        type_total = _resolve_type_total(
            table_plan=table_plan,
            source_ddl=source_ddl,
            effective_column_order=effective_column_order,
        )
        top_variants = _resolve_top_type_variants(
            runner=runner,
            table_plan=table_plan,
            benchmark_run_id=benchmark_run_id,
            type_total=type_total,
        )
        if not top_variants:
            return

        for job in _iter_index_jobs_from_top_variants(
            runner=runner,
            table_plan=table_plan,
            raw_query_plan=raw_query_plan,
            effective_column_order=effective_column_order,
            top_variants=top_variants,
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
            type_total=type_total,
            source_benchmark=source_benchmark,
        ):
            runner._execute_without_store(job)
