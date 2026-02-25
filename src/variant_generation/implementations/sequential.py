"""Sequential variant-generation strategy (types then indexes)."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from src.clickhouse_ddl import TableDDL
from src.column_rules import ColumnRule
from src.column_variants import iter_column_variants, total_column_variants
from src.index_rules import IndexRule
from src.index_variants import iter_index_variants, total_index_variants

from ..contracts import VariantGenerationStrategy
from ..types import VariantMeta


class SequentialVariantGenerationStrategy(VariantGenerationStrategy):
    """
    Generates `types` and `indexes` variants sequentially.

    Note: this is combiner-level sequencing; top-N orchestration is done by runner.
    """

    def iter_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
        table_index_granularity_values: Optional[List[int]] = None,
    ) -> Iterable[Tuple[TableDDL, VariantMeta]]:
        for variant, col_meta in iter_column_variants(table, column_rules, column_order):
            yield variant, VariantMeta(
                global_index=0,
                mode="sequential",
                column_meta=col_meta,
            )
        for variant, idx_meta in iter_index_variants(
            table,
            index_rules,
            column_order=column_order,
            table_index_granularity_values=table_index_granularity_values,
        ):
            yield variant, VariantMeta(
                global_index=0,
                mode="sequential",
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
        col_total = total_column_variants(table, column_rules, column_order)
        idx_total = total_index_variants(
            table,
            index_rules,
            column_order,
            table_index_granularity_values=table_index_granularity_values,
        )
        return col_total + idx_total
