"""
Генератор вариантов TableDDL с изменёнными типами и кодеками колонок.
"""

from __future__ import annotations

import itertools
from copy import deepcopy
from pydantic import BaseModel, Field
from typing import Dict, Generator, List, Optional, Tuple

from clickhouse_ddl import ColumnDef, TableDDL
from column_rules import ColumnAlternatives, ColumnRule


# ─── метаданные варианта ──────────────────────────────────────────────────────

class ColumnVariantMeta(BaseModel):
    """Метаданные одного column-варианта: индекс и выбранные (type, codec) по колонкам."""

    index: int
    column_choices: Dict[str, Tuple[Optional[str], Optional[str]]]  # {name: (type, codec)}


# ─── внутренний резолвинг правил к колонкам ───────────────────────────────────

def _resolve_columns(
    table: TableDDL,
    rules: List[ColumnRule],
    column_order: Dict[str, int],
) -> List[Tuple[str, ColumnAlternatives]]:
    """
    Матчит колонки таблицы по правилам (первое совпадение побеждает),
    сортирует по column_order.
    """
    matched: Dict[str, ColumnAlternatives] = {}
    for col in table.columns:
        for rule in rules:
            if rule.matches(col):
                matched[col.name] = rule.alternatives
                break

    INF = float("inf")
    ordered = sorted(matched, key=lambda n: column_order.get(n, INF))
    return [(name, matched[name]) for name in ordered]


# ─── генератор ───────────────────────────────────────────────────────────────

def iter_column_variants(
    table: TableDDL,
    rules: List[ColumnRule],
    column_order: Optional[Dict[str, int]] = None,
) -> Generator[Tuple[TableDDL, ColumnVariantMeta], None, None]:
    """
    Генерирует все варианты TableDDL с изменёнными типами / кодеками.
    Индексы таблицы не трогаются.

    Yields: (variant_table, meta)
    """
    order = column_order or {}
    resolved = _resolve_columns(table, rules, order)

    if not resolved:
        yield table.copy(), ColumnVariantMeta(index=0, column_choices={})
        return

    col_names = [name for name, _ in resolved]
    combo_lists = [
        list(alt.iter_combos(table.column(name)))
        for name, alt in resolved
    ]

    for idx, combos in enumerate(itertools.product(*combo_lists)):
        variant = table.copy()
        choices: Dict[str, Tuple[Optional[str], Optional[str]]] = {}

        for col_name, (new_type, new_codec) in zip(col_names, combos):
            col = variant.column(col_name)
            if new_type is not None:
                col.type = new_type
            col.codec = new_codec
            choices[col_name] = (col.type, col.codec)

        yield variant, ColumnVariantMeta(index=idx, column_choices=choices)


def total_column_variants(
    table: TableDDL,
    rules: List[ColumnRule],
    column_order: Optional[Dict[str, int]] = None,
) -> int:
    """Подсчитывает число column-вариантов без материализации самих таблиц."""
    resolved = _resolve_columns(table, rules, column_order or {})
    n = 1
    for col_name, alt in resolved:
        n *= alt.total(table.column(col_name))
    return n
