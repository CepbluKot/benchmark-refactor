"""Result-store contract and backward-compatible exports."""

from .contracts.result_store import BenchmarkResultStore
from .implementations.clickhouse_celery.result_store import (
    ClickHouseBenchmarkResultStore,
)
from .implementations.inmemory.result_store import InMemoryBenchmarkResultStore

__all__ = [
    "BenchmarkResultStore",
    "InMemoryBenchmarkResultStore",
    "ClickHouseBenchmarkResultStore",
]
