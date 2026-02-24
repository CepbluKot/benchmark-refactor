"""Реализации table-level стратегий для sequential top-N."""

from __future__ import annotations

from datetime import datetime
import logging
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

logger = logging.getLogger(__name__)


def _open_progress_scope_if_supported(
    runner: "BenchmarkRunner",
    scope_name: str,
) -> None:
    """Открывает progress-scope в adapter, если реализация поддерживает API."""
    open_hook = getattr(runner._execution_adapter, "open_progress_scope", None)
    if callable(open_hook):
        open_hook(scope_name)


def _wait_for_dispatched_tasks_if_supported(
    runner: "BenchmarkRunner",
    stage_label: str,
) -> None:
    """Ждёт завершения Celery-batch, если adapter поддерживает API ожидания."""
    wait_hook = getattr(runner._execution_adapter, "wait_for_dispatched_tasks", None)
    if callable(wait_hook):
        wait_hook(stage_label=stage_label)


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
    logger.info(
        "SequentialTopN: ожидание завершения type-stage "
        "(run_id=%d, benchmark=%s, table=%s.%s, expected=%d)",
        benchmark_run_id,
        table_plan.benchmark_id,
        table_plan.database,
        table_plan.table,
        type_total,
    )
    while True:
        ranked = store.get_top_type_variants(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            source_database=table_plan.database,
            source_table=table_plan.table,
            top_n=type_total,
        )
        if len(ranked) >= type_total:
            logger.info(
                "SequentialTopN: type-stage завершён "
                "(run_id=%d, benchmark=%s, table=%s.%s, ready=%d)",
                benchmark_run_id,
                table_plan.benchmark_id,
                table_plan.database,
                table_plan.table,
                len(ranked),
            )
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
        logger.info(
            "SequentialTopN: старт стратегии "
            "(run_id=%d, benchmark=%s, table=%s.%s)",
            benchmark_run_id,
            table_plan.benchmark_id,
            table_plan.database,
            table_plan.table,
        )
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
        logger.info(
            "SequentialTopN: type-stage dispatch "
            "(run_id=%d, benchmark=%s, table=%s.%s, variants=%d)",
            benchmark_run_id,
            table_plan.benchmark_id,
            table_plan.database,
            table_plan.table,
            type_total,
        )
        _open_progress_scope_if_supported(
            runner=runner,
            scope_name=(
                f"sequential stage1 types: {table_plan.benchmark_id} "
                f"{table_plan.database}.{table_plan.table}"
            ),
        )

        type_dispatched = 0
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
            type_dispatched += 1
        logger.info(
            "SequentialTopN: type-stage dispatch завершён "
            "(run_id=%d, benchmark=%s, table=%s.%s, jobs=%d)",
            benchmark_run_id,
            table_plan.benchmark_id,
            table_plan.database,
            table_plan.table,
            type_dispatched,
        )
        _wait_for_dispatched_tasks_if_supported(
            runner=runner,
            stage_label=(
                f"sequential stage1 types: {table_plan.benchmark_id} "
                f"{table_plan.database}.{table_plan.table}"
            ),
        )

        ranked_type_variants = _wait_for_type_stage_completion(
            runner=runner,
            table_plan=table_plan,
            benchmark_run_id=benchmark_run_id,
            type_total=type_total,
        )
        top_n = min(table_plan.sequential_top_n, type_total)
        top_variants = ranked_type_variants[:top_n]
        if not top_variants:
            logger.info(
                "SequentialTopN: top-N пуст, index-stage пропущен "
                "(run_id=%d, benchmark=%s, table=%s.%s)",
                benchmark_run_id,
                table_plan.benchmark_id,
                table_plan.database,
                table_plan.table,
            )
            return

        logger.info(
            "SequentialTopN: index-stage dispatch "
            "(run_id=%d, benchmark=%s, table=%s.%s, top_n=%d)",
            benchmark_run_id,
            table_plan.benchmark_id,
            table_plan.database,
            table_plan.table,
            len(top_variants),
        )
        _open_progress_scope_if_supported(
            runner=runner,
            scope_name=(
                f"sequential stage2 indexes: {table_plan.benchmark_id} "
                f"{table_plan.database}.{table_plan.table}"
            ),
        )
        index_dispatched = 0
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
            index_dispatched += 1
        logger.info(
            "SequentialTopN: index-stage dispatch завершён "
            "(run_id=%d, benchmark=%s, table=%s.%s, jobs=%d)",
            benchmark_run_id,
            table_plan.benchmark_id,
            table_plan.database,
            table_plan.table,
            index_dispatched,
        )
        _wait_for_dispatched_tasks_if_supported(
            runner=runner,
            stage_label=(
                f"sequential stage2 indexes: {table_plan.benchmark_id} "
                f"{table_plan.database}.{table_plan.table}"
            ),
        )
