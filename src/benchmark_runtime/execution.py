"""Execution contract and backward-compatible exports."""

from .contracts.execution import BenchmarkExecutionAdapter
from .implementations.clickhouse_celery.execution import (
    CeleryClickHouseExecutionAdapter,
)
from .implementations.noop.execution import NoopExecutionAdapter

__all__ = [
    "BenchmarkExecutionAdapter",
    "NoopExecutionAdapter",
    "CeleryClickHouseExecutionAdapter",
]
