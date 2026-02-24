"""Variant-generation strategy contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Iterable, List, Optional, Tuple

from clickhouse_ddl import TableDDL
from column_rules import ColumnRule
from index_rules import IndexRule

from ..types import VariantMeta


class VariantGenerationStrategy(ABC):
    """Strategy that generates DDL variants for one mode."""

    @abstractmethod
    def iter_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
    ) -> Iterable[Tuple[TableDDL, VariantMeta]]:
        """Lazily yields `(variant_ddl, variant_meta)`."""
        pass

    @abstractmethod
    def total_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
    ) -> int:
        """Returns total count without materializing all variants."""
        pass
