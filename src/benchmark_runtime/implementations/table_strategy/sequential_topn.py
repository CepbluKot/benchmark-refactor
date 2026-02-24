"""Sequential top-N table-level execution strategy implementation."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from src.combiner import iter_variants, total_variants

from ...contracts.table_strategy import TableExecutionStrategy
from ...types import TableBenchmarkPlan

if TYPE_CHECKING:
    from src.benchmark_engine import BenchmarkRunner


class SequentialTopNTableExecutionStrategy(TableExecutionStrategy):
    """Two-stage execution for `strategy="sequential_topn_strategy"` plans."""

    def execute_table(
        self,
        runner: "BenchmarkRunner",
        table_plan: TableBenchmarkPlan,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
    ) -> None:
        source_ddl, raw_query_plan = runner._engine.prepare_table_context(table_plan)
        effective_column_order = runner._engine.resolve_column_order(
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
            job = runner._engine.build_variant_job(
                table_plan=table_plan,
                raw_query_plan=raw_query_plan,
                variant_ddl=variant_ddl,
                variant_meta=variant_meta,
                total_variants=type_total,
                benchmark_run_id=benchmark_run_id,
                benchmark_started_at=benchmark_started_at,
                job_mode="sequential",
            )
            runner._execute_and_store(job)

        if type_total <= 0:
            return

        top_n = min(table_plan.sequential_top_n, type_total)
        top_variants = runner._result_store.get_top_type_variants(
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
                index_meta.global_index = next_global_index
                next_global_index += 1
                index_job = runner._engine.build_variant_job(
                    table_plan=table_plan,
                    raw_query_plan=raw_query_plan,
                    variant_ddl=variant_ddl,
                    variant_meta=index_meta,
                    total_variants=index_total,
                    benchmark_run_id=benchmark_run_id,
                    benchmark_started_at=benchmark_started_at,
                    job_mode="sequential",
                )
                runner._execute_and_store(index_job)
