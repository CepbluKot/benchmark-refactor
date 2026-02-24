"""No-op execution adapter implementation."""

from __future__ import annotations

from typing import Optional

from ...contracts.execution import BenchmarkExecutionAdapter
from ...contracts.result_store import BenchmarkResultStore
from ...types import BenchmarkVariantResult, VariantJob


class NoopExecutionAdapter(BenchmarkExecutionAdapter):
    """Dry-run adapter that only returns planned metadata."""

    def __init__(self) -> None:
        self._store: Optional[BenchmarkResultStore] = None

    def bind_result_store(self, result_store: Optional[BenchmarkResultStore]) -> None:
        self._store = result_store

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        result = BenchmarkVariantResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            variant_index=job.variant_meta.global_index,
            score=None,
            payload={"status": "planned_only"},
        )
        if self._store is not None:
            self._store.store_result(job, result)
        return result
