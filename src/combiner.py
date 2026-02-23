"""
Комбинатор вариантов по mode.

types      → только варианты типов/кодеков, индексы не трогаются
indexes    → только варианты индексов, типы не трогаются
sequential → сначала все варианты типов, потом все варианты индексов
             (индексные варианты применяются к исходной таблице, не к лучшему типовому —
              выбор лучшего типового варианта — задача runner/executor.py)
combined   → декартово произведение вариантов типов × вариантов индексов
"""

from __future__ import annotations

import itertools
from pydantic import BaseModel, Field
from typing import Dict, Generator, List, Literal, Optional, Tuple

from clickhouse_ddl import TableDDL
from column_rules import ColumnRule
from index_rules import IndexRule
from column_variants import ColumnVariantMeta, iter_column_variants, total_column_variants
from index_variants import IndexVariantMeta, iter_index_variants, total_index_variants


# ─── метаданные итогового варианта ───────────────────────────────────────────

class VariantMeta(BaseModel):
    """Метаданные одного варианта таблицы для бенчмарка."""
    global_index: int                               # сквозной номер
    mode: Literal["types", "indexes", "sequential", "combined"]
    column_meta: Optional[ColumnVariantMeta] = None
    index_meta: Optional[IndexVariantMeta] = None

    @property
    def column_choices(self):
        """Возвращает решения по колонкам для текущего варианта (если есть)."""
        return self.column_meta.column_choices if self.column_meta else {}

    @property
    def index_choices(self):
        """Возвращает решения по индексам для текущего варианта (если есть)."""
        return self.index_meta.index_choices if self.index_meta else {}


# ─── комбинатор ──────────────────────────────────────────────────────────────

def iter_variants(
    table: TableDDL,
    mode: Literal["types", "indexes", "sequential", "combined"],
    column_rules: List[ColumnRule],
    index_rules: List[IndexRule],
    column_order: Optional[Dict[str, int]] = None,
    max_iterations: Optional[int] = None,
) -> Generator[Tuple[TableDDL, VariantMeta], None, None]:
    """
    Главная точка входа. Генерирует варианты TableDDL по заданному mode.

    Args:
        table:          исходная таблица.
        mode:           режим перебора.
        column_rules:   правила для типов/кодеков.
        index_rules:    правила для индексов.
        column_order:   приоритет перебора колонок (для column и index вариантов).
        max_iterations: если задан — обрезает генератор после N вариантов.

    Yields: (variant_table, meta)
    """
    gen = _make_generator(table, mode, column_rules, index_rules, column_order)
    for idx, (variant, meta) in enumerate(gen):
        if max_iterations is not None and idx >= max_iterations:
            return
        meta.global_index = idx
        yield variant, meta


def total_variants(
    table: TableDDL,
    mode: Literal["types", "indexes", "sequential", "combined"],
    column_rules: List[ColumnRule],
    index_rules: List[IndexRule],
    column_order: Optional[Dict[str, int]] = None,
    max_iterations: Optional[int] = None,
) -> int:
    """Подсчитывает количество вариантов без их генерации."""
    col_total = total_column_variants(table, column_rules, column_order)
    idx_total = total_index_variants(table, index_rules, column_order)

    if mode == "types":
        n = col_total
    elif mode == "indexes":
        n = idx_total
    elif mode == "sequential":
        n = col_total + idx_total
    elif mode == "combined":
        n = col_total * idx_total
    else:
        raise ValueError(f"Неизвестный mode: {mode!r}")

    if max_iterations is not None:
        n = min(n, max_iterations)
    return n


# ─── внутренние генераторы по mode ───────────────────────────────────────────

def _make_generator(
    table: TableDDL,
    mode: str,
    column_rules: List[ColumnRule],
    index_rules: List[IndexRule],
    column_order: Optional[Dict[str, int]],
) -> Generator[Tuple[TableDDL, VariantMeta], None, None]:
    """Выбирает конкретный генератор вариантов согласно `mode`."""
    if mode == "types":
        yield from _gen_types(table, column_rules, column_order)
    elif mode == "indexes":
        yield from _gen_indexes(table, index_rules, column_order)
    elif mode == "sequential":
        yield from _gen_sequential(table, column_rules, index_rules, column_order)
    elif mode == "combined":
        yield from _gen_combined(table, column_rules, index_rules, column_order)
    else:
        raise ValueError(f"Неизвестный mode: {mode!r}")


def _gen_types(table, column_rules, column_order):
    """Режим `types`: меняем только типы/кодеки колонок."""
    for variant, col_meta in iter_column_variants(table, column_rules, column_order):
        yield variant, VariantMeta(
            global_index=0,
            mode="types",
            column_meta=col_meta,
        )


def _gen_indexes(table, index_rules, column_order):
    """Режим `indexes`: меняем только наборы skip-индексов."""
    for variant, idx_meta in iter_index_variants(
        table,
        index_rules,
        column_order=column_order,
    ):
        yield variant, VariantMeta(
            global_index=0,
            mode="indexes",
            index_meta=idx_meta,
        )


def _gen_sequential(table, column_rules, index_rules, column_order):
    """Режим `sequential`: сначала типовые, затем индексные варианты."""
    # Сначала все типовые варианты
    for variant, col_meta in iter_column_variants(table, column_rules, column_order):
        yield variant, VariantMeta(
            global_index=0,
            mode="sequential",
            column_meta=col_meta,
        )
    # Затем все индексные варианты (на основе исходной таблицы)
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


def _gen_combined(table, column_rules, index_rules, column_order):
    """
    Декартово произведение: для каждого типового варианта — все индексные.
    Материализуем индексные варианты в памяти (обычно их немного).
    """
    index_variants_list = list(
        iter_index_variants(table, index_rules, column_order=column_order)
    )

    for col_variant, col_meta in iter_column_variants(table, column_rules, column_order):
        for idx_variant_base, idx_meta_base in index_variants_list:
            # Берём типовой вариант и накладываем на него индексы
            combined = col_variant.copy()
            combined.indexes = [
                idx for idx in idx_variant_base.indexes
            ]
            # Пересоздаём index_meta с правильными IndexDef из combined
            from copy import deepcopy
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
