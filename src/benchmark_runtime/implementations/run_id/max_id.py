"""Max-id-backed run-id provider implementation."""

from __future__ import annotations

from typing import Callable, Optional

from ...contracts.run_id import BenchmarkRunIdProvider


class MaxIdBenchmarkRunIdProvider(BenchmarkRunIdProvider):
    """Run-id provider based on observed `max(existing_run_id)` getter."""

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
