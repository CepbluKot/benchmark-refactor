"""Types-only variant-generation strategy."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from src.clickhouse_ddl import TableDDL
from src.column_rules import ColumnRule
from src.column_variants import iter_column_variants, total_column_variants
from src.index_rules import IndexRule

from ..contracts import VariantGenerationStrategy
from ..types import VariantMeta


class TypesVariantGenerationStrategy(VariantGenerationStrategy):
    """Generates only type/codec variants."""

    def iter_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
        table_index_granularity_values: Optional[List[int]] = None,
    ) -> Iterable[Tuple[TableDDL, VariantMeta]]:
        # Для types-стратегии index_rules не используются.
        del table_index_granularity_values
        for variant, col_meta in iter_column_variants(table, column_rules, column_order):
            yield variant, VariantMeta(
                global_index=0,
                mode="types",
                column_meta=col_meta,
            )

    def total_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
        table_index_granularity_values: Optional[List[int]] = None,
    ) -> int:
        # Для types-стратегии index_rules не используются.
        del table_index_granularity_values
        return total_column_variants(table, column_rules, column_order)
