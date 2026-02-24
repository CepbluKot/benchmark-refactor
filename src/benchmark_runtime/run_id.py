"""Run-id contract and backward-compatible exports."""

from .contracts.run_id import BenchmarkRunIdProvider
from .implementations.inmemory.run_id import InMemoryBenchmarkRunIdProvider
from .implementations.run_id.max_id import MaxIdBenchmarkRunIdProvider

__all__ = [
    "BenchmarkRunIdProvider",
    "InMemoryBenchmarkRunIdProvider",
    "MaxIdBenchmarkRunIdProvider",
]
