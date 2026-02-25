"""Indexes-only table-level execution strategy implementation."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import TYPE_CHECKING

from ...contracts.table_strategy import TableExecutionStrategy
from ...types import TableBenchmarkPlan

if TYPE_CHECKING:
    from src.benchmark_engine import BenchmarkRunner

logger = logging.getLogger(__name__)
_STAGE_BANNER_LINE = "=" * 92


class IndexesTableExecutionStrategy(TableExecutionStrategy):
    """Executes only regular `indexes` variant jobs for a table."""

    def execute_table(
        self,
        runner: "BenchmarkRunner",
        table_plan: TableBenchmarkPlan,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
    ) -> None:
        logger.info(_STAGE_BANNER_LINE)
        logger.info(
            "СТАРТ СТАДИИ: ИНДЕКСЫ | run_id=%d | benchmark=%s | table=%s.%s",
            benchmark_run_id,
            table_plan.benchmark_id,
            table_plan.database,
            table_plan.table,
        )
        logger.info(_STAGE_BANNER_LINE)
        logger.info(
            "IndexesTableExecutionStrategy: выполнение table plan "
            "(run_id=%d, benchmark=%s, table=%s.%s)",
            benchmark_run_id,
            table_plan.benchmark_id,
            table_plan.database,
            table_plan.table,
        )
        runner._execute_regular_table(
            table_plan=table_plan,
            benchmark_run_id=benchmark_run_id,
            benchmark_started_at=benchmark_started_at,
        )
