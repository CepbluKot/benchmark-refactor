"""In-memory result store implementation."""

from __future__ import annotations

from typing import List

from ...contracts.result_store import BenchmarkResultStore
from ...types import (
    BenchmarkVariantResult,
    StoredBenchmarkResult,
    TopTypeVariant,
    VariantJob,
)


class InMemoryBenchmarkResultStore(BenchmarkResultStore):
    """In-memory result store implementation for tests and dry-run flows."""

    def __init__(self) -> None:
        self._records: List[StoredBenchmarkResult] = []

    @property
    def records(self) -> List[StoredBenchmarkResult]:
        """Returns a copy of persisted records."""
        return list(self._records)

    def store_result(
        self,
        job: VariantJob,
        result: BenchmarkVariantResult,
    ) -> None:
        """Stores result and the effective variant DDL snapshot."""
        if result.benchmark_run_id != job.benchmark_run_id:
            raise ValueError(
                "result.benchmark_run_id не совпадает с job.benchmark_run_id"
            )
        if (
            result.benchmark_started_at is not None
            and result.benchmark_started_at != job.benchmark_started_at
        ):
            raise ValueError(
                "result.benchmark_started_at не совпадает с job.benchmark_started_at"
            )
        if result.benchmark_id != job.benchmark_id:
            raise ValueError("result.benchmark_id не совпадает с job.benchmark_id")

        self._records.append(
            StoredBenchmarkResult(
                benchmark_run_id=job.benchmark_run_id,
                benchmark_started_at=job.benchmark_started_at,
                benchmark_id=job.benchmark_id,
                source_database=job.source_database,
                source_table=job.source_table,
                variant_table=job.variant_table,
                variant_index=job.variant_meta.global_index,
                variant_mode=job.variant_meta.mode,
                score=result.score,
                variant_ddl=job.variant_ddl.copy(),
                payload=dict(result.payload),
            )
        )

    def get_top_type_variants(
        self,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        top_n: int,
    ) -> List[TopTypeVariant]:
        """Ranks and returns top-N type variants."""
        if top_n <= 0:
            return []

        candidates = [
            record
            for record in self._records
            if record.benchmark_run_id == benchmark_run_id
            and record.benchmark_id == benchmark_id
            and record.source_database == source_database
            and record.source_table == source_table
            and record.variant_mode == "types"
        ]
        ranked = sorted(
            candidates,
            key=lambda record: (
                record.score is None,
                -(record.score if record.score is not None else 0.0),
                record.variant_index,
            ),
        )
        return [
            TopTypeVariant(
                variant_index=record.variant_index,
                variant_ddl=record.variant_ddl.copy(),
                score=record.score,
            )
            for record in ranked[:top_n]
        ]
