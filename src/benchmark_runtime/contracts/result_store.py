"""Result store contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from ..types import (
    BenchmarkVariantResult,
    StoredVariantSummary,
    TopTypeVariant,
    VariantJob,
)
from ..types import Query, ScoringConfig, TableBenchmarkPlan


class BenchmarkResultStore(ABC):
    """Persistent result-store contract used by benchmark runner."""

    @abstractmethod
    def store_result(
        self,
        job: VariantJob,
        result: BenchmarkVariantResult,
    ) -> None:
        """Stores result of one variant execution."""
        pass

    @abstractmethod
    def get_top_type_variants(
        self,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        top_n: int,
    ) -> List[TopTypeVariant]:
        """Returns ranked top-N type variants for sequential index stage."""
        pass

    def list_variant_summaries(
        self,
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        variant_modes: Optional[Sequence[str]] = None,
    ) -> List[StoredVariantSummary]:
        """
        Возвращает lightweight summary результатов вариантов.

        По умолчанию метод не реализован. Стратегии, которые используют
        multi-phase top-N, требуют store с этой возможностью.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} не реализует list_variant_summaries()"
        )

    def get_top_variants(
        self,
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        top_n: int,
        variant_modes: Sequence[str],
    ) -> List[TopTypeVariant]:
        """
        Возвращает top-N вариантов по заданным mode.

        Базовая реализация сохраняет backward-compatibility:
        поддерживает только case `variant_modes=["types"]`.
        """
        normalized_modes = [str(mode).strip() for mode in variant_modes if str(mode).strip()]
        if normalized_modes == ["types"]:
            return self.get_top_type_variants(
                benchmark_run_id=benchmark_run_id,
                benchmark_id=benchmark_id,
                source_database=source_database,
                source_table=source_table,
                top_n=top_n,
            )
        raise NotImplementedError(
            f"{self.__class__.__name__} не реализует get_top_variants() "
            f"для variant_modes={normalized_modes!r}"
        )

    def register_benchmark_run_start(
        self,
        *,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
        table_plan: TableBenchmarkPlan,
        source_table_ddl: str,
        benchmark_queries: Sequence[Query],
        total_rows: Optional[int],
        scoring: ScoringConfig,
    ) -> None:
        """Опционально регистрирует старт run-контекста в persistent store."""
        return None

    def register_benchmark_run_finish(
        self,
        *,
        benchmark_run_id: int,
        table_plan: TableBenchmarkPlan,
        benchmark_finished_at: datetime,
    ) -> None:
        """Опционально фиксирует `finished_at` для run-контекста."""
        return None

    def recalculate_phase_ranking(
        self,
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        phase: Optional[int] = None,
        variant_mode: Optional[str] = None,
        phase_name: Optional[str] = None,
    ) -> None:
        """
        Опционально пересчитывает `rank_in_phase`/`is_top_n` для scope фазы.

        По умолчанию no-op: полезно для in-memory store и store без rank-колонок.
        """
        return None

    def mark_top_n_variant_tables(
        self,
        *,
        benchmark_run_id: int,
        benchmark_id: str,
        source_database: str,
        source_table: str,
        winner_variant_tables: Sequence[str],
        phase: Optional[int] = None,
        variant_mode: Optional[str] = None,
        phase_name: Optional[str] = None,
    ) -> None:
        """
        Опционально помечает `is_top_n=1` только у переданных winner-variant-таблиц.

        Нужен стратегиям, где top-N определяется не просто глобальным rank, а
        фактическим списком вариантов, прошедших в следующую стадию.
        """
        return None

    def recalculate_custom_score_for_benchmark(
        self,
        *,
        benchmark_id: str,
        expression: str,
        benchmark_run_id: Optional[int] = None,
        source_database: Optional[str] = None,
        source_table: Optional[str] = None,
        target_tables: str = "phased",
    ) -> Dict[str, Dict[str, int]]:
        """
        Опционально пересчитывает кастомный score в дополнительную колонку.

        Базовая реализация — no-op, возвращает пустой результат.
        """
        del (
            benchmark_id,
            expression,
            benchmark_run_id,
            source_database,
            source_table,
            target_tables,
        )
        return {}
