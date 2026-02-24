"""Runtime contracts and built-in implementations for benchmark engine."""

from .execution import BenchmarkExecutionAdapter, NoopExecutionAdapter
from .metadata import FetcherMetadataProvider, MetadataProvider
from .result_store import BenchmarkResultStore, InMemoryBenchmarkResultStore
from .run_id import (
    BenchmarkRunIdProvider,
    InMemoryBenchmarkRunIdProvider,
    MaxIdBenchmarkRunIdProvider,
)
from .table_strategy import (
    CombinedTableExecutionStrategy,
    DefaultTableExecutionStrategy,
    IndexesTableExecutionStrategy,
    SequentialTopNDispatchIndexesTableExecutionStrategy,
    SequentialTopNDispatchTypesTableExecutionStrategy,
    SequentialTopNTableExecutionStrategy,
    TableExecutionStrategy,
    TypesTableExecutionStrategy,
)
from .types import (
    BenchmarkVariantResult,
    Query,
    QueryPlan,
    StoredBenchmarkResult,
    TableBenchmarkPlan,
    TableTarget,
    TopTypeVariant,
    VariantJob,
)

__all__ = [
    "BenchmarkExecutionAdapter",
    "NoopExecutionAdapter",
    "FetcherMetadataProvider",
    "MetadataProvider",
    "BenchmarkResultStore",
    "InMemoryBenchmarkResultStore",
    "BenchmarkRunIdProvider",
    "InMemoryBenchmarkRunIdProvider",
    "MaxIdBenchmarkRunIdProvider",
    "CombinedTableExecutionStrategy",
    "DefaultTableExecutionStrategy",
    "IndexesTableExecutionStrategy",
    "SequentialTopNDispatchIndexesTableExecutionStrategy",
    "SequentialTopNDispatchTypesTableExecutionStrategy",
    "SequentialTopNTableExecutionStrategy",
    "TableExecutionStrategy",
    "TypesTableExecutionStrategy",
    "BenchmarkVariantResult",
    "Query",
    "QueryPlan",
    "StoredBenchmarkResult",
    "TableBenchmarkPlan",
    "TableTarget",
    "TopTypeVariant",
    "VariantJob",
]
