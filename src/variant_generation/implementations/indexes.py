"""Indexes-only variant-generation strategy."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from src.clickhouse_ddl import TableDDL
from src.column_rules import ColumnRule
from src.index_rules import IndexRule
from src.index_variants import iter_index_variants, total_index_variants

from ..contracts import VariantGenerationStrategy
from ..types import VariantMeta


class IndexesVariantGenerationStrategy(VariantGenerationStrategy):
    """Generates only index variants."""

    def iter_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
        table_index_granularity_values: Optional[List[int]] = None,
    ) -> Iterable[Tuple[TableDDL, VariantMeta]]:
        # Для indexes-стратегии column_rules не используются.
        for variant, idx_meta in iter_index_variants(
            table,
            index_rules,
            column_order=column_order,
            table_index_granularity_values=table_index_granularity_values,
        ):
            yield variant, VariantMeta(
                global_index=0,
                mode="indexes",
                index_meta=idx_meta,
                table_index_granularity=idx_meta.table_index_granularity,
            )

    def total_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
        table_index_granularity_values: Optional[List[int]] = None,
    ) -> int:
        # Для indexes-стратегии column_rules не используются.
        return total_index_variants(
            table,
            index_rules,
            column_order,
            table_index_granularity_values=table_index_granularity_values,
        )
