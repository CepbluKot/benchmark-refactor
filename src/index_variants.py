"""
Генератор вариантов TableDDL с изменёнными skip-индексами.
Типы и кодеки колонок не трогаются.

Логика перебора:
  - Для каждой matched колонки есть список вариантов индексов.
  - Берём декартово произведение: для каждой колонки выбираем один индекс.
  - Все выбранные индексы добавляются к таблице (существующие индексы заменяются).
  - None = не добавлять индекс для этой колонки.
"""

from __future__ import annotations

import itertools
from copy import deepcopy
from pydantic import BaseModel, Field
from typing import Dict, Generator, List, Optional, Tuple

from clickhouse_ddl import IndexDef, TableDDL
from index_rules import IndexAlternatives, IndexRule


# ─── метаданные варианта ──────────────────────────────────────────────────────

class IndexVariantMeta(BaseModel):
    """Метаданные одного index-варианта: индекс и выбранные индексы по колонкам."""

    index: int
    # {col_name: IndexDef | None}  None = индекс не добавлен для этой колонки
    index_choices: Dict[str, Optional[IndexDef]]


# ─── внутренний резолвинг ────────────────────────────────────────────────────

def _resolve_index_columns(
    table: TableDDL,
    rules: List[IndexRule],
    column_order: Optional[Dict[str, int]] = None,
) -> List[Tuple[str, IndexAlternatives]]:
    """
    Матчит колонки по index-правилам (первое совпадение побеждает).
    Порядок:
      - если передан column_order, сортировка по нему (меньше = раньше);
      - иначе порядок колонок в таблице.
    """
    matched: Dict[str, IndexAlternatives] = {}
    for col in table.columns:
        for rule in rules:
            if rule.matches(col):
                matched[col.name] = rule.alternatives
                break

    if not column_order:
        return [(name, matched[name]) for name in matched]

    inf = float("inf")
    ordered = sorted(matched, key=lambda col_name: column_order.get(col_name, inf))
    return [(name, matched[name]) for name in ordered]


# ─── генератор ───────────────────────────────────────────────────────────────

def iter_index_variants(
    table: TableDDL,
    rules: List[IndexRule],
    column_order: Optional[Dict[str, int]] = None,
) -> Generator[Tuple[TableDDL, IndexVariantMeta], None, None]:
    """
    Генерирует все варианты TableDDL с разными наборами skip-индексов.
    Типы и кодеки колонок не трогаются.

    Для каждой matched-колонки перебираются все варианты индексов из правила.
    Между колонками — декартово произведение.
    Если передан `column_order`, он влияет на порядок перебора колонок.

    Yields: (variant_table, meta)
    """
    resolved = _resolve_index_columns(table, rules, column_order=column_order)

    if not resolved:
        yield table.copy(), IndexVariantMeta(index=0, index_choices={})
        return

    col_names = [name for name, _ in resolved]
    # Для каждой колонки список Optional[IndexDef]
    # None добавляем в начало — вариант «без индекса для этой колонки»
    variant_lists: List[List[Optional[IndexDef]]] = []
    for col_name, alt in resolved:
        col = table.column(col_name)
        col_variants: List[Optional[IndexDef]] = [None]  # без индекса
        for idx_def in alt.iter_variants(col):
            col_variants.append(idx_def)
        variant_lists.append(col_variants)

    for global_idx, combo in enumerate(itertools.product(*variant_lists)):
        variant = table.copy()

        # Убираем все старые индексы для matched-колонок, оставляем остальные
        matched_exprs = set(col_names)
        kept_indexes = [
            idx for idx in variant.indexes
            if idx.expr not in matched_exprs
        ]

        choices: Dict[str, Optional[IndexDef]] = {}
        new_indexes = list(kept_indexes)

        for col_name, idx_def in zip(col_names, combo):
            choices[col_name] = deepcopy(idx_def) if idx_def else None
            if idx_def is not None:
                new_indexes.append(deepcopy(idx_def))

        variant.indexes = new_indexes

        yield variant, IndexVariantMeta(index=global_idx, index_choices=choices)


def total_index_variants(
    table: TableDDL,
    rules: List[IndexRule],
    column_order: Optional[Dict[str, int]] = None,
) -> int:
    """Количество вариантов (включая «без индекса» для каждой колонки)."""
    resolved = _resolve_index_columns(table, rules, column_order=column_order)
    n = 1
    for _, alt in resolved:
        n *= (alt.total() + 1)  # +1 за вариант None
    return n
