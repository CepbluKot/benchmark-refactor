"""Execution adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..types import BenchmarkVariantResult, VariantJob


class BenchmarkExecutionAdapter(ABC):
    """Contract for physical variant execution backends."""

    @abstractmethod
    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        """Executes one variant and returns benchmark result."""
        pass
