"""
Комбинатор вариантов по mode.

Этот модуль оставлен как публичный фасад (backward-compatible import path).
Фактические контракт и built-in реализации генерации вынесены в пакет
`variant_generation`.
"""

from __future__ import annotations

from typing import Dict, Generator, List, Optional, Tuple

from src.clickhouse_ddl import TableDDL
from src.column_rules import ColumnRule
from src.index_rules import IndexRule
from src.variant_generation import (
    CombinedVariantGenerationStrategy,
    IndexesVariantGenerationStrategy,
    MODE_VARIANT_STRATEGIES,
    SequentialVariantGenerationStrategy,
    TypesVariantGenerationStrategy,
    VariantGenerationStrategy,
    VariantMeta,
    get_variant_generation_strategy,
    register_variant_generation_strategy,
)


def _iter_strategy_variants_with_compat(
    strategy: VariantGenerationStrategy,
    *,
    table: TableDDL,
    column_rules: List[ColumnRule],
    index_rules: List[IndexRule],
    column_order: Optional[Dict[str, int]],
    table_index_granularity_values: Optional[List[int]],
):
    """Вызывает strategy.iter_variants с backward-compatible fallback."""
    try:
        return strategy.iter_variants(
            table=table,
            column_rules=column_rules,
            index_rules=index_rules,
            column_order=column_order,
            table_index_granularity_values=table_index_granularity_values,
        )
    except TypeError as exc:
        if "table_index_granularity_values" not in str(exc):
            raise
        return strategy.iter_variants(
            table=table,
            column_rules=column_rules,
            index_rules=index_rules,
            column_order=column_order,
        )


def _strategy_total_with_compat(
    strategy: VariantGenerationStrategy,
    *,
    table: TableDDL,
    column_rules: List[ColumnRule],
    index_rules: List[IndexRule],
    column_order: Optional[Dict[str, int]],
    table_index_granularity_values: Optional[List[int]],
) -> int:
    """Вызывает strategy.total_variants с backward-compatible fallback."""
    try:
        return strategy.total_variants(
            table=table,
            column_rules=column_rules,
            index_rules=index_rules,
            column_order=column_order,
            table_index_granularity_values=table_index_granularity_values,
        )
    except TypeError as exc:
        if "table_index_granularity_values" not in str(exc):
            raise
        return strategy.total_variants(
            table=table,
            column_rules=column_rules,
            index_rules=index_rules,
            column_order=column_order,
        )


def iter_variants(
    table: TableDDL,
    mode: str,
    column_rules: List[ColumnRule],
    index_rules: List[IndexRule],
    column_order: Optional[Dict[str, int]] = None,
    table_index_granularity_values: Optional[List[int]] = None,
    max_iterations: Optional[int] = None,
) -> Generator[Tuple[TableDDL, VariantMeta], None, None]:
    """
    Главная точка входа. Генерирует варианты TableDDL по заданному mode.

    Args:
        table: исходная таблица.
        mode: режим перебора.
        column_rules: правила для типов/кодеков.
        index_rules: правила для индексов.
        column_order: приоритет перебора колонок.
        table_index_granularity_values: перебор значений `SETTINGS index_granularity`.
        max_iterations: если задан — обрезает генератор после N вариантов.

    Yields:
        (variant_table, meta)
    """
    strategy = get_variant_generation_strategy(mode)
    gen = _iter_strategy_variants_with_compat(
        strategy,
        table=table,
        column_rules=column_rules,
        index_rules=index_rules,
        column_order=column_order,
        table_index_granularity_values=table_index_granularity_values,
    )
    for idx, (variant, meta) in enumerate(gen):
        if max_iterations is not None and idx >= max_iterations:
            return
        meta.global_index = idx
        yield variant, meta


def total_variants(
    table: TableDDL,
    mode: str,
    column_rules: List[ColumnRule],
    index_rules: List[IndexRule],
    column_order: Optional[Dict[str, int]] = None,
    table_index_granularity_values: Optional[List[int]] = None,
    max_iterations: Optional[int] = None,
) -> int:
    """Подсчитывает количество вариантов без их materialize."""
    strategy = get_variant_generation_strategy(mode)
    variants_count = _strategy_total_with_compat(
        strategy,
        table=table,
        column_rules=column_rules,
        index_rules=index_rules,
        column_order=column_order,
        table_index_granularity_values=table_index_granularity_values,
    )
    if max_iterations is not None:
        variants_count = min(variants_count, max_iterations)
    return variants_count


__all__ = [
    "CombinedVariantGenerationStrategy",
    "IndexesVariantGenerationStrategy",
    "MODE_VARIANT_STRATEGIES",
    "SequentialVariantGenerationStrategy",
    "TypesVariantGenerationStrategy",
    "VariantGenerationStrategy",
    "VariantMeta",
    "get_variant_generation_strategy",
    "iter_variants",
    "register_variant_generation_strategy",
    "total_variants",
]
