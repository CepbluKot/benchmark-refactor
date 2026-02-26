"""Built-in table-level execution strategies."""

from .combined import CombinedTableExecutionStrategy
from .default import DefaultTableExecutionStrategy
from .indexes import IndexesTableExecutionStrategy
from .sequential_phased_topn import SequentialPhasedTopNTableExecutionStrategy
from .sequential_topn import SequentialTopNTableExecutionStrategy
from .types import TypesTableExecutionStrategy

__all__ = [
    "CombinedTableExecutionStrategy",
    "DefaultTableExecutionStrategy",
    "IndexesTableExecutionStrategy",
    "SequentialPhasedTopNTableExecutionStrategy",
    "SequentialTopNTableExecutionStrategy",
    "TypesTableExecutionStrategy",
]
