"""
Генератор вариантов TableDDL с изменёнными skip-индексами.
Типы и кодеки колонок не трогаются.

Логика перебора:
  - Для каждой matched колонки есть список вариантов индексов.
  - Берём декартово произведение: для каждой колонки выбираем один индекс.
  - Все выбранные индексы добавляются к таблице (существующие индексы заменяются).
  - None = не добавлять индекс для этой колонки.
  - Полностью no-index комбинации (без единого индекса) по умолчанию исключаются.
"""

from __future__ import annotations

import itertools
from copy import deepcopy
from pydantic import BaseModel, Field
from typing import Dict, Generator, List, Optional, Tuple

from src.clickhouse_ddl import IndexDef, TableDDL
from src.index_rules import IndexAlternatives, IndexRule


# ─── метаданные варианта ──────────────────────────────────────────────────────

class IndexVariantMeta(BaseModel):
    """Метаданные одного index-варианта: индекс и выбранные индексы по колонкам."""

    index: int
    # {col_name: IndexDef | None}  None = индекс не добавлен для этой колонки
    index_choices: Dict[str, Optional[IndexDef]]
    table_index_granularity: Optional[int] = None


def _normalize_table_index_granularity_values(
    values: Optional[List[int]],
) -> List[int]:
    """
    Нормализует список перебора `SETTINGS index_granularity`.

    Возвращает дедуплицированный список `int > 0`.
    Если список не задан — возвращает пустой список (ограничений нет).
    """
    if values is None:
        return []
    deduplicated: list[int] = []
    seen: set[int] = set()
    for value in values:
        numeric = int(value)
        if numeric <= 0:
            raise ValueError("table index_granularity должен быть > 0")
        if numeric in seen:
            continue
        seen.add(numeric)
        deduplicated.append(numeric)
    return deduplicated


# ─── внутренний резолвинг ────────────────────────────────────────────────────

def _resolve_effective_table_index_granularity_values(
    global_values: List[int],
    selected_constraints: List[Optional[List[int]]],
) -> List[Optional[int]]:
    """
    Возвращает эффективный список `SETTINGS index_granularity` для выбранного combo.

    Правила:
      - если ограничений нет вообще -> `[None]` (DDL без изменения SETTINGS);
      - если задан global список -> база берётся из него;
      - если global не задан, но есть per-index списки -> база берётся из первого per-index;
      - итоговый список — пересечение всех ограничений с сохранением порядка базы.
    """
    explicit_constraints = [values for values in selected_constraints if values is not None]

    if not global_values and not explicit_constraints:
        return [None]

    ordered_base: List[int]
    if global_values:
        ordered_base = list(global_values)
    else:
        # explicit_constraints не пустой, иначе мы бы вернули [None] выше.
        ordered_base = list(explicit_constraints[0])

    allowed = set(ordered_base)
    for values in explicit_constraints:
        allowed &= set(values)

    resolved = [value for value in ordered_base if value in allowed]
    if not resolved:
        return []
    return resolved

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
    table_index_granularity_values: Optional[List[int]] = None,
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
    global_granularity_values = _normalize_table_index_granularity_values(
        table_index_granularity_values
    )

    if not resolved:
        # Нет matched-колонок => нет индексных вариантов.
        return

    col_names = [name for name, _ in resolved]
    # Для каждой колонки: (IndexDef|None, per-index table index_granularity values|None)
    # None добавляем в начало — вариант «без индекса для этой колонки».
    variant_lists: List[List[Tuple[Optional[IndexDef], Optional[List[int]]]]] = []
    for col_name, alt in resolved:
        col = table.column(col_name)
        col_variants: List[Tuple[Optional[IndexDef], Optional[List[int]]]] = [
            (None, None)
        ]
        for idx_num, index_variant in enumerate(alt.variants):
            col_variants.append(
                (
                    index_variant.to_index_def(col, idx_num),
                    (
                        list(index_variant.table_index_granularity_values)
                        if index_variant.table_index_granularity_values is not None
                        else None
                    ),
                )
            )
        variant_lists.append(col_variants)

    global_idx = 0
    for combo in itertools.product(*variant_lists):
        # Полностью no-index combo исключаем по умолчанию.
        if all(idx_def is None for idx_def, _ in combo):
            continue

        base_variant = table.copy()

        # Убираем все старые индексы для matched-колонок, оставляем остальные
        matched_exprs = set(col_names)
        kept_indexes = [
            idx for idx in base_variant.indexes
            if idx.expr not in matched_exprs
        ]

        choices: Dict[str, Optional[IndexDef]] = {}
        new_indexes = list(kept_indexes)
        selected_granularity_constraints: List[Optional[List[int]]] = []

        for col_name, (idx_def, per_index_granularity_values) in zip(col_names, combo):
            choices[col_name] = deepcopy(idx_def) if idx_def else None
            if idx_def is not None:
                new_indexes.append(deepcopy(idx_def))
                selected_granularity_constraints.append(
                    deepcopy(per_index_granularity_values)
                )

        base_variant.indexes = new_indexes

        effective_granularity_values = _resolve_effective_table_index_granularity_values(
            global_values=global_granularity_values,
            selected_constraints=selected_granularity_constraints,
        )
        if not effective_granularity_values:
            continue

        for table_index_granularity in effective_granularity_values:
            variant = base_variant.copy()
            if table_index_granularity is not None:
                variant.set_index_granularity(table_index_granularity)
            yield variant, IndexVariantMeta(
                index=global_idx,
                index_choices=deepcopy(choices),
                table_index_granularity=table_index_granularity,
            )
            global_idx += 1


def total_index_variants(
    table: TableDDL,
    rules: List[IndexRule],
    column_order: Optional[Dict[str, int]] = None,
    table_index_granularity_values: Optional[List[int]] = None,
) -> int:
    """Количество вариантов (полностью no-index комбинации исключены)."""
    resolved = _resolve_index_columns(table, rules, column_order=column_order)
    global_granularity_values = _normalize_table_index_granularity_values(
        table_index_granularity_values
    )
    if not resolved:
        return 0

    has_per_index_constraints = any(
        variant.table_index_granularity_values is not None
        for _, alt in resolved
        for variant in alt.variants
    )
    if not has_per_index_constraints:
        n = 1
        for _, alt in resolved:
            n *= (alt.total() + 1)  # +1 за вариант None
        # Исключаем комбинацию, где для всех колонок выбран None.
        n -= 1
        if n <= 0:
            return 0
        granularity_multiplier = len(global_granularity_values) if global_granularity_values else 1
        return n * granularity_multiplier

    variant_choice_lists: List[List[Tuple[bool, Optional[List[int]]]]] = []
    for _, alt in resolved:
        choices: List[Tuple[bool, Optional[List[int]]]] = [(False, None)]
        for variant in alt.variants:
            choices.append(
                (
                    True,
                    (
                        list(variant.table_index_granularity_values)
                        if variant.table_index_granularity_values is not None
                        else None
                    ),
                )
            )
        variant_choice_lists.append(choices)

    total = 0
    for combo_choices in itertools.product(*variant_choice_lists):
        if not any(is_index for is_index, _ in combo_choices):
            continue
        effective_granularity_values = _resolve_effective_table_index_granularity_values(
            global_values=global_granularity_values,
            selected_constraints=[constraints for _, constraints in combo_choices],
        )
        total += len(effective_granularity_values)
    return total
