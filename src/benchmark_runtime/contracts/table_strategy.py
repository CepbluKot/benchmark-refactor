"""Table-level execution strategy contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

from ..types import TableBenchmarkPlan

if TYPE_CHECKING:
    from src.benchmark_engine import BenchmarkRunner


class TableExecutionStrategy(ABC):
    """Strategy for executing one table-level benchmark plan."""

    @abstractmethod
    def execute_table(
        self,
        runner: "BenchmarkRunner",
        table_plan: TableBenchmarkPlan,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
    ) -> None:
        """Executes whole table plan and persists results via runner."""
        pass
