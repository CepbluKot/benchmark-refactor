"""Benchmark run-id provider contract."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BenchmarkRunIdProvider(ABC):
    """Provider of monotonically increasing benchmark run ids."""

    @abstractmethod
    def next_benchmark_run_id(self) -> int:
        """Returns next run id (> 0)."""
        pass
