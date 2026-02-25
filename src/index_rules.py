"""
Правила матчинга и альтернативы для skip-индексов колонок.
Аналог column_rules.py, но вместо type/codec перебираем наборы индексов.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Iterator, List, Optional

from src.clickhouse_ddl import ColumnDef, IndexDef


# ─── один вариант индекса для колонки ────────────────────────────────────────

class IndexVariant(BaseModel):
    """
    Описывает один конкретный индекс который будет добавлен к колонке.
    index_type — строка как в DDL: 'bloom_filter(0.01)', 'ngrambf_v1(4, 65536, 2, 0)'
    """
    index_type: str
    granularity: int = 1
    table_index_granularity_values: Optional[List[int]] = None

    def to_index_def(self, col: ColumnDef, idx_num: int) -> IndexDef:
        """Создаёт IndexDef с автоматическим именем на основе колонки и типа."""
        # Берём базовое имя типа без параметров для имени индекса
        base_type = self.index_type.split("(")[0]
        name = f"idx_{col.name}_{base_type}_{idx_num}"
        return IndexDef(
            name=name,
            expr=col.name,
            index_type=self.index_type,
            granularity=str(self.granularity),
        )


# ─── альтернативы для одной колонки ──────────────────────────────────────────

class IndexAlternatives(BaseModel):
    """
    Список вариантов индексов для одной колонки.
    Каждый вариант — это один IndexVariant (один индекс на колонку).
    Перебираются последовательно, не перемножаются между собой.
    """
    variants: List[IndexVariant] = Field(default_factory=list)

    def iter_variants(self, col: ColumnDef) -> Iterator[Optional[IndexDef]]:
        """
        Генерирует варианты индексов для данной колонки.
        None = не добавлять индекс для этой колонки (попробовать без индекса).
        """
        for i, variant in enumerate(self.variants):
            yield variant.to_index_def(col, i)

    def total(self) -> int:
        """Количество явных индексных альтернатив для колонки."""
        return len(self.variants)


# ─── правило матчинга ─────────────────────────────────────────────────────────

class IndexRule(BaseModel):
    """
    Связывает матчер с набором вариантов индексов.
    Логика matches — AND, аналогично ColumnRule.
    by_name без by_type запрещён.
    """
    alternatives: IndexAlternatives
    by_type: Optional[str] = None
    by_name: Optional[str] = None

    def matches(self, col: ColumnDef) -> bool:
        """Проверяет, подходит ли правило к колонке по by_type/by_name."""
        name_ok = self.by_name is None or col.name == self.by_name
        type_ok = self.by_type is None or col.type == self.by_type
        return name_ok and type_ok
