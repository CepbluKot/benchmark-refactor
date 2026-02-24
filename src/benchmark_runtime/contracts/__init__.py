"""Core runtime interfaces used by benchmark orchestration layers."""

from .execution import BenchmarkExecutionAdapter
from .metadata import MetadataProvider
from .result_store import BenchmarkResultStore
from .run_id import BenchmarkRunIdProvider
from .table_strategy import TableExecutionStrategy

__all__ = [
    "BenchmarkExecutionAdapter",
    "MetadataProvider",
    "BenchmarkResultStore",
    "BenchmarkRunIdProvider",
    "TableExecutionStrategy",
]
