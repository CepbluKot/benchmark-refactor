"""
Именование variant-таблиц в бенчмарке.

Схема:  {original_table}__bench__{benchmark_id}__{variant_index:04d}

Двойной разделитель __ гарантирует однозначный парсинг,
т.к. benchmark_id и имя таблицы не содержат __ (заменяются на _).

Примеры:
  events__bench__prod_full__0000
  user_events__bench__mytest__0042

Ограничения:
  - Символы кроме [a-zA-Z0-9_] заменяются на '_'.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

_SEP = "__bench__"
_IDX_SEP = "__"
_UNSAFE = re.compile(r"[^a-zA-Z0-9_]")
_MULTI_UNDERSCORE = re.compile(r"_{2,}")


def _sanitize(s: str) -> str:
    """Заменяет небезопасные символы на _, схлопывает множественные _ в одиночные."""
    s = _UNSAFE.sub("_", s)
    s = _MULTI_UNDERSCORE.sub("_", s)
    return s.strip("_")


def variant_table_name(
    original_table: str,
    benchmark_id: str,
    variant_index: int,
) -> str:
    """
    Генерирует имя variant-таблицы.

    >>> variant_table_name("user_events", "prod_full", 42)
    'user_events__bench__prod_full__0042'
    """
    table = _sanitize(original_table)
    bench = _sanitize(benchmark_id)
    suffix = f"{_SEP}{bench}{_IDX_SEP}{variant_index:04d}"
    return table + suffix


def parse_variant_name(name: str) -> Optional[Tuple[str, str, int]]:
    """
    Разбирает variant-имя обратно.
    Возвращает (original_table, benchmark_id, variant_index) или None.

    >>> parse_variant_name("user_events__bench__prod_full__0042")
    ('user_events', 'prod_full', 42)
    """
    m = re.match(r"^(.+)__bench__(.+)__(\d{4})$", name)
    if not m:
        return None
    return m.group(1), m.group(2), int(m.group(3))


def is_variant_table(name: str) -> bool:
    """True если имя похоже на variant-таблицу бенчмарка."""
    return "__bench__" in name and bool(re.search(r"__\d{4}$", name))
