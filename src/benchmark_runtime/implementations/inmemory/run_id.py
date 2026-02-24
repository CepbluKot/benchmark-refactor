"""In-memory run-id provider implementation."""

from __future__ import annotations

from ...contracts.run_id import BenchmarkRunIdProvider


class InMemoryBenchmarkRunIdProvider(BenchmarkRunIdProvider):
    """Simple in-memory serial provider: 1, 2, 3, ..."""

    def __init__(self, start_from: int = 0) -> None:
        self._last_run_id = start_from

    def next_benchmark_run_id(self) -> int:
        self._last_run_id += 1
        return self._last_run_id
