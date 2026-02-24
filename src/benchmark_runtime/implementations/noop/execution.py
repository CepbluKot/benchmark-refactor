"""No-op реализация адаптера выполнения."""

from __future__ import annotations

import logging
from typing import Optional

from ...contracts.execution import BenchmarkExecutionAdapter
from ...contracts.result_store import BenchmarkResultStore
from ...types import BenchmarkVariantResult, VariantJob
from ...types import SourceBenchmarkJob, SourceBenchmarkResult

logger = logging.getLogger(__name__)


class NoopExecutionAdapter(BenchmarkExecutionAdapter):
    """Dry-run адаптер, который возвращает только запланированные метаданные."""

    def __init__(self) -> None:
        """Создаёт адаптер без привязанного result store."""
        self._store: Optional[BenchmarkResultStore] = None

    def bind_result_store(self, result_store: Optional[BenchmarkResultStore]) -> None:
        """Запоминает store для тестового сохранения результатов."""
        self._store = result_store

    def execute_source_benchmark(self, job: SourceBenchmarkJob) -> SourceBenchmarkResult:
        """Возвращает baseline-результат без реального выполнения SQL."""
        logger.debug(
            "NoopExecutionAdapter: source baseline job "
            "(run_id=%d, benchmark=%s, table=%s.%s)",
            job.benchmark_run_id,
            job.benchmark_id,
            job.source_database,
            job.source_table,
        )
        return SourceBenchmarkResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            source_table_ddl=job.source_table_ddl.to_ddl(),
            score=None,
            metrics={"status": "planned_only"},
        )

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        """Возвращает dry-run результат и при наличии пишет его в store."""
        logger.debug(
            "NoopExecutionAdapter: variant job "
            "(run_id=%d, benchmark=%s, table=%s.%s, variant=%s, mode=%s, index=%d)",
            job.benchmark_run_id,
            job.benchmark_id,
            job.source_database,
            job.source_table,
            job.variant_table,
            job.variant_meta.mode,
            job.variant_meta.global_index,
        )
        result = BenchmarkVariantResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            variant_mode=job.variant_meta.mode,
            score=None,
            extra_json='{"status":"planned_only"}',
        )
        if self._store is not None:
            self._store.store_result(job, result)
        return result
