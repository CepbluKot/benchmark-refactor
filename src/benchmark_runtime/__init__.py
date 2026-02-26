"""Runtime contracts and built-in implementations for benchmark engine."""

from .execution import BenchmarkExecutionAdapter, NoopExecutionAdapter
from .metadata import FetcherMetadataProvider, MetadataProvider
from .result_store import (
    BenchmarkResultStore,
    ClickHouseBenchmarkResultStore,
    InMemoryBenchmarkResultStore,
)
from .run_id import (
    BenchmarkRunIdProvider,
    InMemoryBenchmarkRunIdProvider,
    MaxIdBenchmarkRunIdProvider,
)
from .implementations.clickhouse_celery import (
    CeleryClickHouseExecutionAdapter,
    ClickHouseConnectionParams,
    TaskMonitorCelery,
)
from .table_strategy import (
    CombinedTableExecutionStrategy,
    DefaultTableExecutionStrategy,
    IndexesTableExecutionStrategy,
    SequentialPhasedTopNTableExecutionStrategy,
    SequentialTopNTableExecutionStrategy,
    TableExecutionStrategy,
    TypesTableExecutionStrategy,
)
from .types import (
    BenchmarkVariantResult,
    Query,
    QueryPlan,
    SourceBenchmarkJob,
    SourceBenchmarkResult,
    StoredBenchmarkResult,
    StoredVariantSummary,
    TableBenchmarkPlan,
    TableTarget,
    TopTypeVariant,
    VariantJob,
    build_variant_params,
)

__all__ = [
    "BenchmarkExecutionAdapter",
    "NoopExecutionAdapter",
    "FetcherMetadataProvider",
    "MetadataProvider",
    "BenchmarkResultStore",
    "ClickHouseBenchmarkResultStore",
    "InMemoryBenchmarkResultStore",
    "BenchmarkRunIdProvider",
    "InMemoryBenchmarkRunIdProvider",
    "MaxIdBenchmarkRunIdProvider",
    "CombinedTableExecutionStrategy",
    "DefaultTableExecutionStrategy",
    "IndexesTableExecutionStrategy",
    "SequentialPhasedTopNTableExecutionStrategy",
    "SequentialTopNTableExecutionStrategy",
    "TableExecutionStrategy",
    "TypesTableExecutionStrategy",
    "CeleryClickHouseExecutionAdapter",
    "ClickHouseConnectionParams",
    "TaskMonitorCelery",
    "BenchmarkVariantResult",
    "Query",
    "QueryPlan",
    "SourceBenchmarkJob",
    "SourceBenchmarkResult",
    "StoredBenchmarkResult",
    "StoredVariantSummary",
    "TableBenchmarkPlan",
    "TableTarget",
    "TopTypeVariant",
    "VariantJob",
    "build_variant_params",
]
