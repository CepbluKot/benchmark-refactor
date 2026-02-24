"""Sequential variant-generation strategy (types then indexes)."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from clickhouse_ddl import TableDDL
from column_rules import ColumnRule
from column_variants import iter_column_variants, total_column_variants
from index_rules import IndexRule
from index_variants import iter_index_variants, total_index_variants

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
        ):
            yield variant, VariantMeta(
                global_index=0,
                mode="sequential",
                index_meta=idx_meta,
            )

    def total_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
    ) -> int:
        col_total = total_column_variants(table, column_rules, column_order)
        idx_total = total_index_variants(table, index_rules, column_order)
        return col_total + idx_total
