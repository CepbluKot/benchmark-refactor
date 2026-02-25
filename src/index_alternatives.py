"""
Автогенерация skip-индексов по типу колонки.

Используется для `index_rules[].auto_generate_indexes=true`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class IndexAutoAlternative:
    """Одна автосгенерированная альтернатива индекса."""

    index_type: str
    granularity: int


def _unwrap_nullable_and_low_cardinality(datatype: str) -> tuple[str, bool]:
    """
    Разворачивает Nullable/LowCardinality обёртки.

    Возвращает:
      - базовый тип без обёрток;
      - флаг, была ли обёртка LowCardinality.
    """
    current = str(datatype or "").strip()
    is_low_cardinality = False

    while current:
        lowered = current.lower()
        if lowered.startswith("nullable(") and current.endswith(")"):
            current = current[len("nullable(") : -1].strip()
            continue
        if lowered.startswith("lowcardinality(") and current.endswith(")"):
            is_low_cardinality = True
            current = current[len("lowcardinality(") : -1].strip()
            continue
        break
    return current, is_low_cardinality


def _is_int_like(normalized_base_type: str) -> bool:
    """Проверяет, что тип относится к integer-like."""
    return (
        normalized_base_type.startswith("int")
        or normalized_base_type.startswith("uint")
        or normalized_base_type.startswith("enum")
        or normalized_base_type == "bool"
    )


def generate_possible_indexes_by_type(datatype: str) -> List[IndexAutoAlternative]:
    """
    Генерирует разумный набор skip-индексов по типу колонки.

    Логика приближена к существующим baseline rule-bank шаблонам.
    """
    base_type, _is_low_cardinality = _unwrap_nullable_and_low_cardinality(datatype)
    normalized = base_type.replace(" ", "").lower()

    if not normalized:
        return []

    # Для диапазонных типов всегда включаем minmax:
    # Int8/16/32/64, Float32/64, Decimal*, Date/DateTime*.
    if _is_int_like(normalized):
        return [IndexAutoAlternative(index_type="minmax", granularity=4)]

    if normalized.startswith("float") or normalized.startswith("decimal"):
        return [IndexAutoAlternative(index_type="minmax", granularity=4)]

    if normalized.startswith("date") or normalized.startswith("datetime"):
        return [IndexAutoAlternative(index_type="minmax", granularity=4)]

    if normalized == "string":
        return [
            IndexAutoAlternative(index_type="ngrambf_v1(3, 256, 2, 0)", granularity=1),
        ]

    if normalized.startswith("fixedstring("):
        return []

    if normalized in {"uuid", "ipv4", "ipv6"}:
        return []

    return []
