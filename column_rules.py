"""
Правила матчинга и альтернативы для типов/кодеков колонок.
Принимает на вход Config-датаклассы, отдаёт объекты для variants/.
"""

from __future__ import annotations

import itertools
from pydantic import BaseModel, Field
from typing import Iterator, List, Optional, Tuple

from clickhouse_ddl import ColumnDef


# ─── альтернативы для одной колонки ──────────────────────────────────────────

class ColumnAlternatives(BaseModel):
    """
    Список альтернативных типов и кодеков для одной колонки.
    Пустой список = оставить исходное значение.
    None внутри codecs = убрать кодек совсем.
    """
    types: List[Optional[str]] = Field(default_factory=list)
    codecs: List[Optional[str]] = Field(default_factory=list)

    def iter_combos(
        self, original: ColumnDef
    ) -> Iterator[Tuple[Optional[str], Optional[str]]]:
        """Декартово произведение types × codecs."""
        type_options = self.types if self.types else [original.type]
        codec_options = self.codecs if self.codecs else [original.codec]
        yield from itertools.product(type_options, codec_options)

    def total(self, original: ColumnDef) -> int:
        """Количество комбинаций для колонки с учётом fallback на исходные значения."""
        return max(len(self.types), 1) * max(len(self.codecs), 1)


# ─── правило матчинга ─────────────────────────────────────────────────────────

class ColumnRule(BaseModel):
    """
    Связывает матчер (by_name AND/OR by_type) с набором альтернатив.

    Логика matches — AND:
      - Каждый заданный матчер должен совпасть.
      - Незаданный матчер (None) считается совпавшим автоматически.
      - by_name без by_type запрещён (гарантируется в config/loader.py).

    by_type поддерживает префиксный матч параметрических типов:
      'Nullable'       → Nullable(String), Nullable(UInt32), ...
      'LowCardinality' → LowCardinality(String), ...
    """
    alternatives: ColumnAlternatives
    by_type: Optional[str] = None
    by_name: Optional[str] = None

    def matches(self, col: ColumnDef) -> bool:
        """Проверяет, подходит ли правило к конкретной колонке таблицы."""
        name_ok = self.by_name is None or col.name == self.by_name
        type_ok = (
            self.by_type is None
            or col.type == self.by_type
            or col.type.startswith(self.by_type + "(")
        )
        return name_ok and type_ok
