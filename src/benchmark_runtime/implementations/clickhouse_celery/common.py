"""Общие утилиты ClickHouse/Celery реализаций."""

from __future__ import annotations

import json
import math
from typing import Any, Iterable, List, Sequence

try:
    import numpy as np
except ImportError:  # pragma: no cover - fallback нужен только без установленного numpy.
    np = None

DEFAULT_MEASURED_PERCENTILES: list[int] = [1, 50, 90, 95, 99, 100]


def make_readable_bytes(value: float | int | None) -> str:
    """Возвращает человекочитаемый размер (`B`, `KB`, `MB`, ...)."""
    if value is None:
        return "0 B"
    size = float(value)
    if size <= 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    unit_idx = 0
    while size >= 1024 and unit_idx < len(units) - 1:
        size /= 1024.0
        unit_idx += 1
    if unit_idx == 0:
        return f"{int(size)} {units[unit_idx]}"
    return f"{size:.2f} {units[unit_idx]}"


def compute_percentiles(values: Iterable[float | int], measured_percentiles: Sequence[int]) -> List[float]:
    """Считает percentiles через numpy (`method='linear'`)."""
    numeric_values = list(float(v) for v in values)
    if not numeric_values:
        return []

    requested_percentiles = list(measured_percentiles)
    if not requested_percentiles:
        return []

    # Исторически percentiles в runtime клампились в [0, 100], сохраняем это поведение.
    clipped = [max(0.0, min(100.0, float(p))) for p in requested_percentiles]

    if np is not None:
        arr = np.asarray(numeric_values, dtype=np.float64)
        q = np.asarray(clipped, dtype=np.float64)
        return np.percentile(arr, q, method="linear").tolist()

    sorted_values = sorted(numeric_values)
    result: List[float] = []
    for percentile in clipped:
        if len(sorted_values) == 1:
            result.append(float(sorted_values[0]))
            continue
        rank = (percentile / 100.0) * (len(sorted_values) - 1)
        lo = int(math.floor(rank))
        hi = int(math.ceil(rank))
        lo_val = float(sorted_values[lo])
        hi_val = float(sorted_values[hi])
        if lo == hi:
            result.append(lo_val)
            continue
        result.append(lo_val + (hi_val - lo_val) * (rank - lo))
    return result


def compute_speedup_coefficients(
    source_percentiles: Sequence[float],
    tested_percentiles: Sequence[float],
) -> List[float]:
    """Возвращает поэлементные коэффициенты ускорения `source/tested`."""
    if len(source_percentiles) != len(tested_percentiles):
        return []

    result: list[float] = []
    for source_value, tested_value in zip(source_percentiles, tested_percentiles):
        if tested_value and tested_value > 0:
            result.append(float(source_value) / float(tested_value))
        else:
            result.append(0.0)
    return result


def json_dumps(value: Any) -> str:
    """Стабильная сериализация JSON для хранения в ClickHouse String."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
