"""No-op execution adapter implementation."""

from __future__ import annotations

from ...contracts.execution import BenchmarkExecutionAdapter
from ...types import BenchmarkVariantResult, VariantJob


class NoopExecutionAdapter(BenchmarkExecutionAdapter):
    """Dry-run adapter that only returns planned metadata."""

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        return BenchmarkVariantResult(
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
