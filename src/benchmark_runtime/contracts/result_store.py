"""Result store contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..types import BenchmarkVariantResult, TopTypeVariant, VariantJob


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
