"""
Legacy-совместимая генерация альтернатив type+codec для column rules.

Сохраняет знакомые функции:
  - generate_possible_compressions_w_preprocessings
  - generate_possible_new_datatypes
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from typing import List, Sequence, Set, Tuple


MAX_COMPRESSION_PERMUTATIONS = 1


@dataclass(frozen=True)
class Compression:
    """Описание компрессии и диапазона уровней (если есть)."""

    name: str
    min_lvl: int = -1
    max_lvl: int = -1


@dataclass(frozen=True)
class DataTypeCodecAlternative:
    """Одна альтернатива: тип + codec-expression без обёртки CODEC(...)."""

    datatype: str
    codec: str


ALL_POSSIBLE_COMPRESSIONS: Tuple[Compression, ...] = (
    Compression("ZSTD", 1, 5),
    Compression("LZ4"),
)

ALL_POSSIBLE_PREPROCESSINGS: Set[str] = {
    "Delta",
    "T64",
    "DoubleDelta",
    "GCD",
    "FPC",
}


def generate_possible_compressions() -> List[str]:
    """Генерирует список codec-частей без CODEC(...): `ZSTD(1)`, `LZ4`, ..."""
    possible_compressions: list[str] = []
    for compression in ALL_POSSIBLE_COMPRESSIONS:
        if compression.min_lvl == -1:
            possible_compressions.append(compression.name)
            continue
        for compression_lvl in range(compression.min_lvl, compression.max_lvl + 1):
            possible_compressions.append(f"{compression.name}({compression_lvl})")
    return possible_compressions


def generate_permutations(arr: Sequence[str], max_len: int = 2) -> List[Tuple[str, ...]]:
    """Генерирует все перестановки длиной 1..max_len."""
    res: list[Tuple[str, ...]] = []
    n = len(arr)
    if n == 0:
        return res
    for permutation_len in range(1, min(max_len, n) + 1):
        for permutation in permutations(arr, permutation_len):
            res.append(permutation)
    return res


def _normalize_datatype_for_preprocessing(datatype: str) -> str:
    """Нормализует datatype для выбора preprocessings."""
    return str(datatype or "").strip().lower()


def generate_possible_compressions_w_preprocessings(datatype: str) -> List[str]:
    """
    Генерирует codec-выражения без CODEC(...), включая preprocessings.

    Примеры результата:
      - `ZSTD(1)`
      - `Delta, ZSTD(1)`
      - `DoubleDelta, LZ4`
    """
    possible_compressions_w_preprocessings: list[str] = []
    possible_compressions = generate_possible_compressions()
    all_possible_preprocessings = set(ALL_POSSIBLE_PREPROCESSINGS)

    datatype_normalized = _normalize_datatype_for_preprocessing(datatype)
    if "string" in datatype_normalized:
        all_possible_preprocessings = set()
    elif "datetime" in datatype_normalized:
        all_possible_preprocessings = all_possible_preprocessings.difference({"FPC"})
    elif "int" in datatype_normalized:
        all_possible_preprocessings = all_possible_preprocessings.difference({"FPC"})

    preprocessings_permutations = generate_permutations(
        sorted(all_possible_preprocessings),
        MAX_COMPRESSION_PERMUTATIONS,
    )

    for compression in possible_compressions:
        possible_compressions_w_preprocessings.append(compression)
        for permutation in preprocessings_permutations:
            possible_compressions_w_preprocessings.append(
                ", ".join(permutation) + f", {compression}"
            )
    return possible_compressions_w_preprocessings


def generate_possible_new_datatypes(
    new_possible_datatypes: Sequence[str],
    possible_compressions_w_preprocessings: Sequence[str],
) -> List[DataTypeCodecAlternative]:
    """Строит декартово произведение datatype × codec-expression."""
    result: list[DataTypeCodecAlternative] = []
    for new_datatype in new_possible_datatypes:
        normalized_datatype = str(new_datatype).strip()
        if not normalized_datatype:
            continue
        for compression in possible_compressions_w_preprocessings:
            normalized_codec = str(compression).strip()
            if not normalized_codec:
                continue
            result.append(
                DataTypeCodecAlternative(
                    datatype=normalized_datatype,
                    codec=normalized_codec,
                )
            )
    return result
