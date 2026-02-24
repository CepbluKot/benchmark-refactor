"""Built-in table-level execution strategies."""

from .combined import CombinedTableExecutionStrategy
from .default import DefaultTableExecutionStrategy
from .indexes import IndexesTableExecutionStrategy
from .sequential_topn import (
    SequentialTopNDispatchIndexesTableExecutionStrategy,
    SequentialTopNDispatchTypesTableExecutionStrategy,
    SequentialTopNTableExecutionStrategy,
)
from .types import TypesTableExecutionStrategy

__all__ = [
    "CombinedTableExecutionStrategy",
    "DefaultTableExecutionStrategy",
    "IndexesTableExecutionStrategy",
    "SequentialTopNDispatchIndexesTableExecutionStrategy",
    "SequentialTopNDispatchTypesTableExecutionStrategy",
    "SequentialTopNTableExecutionStrategy",
    "TypesTableExecutionStrategy",
]
