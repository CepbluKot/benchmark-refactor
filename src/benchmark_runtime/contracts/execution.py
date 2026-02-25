"""Контракт адаптера выполнения."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

from ..types import (
    BenchmarkVariantResult,
    SourceBenchmarkJob,
    SourceBenchmarkResult,
    VariantJob,
)

if TYPE_CHECKING:
    from .result_store import BenchmarkResultStore


class BenchmarkExecutionAdapter(ABC):
    """Контракт для backend-реализаций фактического выполнения бенчмарка."""

    @abstractmethod
    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        """Выполняет один вариант и возвращает результат бенчмарка."""
        pass

    def execute_source_benchmark(self, job: SourceBenchmarkJob) -> SourceBenchmarkResult:
        """
        Выполняет baseline-бенчмарк исходного DDL.

        Поведение по умолчанию возвращает baseline только с метаданными.
        Продакшн-адаптеры должны переопределить метод и выполнить
        реальные baseline-замеры.
        """
        return SourceBenchmarkResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            source_table_ddl=job.source_table_ddl.to_ddl(),
            score=None,
            metrics={},
        )

    def bind_result_store(self, result_store: Optional["BenchmarkResultStore"]) -> None:
        """
        Опциональный lifecycle-hook.

        Runner вызывает этот метод один раз при инициализации, чтобы адаптер
        при необходимости мог сам сохранять результаты (например, имитировать
        worker-side сохранение в тестах/демо).
        """
        # Базовая реализация ничего не делает.
        return None
