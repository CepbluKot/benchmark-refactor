"""Combined variant-generation strategy (cartesian types x indexes)."""

from __future__ import annotations

from copy import deepcopy
from typing import Dict, Iterable, List, Optional, Tuple

from src.clickhouse_ddl import TableDDL
from src.column_rules import ColumnRule
from src.column_variants import iter_column_variants, total_column_variants
from src.index_rules import IndexRule
from src.index_variants import IndexVariantMeta, iter_index_variants, total_index_variants

from ..contracts import VariantGenerationStrategy
from ..types import VariantMeta


class CombinedVariantGenerationStrategy(VariantGenerationStrategy):
    """Generates cartesian product of column and index variants."""

    def iter_variants(
        self,
        table: TableDDL,
        column_rules: List[ColumnRule],
        index_rules: List[IndexRule],
        column_order: Optional[Dict[str, int]] = None,
    ) -> Iterable[Tuple[TableDDL, VariantMeta]]:
        index_variants_list = list(
            iter_index_variants(table, index_rules, column_order=column_order)
        )
        for col_variant, col_meta in iter_column_variants(table, column_rules, column_order):
            for idx_variant_base, idx_meta_base in index_variants_list:
                combined = col_variant.copy()
                combined.indexes = [idx for idx in idx_variant_base.indexes]
                final_idx_meta = IndexVariantMeta(
                    index=idx_meta_base.index,
                    index_choices=deepcopy(idx_meta_base.index_choices),
                )
                yield combined, VariantMeta(
                    global_index=0,
                    mode="combined",
                    column_meta=col_meta,
                    index_meta=final_idx_meta,
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
        return col_total * idx_total
