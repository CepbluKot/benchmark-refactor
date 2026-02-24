"""Execution adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

from ..types import BenchmarkVariantResult, VariantJob

if TYPE_CHECKING:
    from .result_store import BenchmarkResultStore


class BenchmarkExecutionAdapter(ABC):
    """Contract for physical variant execution backends."""

    @abstractmethod
    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        """Executes one variant and returns benchmark result."""
        pass

    def bind_result_store(self, result_store: Optional["BenchmarkResultStore"]) -> None:
        """
        Optional lifecycle hook.

        Runner calls this once during initialization so adapter can persist
        results itself (e.g. emulate worker-side persistence in tests/demos).
        """
        del result_store
