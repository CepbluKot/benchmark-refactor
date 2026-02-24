"""Table strategy contract and backward-compatible exports."""

from .contracts.table_strategy import TableExecutionStrategy
from .implementations.table_strategy.combined import CombinedTableExecutionStrategy
from .implementations.table_strategy.default import DefaultTableExecutionStrategy
from .implementations.table_strategy.indexes import IndexesTableExecutionStrategy
from .implementations.table_strategy.sequential_topn import (
    SequentialTopNTableExecutionStrategy,
)
from .implementations.table_strategy.types import TypesTableExecutionStrategy

__all__ = [
    "CombinedTableExecutionStrategy",
    "TableExecutionStrategy",
    "DefaultTableExecutionStrategy",
    "IndexesTableExecutionStrategy",
    "SequentialTopNTableExecutionStrategy",
    "TypesTableExecutionStrategy",
]
