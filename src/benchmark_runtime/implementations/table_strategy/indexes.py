"""Indexes-only table-level execution strategy implementation."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from ...contracts.table_strategy import TableExecutionStrategy
from ...types import TableBenchmarkPlan

if TYPE_CHECKING:
    from benchmark_engine import BenchmarkRunner


class IndexesTableExecutionStrategy(TableExecutionStrategy):
    """Executes only regular `indexes` variant jobs for a table."""

    def execute_table(
        self,
        runner: "BenchmarkRunner",
        table_plan: TableBenchmarkPlan,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
    ) -> None:
        runner._execute_regular_table(
            table_plan=table_plan,
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
        )
