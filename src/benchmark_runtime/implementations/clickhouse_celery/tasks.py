"""Celery worker-side задачи для ClickHouse benchmark execution."""

from __future__ import annotations

import functools
import json
import logging
import math
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.clickhouse_ddl import TableDDL
from src.models import ScoringConfig
from src.naming import is_variant_table

from ...types import (
    BenchmarkVariantResult,
    SourceBenchmarkResult,
)
from .common import (
    DEFAULT_MEASURED_PERCENTILES,
    compute_percentiles,
    compute_speedup_coefficients,
    json_dumps,
    make_readable_bytes,
)
from .result_store import ClickHouseBenchmarkResultStore, ClickHouseConnectionParams
from .scoring import ScoreEvaluationError, build_percentile_lookup, evaluate_score_expression
from .settings import get_clickhouse_celery_worker_settings

logger = logging.getLogger(__name__)

SOURCE_BENCHMARK_TASK_NAME = "bench.source_benchmark"
VARIANT_BENCHMARK_TASK_NAME = "bench.variant_benchmark"

_DANGEROUS_INPUT_KEYWORDS = (
    "drop",
    "alter",
    "delete",
    "truncate",
    "insert",
    "update",
    "grant",
    "revoke",
)
_READ_ONLY_SQL_PREFIXES = ("select", "with", "show", "describe", "desc", "explain")
_BASELINE_TABLE_MARKER = "__source_baseline__"
_COLD_SELECT_SETTINGS_ASSIGNMENTS = (
    "use_uncompressed_cache = 0",
)
_PHASED_STRATEGIES = ("sequential_phased_topn_strategy",)


def _is_phased_strategy(strategy: str) -> bool:
    """Проверяет, что benchmark strategy относится к phased-линейке."""
    return str(strategy or "").strip() in _PHASED_STRATEGIES


def _resolve_worker_start_benchmark_run_id() -> str:
    """Возвращает benchmark_run_id для стартового лога worker-процесса."""
    from_env = (os.getenv("BENCH_BENCHMARK_RUN_ID") or "").strip()
    if from_env:
        return from_env
    return "unknown (из payload задач)"


def _log_worker_build_metadata() -> None:
    """Пишет в лог build metadata на старте Celery worker."""
    build_date = (os.getenv("BENCH_BUILD_DATETIME") or "").strip()
    if not build_date:
        build_date = f"{datetime.utcnow().isoformat()}Z"
    git_commit = (os.getenv("BENCH_GIT_COMMIT") or "unknown").strip() or "unknown"
    git_branch = (os.getenv("BENCH_GIT_BRANCH") or "unknown").strip() or "unknown"

    logger.info("=== Build metadata ===")
    logger.info("Build date: %s", build_date)
    logger.info("Git commit: %s", git_commit)
    logger.info("Git branch: %s", git_branch)
    logger.info("Benchmark run id: %s", _resolve_worker_start_benchmark_run_id())
    logger.info("======================")


def _strip_leading_sql_comments(query: str) -> str:
    """Удаляет ведущие block comments и пробелы."""
    stripped = query.lstrip()
    while stripped.startswith("/*"):
        end_pos = stripped.find("*/")
        if end_pos == -1:
            break
        stripped = stripped[end_pos + 2 :].lstrip()
    return stripped


def _is_identifier_char(ch: str) -> bool:
    """Проверяет, что символ может быть частью SQL-идентификатора."""
    return ch.isalnum() or ch == "_"


def _skip_sql_line_comment(text: str, i: int) -> int:
    """Сдвигает позицию в конец SQL line-comment `-- ...`."""
    i += 2
    while i < len(text) and text[i] != "\n":
        i += 1
    return i


def _skip_sql_block_comment(text: str, i: int) -> int:
    """Сдвигает позицию после SQL block-comment `/* ... */`."""
    i += 2
    while i + 1 < len(text):
        if text[i] == "*" and text[i + 1] == "/":
            return i + 2
        i += 1
    return len(text)


def _find_top_level_keyword_pos(sql: str, keyword: str, *, start: int = 0) -> int:
    """
    Возвращает позицию keyword на верхнем уровне SQL (вне строк/скобок/комментариев).

    Если keyword не найден, возвращает `-1`.
    """
    if not keyword:
        return -1
    needle = keyword.upper()
    nlen = len(needle)
    depth = 0
    quote: Optional[str] = None
    i = max(0, int(start))
    while i < len(sql):
        ch = sql[i]
        if quote is not None:
            if ch == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote:
                    i += 2
                    continue
                if i > 0 and sql[i - 1] == "\\":
                    i += 1
                    continue
                quote = None
            i += 1
            continue

        if ch in ("'", '"', "`"):
            quote = ch
            i += 1
            continue

        if ch == "-" and i + 1 < len(sql) and sql[i + 1] == "-":
            i = _skip_sql_line_comment(sql, i)
            continue
        if ch == "/" and i + 1 < len(sql) and sql[i + 1] == "*":
            i = _skip_sql_block_comment(sql, i)
            continue

        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")" and depth > 0:
            depth -= 1
            i += 1
            continue

        if depth == 0 and sql[i : i + nlen].upper() == needle:
            prev_ok = i == 0 or not _is_identifier_char(sql[i - 1])
            next_pos = i + nlen
            next_ok = next_pos >= len(sql) or not _is_identifier_char(sql[next_pos])
            if prev_ok and next_ok:
                return i

        i += 1
    return -1


def _split_top_level_commas_sql(text: str) -> List[str]:
    """Разбивает SQL-фрагмент по top-level запятым (вне строк/скобок/комментариев)."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    quote: Optional[str] = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    buf.append(text[i + 1])
                    i += 2
                    continue
                if i > 0 and text[i - 1] == "\\":
                    i += 1
                    continue
                quote = None
            i += 1
            continue

        if ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
            i += 1
            continue

        if ch == "-" and i + 1 < len(text) and text[i + 1] == "-":
            i = _skip_sql_line_comment(text, i)
            continue
        if ch == "/" and i + 1 < len(text) and text[i + 1] == "*":
            i = _skip_sql_block_comment(text, i)
            continue

        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1

        if ch == "," and depth == 0:
            chunk = "".join(buf).strip()
            if chunk:
                parts.append(chunk)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    chunk = "".join(buf).strip()
    if chunk:
        parts.append(chunk)
    return parts


def _find_top_level_trailing_comment_span(sql: str) -> Optional[tuple[int, int]]:
    """
    Ищет trailing top-level комментарий в конце SQL (`-- ...` или `/* ... */`).

    Возвращает `(start, end)` если комментарий находится в хвосте запроса
    (после него только пробелы), иначе `None`.
    """
    depth = 0
    quote: Optional[str] = None
    comment_spans: list[tuple[int, int]] = []
    i = 0
    while i < len(sql):
        ch = sql[i]
        if quote is not None:
            if ch == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote:
                    i += 2
                    continue
                if i > 0 and sql[i - 1] == "\\":
                    i += 1
                    continue
                quote = None
            i += 1
            continue

        if ch in ("'", '"', "`"):
            quote = ch
            i += 1
            continue

        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")" and depth > 0:
            depth -= 1
            i += 1
            continue

        if depth == 0 and ch == "-" and i + 1 < len(sql) and sql[i + 1] == "-":
            start = i
            end = _skip_sql_line_comment(sql, i)
            comment_spans.append((start, end))
            i = end
            continue
        if depth == 0 and ch == "/" and i + 1 < len(sql) and sql[i + 1] == "*":
            start = i
            end = _skip_sql_block_comment(sql, i)
            comment_spans.append((start, end))
            i = end
            continue

        i += 1

    for start, end in reversed(comment_spans):
        if sql[end:].strip():
            continue
        if sql[:start].strip():
            return (start, end)
    return None


def _with_cold_select_settings(
    query: str,
    *,
    settings_assignments: Optional[Sequence[str]] = None,
) -> str:
    """
    Возвращает SELECT query c отключёнными cache-настройками через `SETTINGS`.

    Формирует/обновляет ключ `use_uncompressed_cache = 0`.
    """
    normalized = query.rstrip()
    while normalized.endswith(";"):
        normalized = normalized[:-1].rstrip()

    if not normalized:
        return normalized

    trailing_comment = ""
    trailing_comment_span = _find_top_level_trailing_comment_span(normalized)
    if trailing_comment_span is not None:
        start, _ = trailing_comment_span
        trailing_comment = normalized[start:].strip()
        normalized = normalized[:start].rstrip()

    if not normalized:
        return trailing_comment

    if settings_assignments is None:
        required_settings = list(_COLD_SELECT_SETTINGS_ASSIGNMENTS)
    else:
        required_settings = [str(item).strip() for item in settings_assignments if str(item).strip()]
        if not required_settings:
            required_settings = list(_COLD_SELECT_SETTINGS_ASSIGNMENTS)

    settings_pos = _find_top_level_keyword_pos(normalized, "SETTINGS")
    format_pos = _find_top_level_keyword_pos(normalized, "FORMAT")
    rewritten = ""
    if settings_pos < 0:
        if format_pos >= 0:
            before = normalized[:format_pos].rstrip()
            after = normalized[format_pos:].lstrip()
            rewritten = f"{before} SETTINGS {', '.join(required_settings)} {after}"
        else:
            rewritten = f"{normalized} SETTINGS {', '.join(required_settings)}"
        if trailing_comment:
            return f"{rewritten} {trailing_comment}"
        return rewritten

    settings_body_start = settings_pos + len("SETTINGS")
    settings_body_end = format_pos if format_pos >= 0 and format_pos > settings_pos else len(normalized)
    settings_body = normalized[settings_body_start:settings_body_end]
    raw_assignments = _split_top_level_commas_sql(settings_body)

    filtered_assignments: list[str] = []
    for assignment in raw_assignments:
        matcher = re.match(r"^\s*`?([A-Za-z_][A-Za-z0-9_]*)`?\s*=", assignment)
        if matcher is not None:
            key = matcher.group(1).lower()
            if key in {"use_uncompressed_cache", "use_index_marks_cache", "use_index_mark_cache"}:
                continue
        filtered_assignments.append(assignment.strip())

    filtered_assignments.extend(required_settings)
    rebuilt_settings = ", ".join(item for item in filtered_assignments if item)

    before_settings = normalized[:settings_body_start].rstrip()
    if settings_body_end < len(normalized):
        after_settings = normalized[settings_body_end:].lstrip()
        rewritten = f"{before_settings} {rebuilt_settings} {after_settings}"
    else:
        rewritten = f"{before_settings} {rebuilt_settings}"

    if trailing_comment:
        return f"{rewritten} {trailing_comment}"
    return rewritten


def is_safe_input_parameter(param: str) -> bool:
    """
    Проверяет строковый параметр на опасные SQL-ключевые слова.

    Сделано по аналогии с legacy `check_input_params_decorator`.
    """
    if not isinstance(param, str):
        return False
    stripped = param.strip()
    if not stripped:
        return False
    pattern = r"\b(" + "|".join(_DANGEROUS_INPUT_KEYWORDS) + r")\b"
    return re.search(pattern, stripped.lower()) is None


def are_all_input_params_safe(params: Sequence[str]) -> bool:
    """Проверяет список строковых параметров на безопасность."""
    return all(is_safe_input_parameter(param) for param in params)


def _assert_read_only_query(query: str, *, context: str) -> None:
    """Запрещает любые не read-only SQL-запросы в пользовательском query-plan."""
    normalized = _strip_leading_sql_comments(query).lower()
    if not normalized.startswith(_READ_ONLY_SQL_PREFIXES):
        raise ValueError(
            f"{context}: разрешены только read-only SQL-запросы "
            f"({', '.join(_READ_ONLY_SQL_PREFIXES)})."
        )


def check_input_params_decorator(func):
    """
    Legacy-совместимый декоратор проверки строковых входных параметров.

    Блокирует выполнение, если среди строковых аргументов обнаружены опасные ключевые слова.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        str_args = [arg for arg in args if isinstance(arg, str)]
        str_args.extend(value for value in kwargs.values() if isinstance(value, str))
        if not are_all_input_params_safe(str_args):
            raise ValueError(
                f"Обнаружены потенциально опасные input-параметры в {func.__name__}: "
                f"args={args}, kwargs={kwargs}"
            )
        return func(*args, **kwargs)

    return wrapper


@check_input_params_decorator
def _validate_user_read_only_sql_input(query: str) -> None:
    """Проверяет один пользовательский SQL на безопасность и read-only характер."""
    _assert_read_only_query(query, context="user_query")


def _error_query_metrics() -> Dict[str, float]:
    """Стандартный набор метрик для случая ошибки."""
    return {
        "elapsed_ns": -1.0,
        "read_rows": -1.0,
        "read_bytes": -1.0,
        "written_rows": -1.0,
        "written_bytes": -1.0,
    }


def _sum_column_compressed_size_bytes(column_sizes: Any) -> float:
    """Суммирует `size_compressed_bytes` по словарю колонок."""
    if not isinstance(column_sizes, dict):
        return 0.0
    total = 0.0
    for stats in column_sizes.values():
        if not isinstance(stats, dict):
            continue
        try:
            value = float(stats.get("size_compressed_bytes", 0.0) or 0.0)
        except Exception:
            continue
        if value > 0 and math.isfinite(value):
            total += value
    return total


def _normalize_total_size_bytes(
    total_size_bytes: float,
    *,
    column_sizes: Dict[str, Dict[str, Any]],
    context: str,
) -> float:
    """
    Нормализует общий размер таблицы, защищая от недооценки в system.parts.

    В некоторых версиях/моментах `system.parts.data_compressed_bytes` может
    отставать и быть заметно меньше, чем сумма `size_compressed_bytes` по
    колонкам. В этом случае берём сумму по колонкам как более консервативное
    (и практично более стабильное) значение.
    """
    total = float(total_size_bytes or 0.0)
    by_columns = _sum_column_compressed_size_bytes(column_sizes)

    if total <= 0 and by_columns > 0:
        return by_columns

    if by_columns > total > 0:
        logger.warning(
            "%s: общий compressed size из system.parts (%.0f B) меньше суммы по колонкам "
            "(%.0f B). Используем сумму по колонкам.",
            context,
            total,
            by_columns,
        )
        return by_columns

    return total


def _to_positive_finite_float(value: Any) -> float:
    """Безопасно приводит значение к float и отбрасывает некорректные значения."""
    try:
        normalized = float(value or 0.0)
    except Exception:
        return 0.0
    if not math.isfinite(normalized) or normalized <= 0:
        return 0.0
    return normalized


def _resolve_total_size_with_indexes_bytes(
    *,
    parts_metrics: Dict[str, float],
    normalized_data_size_bytes: float,
) -> float:
    """
    Возвращает полный размер таблицы с индексами.

    Используем `sum(bytes_on_disk)` из `system.parts` как primary-источник total_on_disk.
    Если `bytes_on_disk` временно занижен/нулевой, не даём итогу опуститься ниже
    нормализованного `data_compressed_bytes`.
    """
    data_size = _to_positive_finite_float(normalized_data_size_bytes)
    total_on_disk = _to_positive_finite_float(parts_metrics.get("bytes_on_disk"))
    return max(total_on_disk, data_size)


def _wait_for_table_size_materialization_if_needed(
    client: "_ClickHouseRuntimeClient",
    *,
    database: str,
    table: str,
    column_sizes: Dict[str, Dict[str, Any]],
    index_sizes: Dict[str, Dict[str, Any]],
    total_size_bytes: float,
    timeout_sec: float = 5.0,
    poll_sec: float = 0.5,
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], float]:
    """
    Короткий poll размеров таблицы, если первичный снимок дал нули.

    Нужно для случаев, когда сразу после INSERT системные таблицы ещё не успели
    отдать финальные размеры (в т.ч. на некоторых схемах LowCardinality).
    """
    effective_total_size = float(total_size_bytes or 0.0)
    effective_column_sizes = dict(column_sizes or {})
    effective_index_sizes = dict(index_sizes or {})

    if effective_total_size > 0 or _sum_column_compressed_size_bytes(effective_column_sizes) > 0:
        return effective_column_sizes, effective_index_sizes, effective_total_size

    deadline = time.monotonic() + max(0.0, float(timeout_sec))
    while time.monotonic() < deadline:
        sleep_time = max(0.0, float(poll_sec))
        if sleep_time > 0:
            time.sleep(sleep_time)

        effective_column_sizes = client.get_column_sizes(database, table)
        effective_index_sizes = client.get_index_sizes(database, table)
        effective_total_size = float(
            client.get_total_compressed_size_bytes(database, table) or 0.0
        )
        if (
            effective_total_size > 0
            or _sum_column_compressed_size_bytes(effective_column_sizes) > 0
        ):
            break

    return effective_column_sizes, effective_index_sizes, effective_total_size


def _to_metric_or_error(value: Any) -> float:
    """Безопасно приводит значение метрики к float, иначе возвращает `-1`."""
    if value is None:
        return -1.0
    try:
        return float(value)
    except Exception:
        return -1.0


def _is_benchmark_temp_table_name(table: str) -> bool:
    """Проверяет, что имя относится к временным benchmark-таблицам."""
    normalized = str(table).strip()
    if not normalized:
        return False
    if _BASELINE_TABLE_MARKER in normalized:
        return True
    return is_variant_table(normalized)


def _is_error_query_metrics(metrics: Dict[str, float]) -> bool:
    """Определяет, что метрики помечены как ошибочные."""
    return float(metrics.get("elapsed_ns", -1.0)) < 0


def _filter_positive_finite_measurements(
    values: Sequence[float],
    *,
    metric_name: str,
    context: str,
) -> List[float]:
    """
    Оставляет только валидные замеры (> 0 и конечные).

    Это защищает percentiles от загрязнения нулями/ошибочными значениями.
    """
    cleaned: list[float] = []
    dropped = 0
    for value in values:
        try:
            numeric = float(value)
        except Exception:
            dropped += 1
            continue
        if math.isfinite(numeric) and numeric > 0:
            cleaned.append(numeric)
        else:
            dropped += 1

    if dropped > 0:
        logger.warning(
            "%s: отброшено %d невалидных замеров `%s` (<= 0/NaN/Inf)",
            context,
            dropped,
            metric_name,
        )
    return cleaned


def _to_pretty_score_calculation_json(value: Dict[str, Any]) -> str:
    """Сериализует детали расчёта score в человекочитаемый JSON."""
    def _normalize_jsonable(payload: Any) -> Any:
        if isinstance(payload, dict):
            return {
                str(key): _normalize_jsonable(inner_value)
                for key, inner_value in payload.items()
            }
        if isinstance(payload, list):
            return [_normalize_jsonable(item) for item in payload]
        if isinstance(payload, tuple):
            return [_normalize_jsonable(item) for item in payload]
        return payload

    return json.dumps(
        _normalize_jsonable(value),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=str,
    )


def _build_metric_bucket(
    *,
    measured_percentiles: Sequence[int],
    time_ms_percentiles: Sequence[float],
    rows_per_second_percentiles: Sequence[float],
    bytes_per_second_percentiles: Sequence[float],
) -> Dict[str, Any]:
    """Строит унифицированный контейнер метрик + lookup по перцентилям."""
    return {
        "time_ms_percentiles": list(time_ms_percentiles),
        "time_ms_by_percentile": build_percentile_lookup(
            measured_percentiles,
            time_ms_percentiles,
        ),
        "rows_per_second_percentiles": list(rows_per_second_percentiles),
        "rows_per_second_by_percentile": build_percentile_lookup(
            measured_percentiles,
            rows_per_second_percentiles,
        ),
        "bytes_per_second_percentiles": list(bytes_per_second_percentiles),
        "bytes_per_second_by_percentile": build_percentile_lookup(
            measured_percentiles,
            bytes_per_second_percentiles,
        ),
    }


def _compute_builtin_source_score(
    *,
    select_time_ms_percentiles: Sequence[float],
) -> tuple[Optional[float], Dict[str, Any]]:
    """Встроенный baseline score: `1 / p_last(select_latency_ms)`."""
    selected_latency_ms: Optional[float] = None
    score: Optional[float] = None
    if select_time_ms_percentiles and select_time_ms_percentiles[-1] > 0:
        selected_latency_ms = float(select_time_ms_percentiles[-1])
        score = 1.0 / selected_latency_ms

    details: Dict[str, Any] = {
        "formula": "1 / tested_select_time_ms_percentiles[-1]",
        "inputs": {
            "tested_select_time_ms_percentiles": list(select_time_ms_percentiles),
            "selected_latency_ms": selected_latency_ms,
        },
        "result": score,
        "note": (
            None
            if score is not None
            else "Не удалось вычислить score: отсутствует/некорректен последний select percentile"
        ),
    }
    return score, details


def _compute_builtin_variant_score(
    *,
    source_insert_time_ms_measurements: Sequence[float],
    tested_insert_time_ms_measurements: Sequence[float],
    source_select_time_ms_measurements: Sequence[float],
    tested_select_time_ms_measurements: Sequence[float],
    source_total_size_bytes: Optional[float],
    tested_total_size_bytes: Optional[float],
) -> tuple[Optional[float], Dict[str, Any]]:
    """
    Встроенная формула score (геометрическое среднее трех ratio по медианам).

    Шаги:
      1) median(source_insert_ms) / median(tested_insert_ms)
      2) median(source_select_ms) / median(tested_select_ms)
      3) source_size_bytes / tested_size_bytes
      4) score = (insert_ratio * select_ratio * compression_ratio) ** (1/3)
    """

    def _median_positive(values: Sequence[float]) -> Optional[float]:
        valid: list[float] = []
        for value in values:
            try:
                numeric = float(value)
            except Exception:
                continue
            if math.isfinite(numeric) and numeric > 0:
                valid.append(numeric)
        if not valid:
            return None
        valid.sort()
        mid = len(valid) // 2
        if len(valid) % 2 == 1:
            return float(valid[mid])
        return float((valid[mid - 1] + valid[mid]) / 2.0)

    source_insert_median = _median_positive(source_insert_time_ms_measurements)
    tested_insert_median = _median_positive(tested_insert_time_ms_measurements)
    source_select_median = _median_positive(source_select_time_ms_measurements)
    tested_select_median = _median_positive(tested_select_time_ms_measurements)

    insert_ratio: Optional[float] = None
    if source_insert_median is not None and tested_insert_median is not None and tested_insert_median > 0:
        insert_ratio = source_insert_median / tested_insert_median
        if insert_ratio <= 0 or not math.isfinite(insert_ratio):
            insert_ratio = None

    select_ratio: Optional[float] = None
    if source_select_median is not None and tested_select_median is not None and tested_select_median > 0:
        select_ratio = source_select_median / tested_select_median
        if select_ratio <= 0 or not math.isfinite(select_ratio):
            select_ratio = None

    compression_ratio: Optional[float] = None
    try:
        source_size = float(source_total_size_bytes or 0.0)
        tested_size = float(tested_total_size_bytes or 0.0)
    except Exception:
        source_size = 0.0
        tested_size = 0.0
    if source_size > 0 and tested_size > 0:
        compression_ratio = source_size / tested_size
        if compression_ratio <= 0 or not math.isfinite(compression_ratio):
            compression_ratio = None

    score: Optional[float] = None
    if (
        insert_ratio is not None
        and select_ratio is not None
        and compression_ratio is not None
    ):
        score = float((insert_ratio * select_ratio * compression_ratio) ** (1.0 / 3.0))

    details: Dict[str, Any] = {
        "formula": (
            "(insert_ratio * select_ratio * compression_ratio) ^ (1/3)"
        ),
        "inputs": {
            "source_insert_time_ms_measurements": list(source_insert_time_ms_measurements),
            "tested_insert_time_ms_measurements": list(tested_insert_time_ms_measurements),
            "source_select_time_ms_measurements": list(source_select_time_ms_measurements),
            "tested_select_time_ms_measurements": list(tested_select_time_ms_measurements),
            "source_size_bytes": source_total_size_bytes,
            "tested_size_bytes": tested_total_size_bytes,
            "source_insert_median_ms": source_insert_median,
            "tested_insert_median_ms": tested_insert_median,
            "source_select_median_ms": source_select_median,
            "tested_select_median_ms": tested_select_median,
            "insert_ratio": insert_ratio,
            "select_ratio": select_ratio,
            "compression_ratio": compression_ratio,
        },
        "result": score,
        "note": (
            None
            if score is not None
            else (
                "Не удалось вычислить score: для builtin нужны валидные медианы "
                "insert/select и валидные размеры source/tested"
            )
        ),
    }
    return score, details


def _resolve_score(
    *,
    scoring: ScoringConfig,
    builtin_score: Optional[float],
    builtin_score_details: Optional[Dict[str, Any]],
    expression_context: Dict[str, Any],
    context_label: str,
) -> tuple[Optional[float], str]:
    """
    Вычисляет итоговый score по конфигу scoring.

    - `builtin` -> возвращает `builtin_score`;
    - `expression` -> вычисляет безопасное expression.
    """
    if scoring.mode == "builtin":
        details: Dict[str, Any] = {
            "mode": "builtin",
            "status": "ok" if builtin_score is not None else "empty",
            "final_score": builtin_score,
            "on_error_score": scoring.on_error_score,
            "details": builtin_score_details or {},
        }
        return builtin_score, _to_pretty_score_calculation_json(details)

    base_details: Dict[str, Any] = {
        "mode": "expression",
        "expression": scoring.expression,
        "on_error_score": scoring.on_error_score,
        "builtin_score_fallback": builtin_score,
        "context": expression_context,
    }

    try:
        score = evaluate_score_expression(
            scoring.expression or "",
            expression_context,
        )
    except ScoreEvaluationError as exc:
        logger.warning(
            "%s: ошибка вычисления scoring.expression: %s",
            context_label,
            exc,
        )
        if scoring.on_error_score is not None:
            fallback_score = float(scoring.on_error_score)
            return fallback_score, _to_pretty_score_calculation_json(
                {
                    **base_details,
                    "status": "fallback_on_error",
                    "error": str(exc),
                    "final_score": fallback_score,
                }
            )
        return None, _to_pretty_score_calculation_json(
            {
                **base_details,
                "status": "error",
                "error": str(exc),
                "final_score": None,
            }
        )

    if not math.isfinite(score):
        logger.warning("%s: scoring.expression вернуло неfinite score=%s", context_label, score)
        if scoring.on_error_score is not None:
            fallback_score = float(scoring.on_error_score)
            return fallback_score, _to_pretty_score_calculation_json(
                {
                    **base_details,
                    "status": "fallback_non_finite",
                    "error": f"non-finite score: {score}",
                    "final_score": fallback_score,
                }
            )
        return None, _to_pretty_score_calculation_json(
            {
                **base_details,
                "status": "non_finite",
                "error": f"non-finite score: {score}",
                "final_score": None,
            }
        )
    final_score = float(score)
    return final_score, _to_pretty_score_calculation_json(
        {
            **base_details,
            "status": "ok",
            "final_score": final_score,
        }
    )


class QueryPayload(BaseModel):
    """Сериализуемое описание одного select-запроса."""

    model_config = ConfigDict(extra="forbid")

    query_id: Optional[str] = None
    query: str
    cache_mode: Literal["warm", "cold"] = "warm"
    select_operations_count: Optional[int] = Field(default=None, gt=0)
    warmup_queries: List[str] = Field(default_factory=list)

    @field_validator("query_id")
    @classmethod
    def _validate_query_id(cls, value: Optional[str]) -> Optional[str]:
        """Проверяет, что query_id не пустой, если задан."""
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("test_queries[].query_id не должен быть пустым")
        return cleaned

    @field_validator("query")
    @classmethod
    def _validate_query_is_safe_and_read_only(cls, value: str) -> str:
        """Проверяет основной query на безопасность и read-only режим."""
        if not is_safe_input_parameter(value):
            raise ValueError("test_queries[].query содержит потенциально опасный SQL.")
        _assert_read_only_query(value, context="test_queries[].query")
        return value

    @field_validator("warmup_queries")
    @classmethod
    def _validate_query_warmups_are_safe_and_read_only(
        cls,
        values: List[str],
    ) -> List[str]:
        """Проверяет query-level warmup запросы."""
        validated: list[str] = []
        for index, query in enumerate(values):
            if not is_safe_input_parameter(query):
                raise ValueError(
                    f"test_queries[].warmup_queries[{index}] содержит потенциально опасный SQL."
                )
            _assert_read_only_query(
                query,
                context=f"test_queries[].warmup_queries[{index}]",
            )
            validated.append(query)
        return validated

    @model_validator(mode="after")
    def _validate_cache_mode_specific_fields(self) -> "QueryPayload":
        """Проверяет согласованность cache_mode и query-level warmup."""
        if self.cache_mode == "cold" and self.warmup_queries:
            raise ValueError(
                "test_queries[].warmup_queries нельзя задавать при cache_mode=cold"
            )
        return self


class QueryPlanPayload(BaseModel):
    """Сериализуемый query-plan для Celery payload."""

    model_config = ConfigDict(extra="forbid")

    test_queries: List[QueryPayload] = Field(default_factory=list)

    @field_validator("test_queries", mode="before")
    @classmethod
    def _coerce_test_queries(cls, value: Any) -> Any:
        """
        Поддерживает legacy-формат `test_queries: [\"SELECT ...\"]`.

        Новый формат: список объектов `QueryPayload`.
        """
        if not isinstance(value, list):
            return value
        coerced: list[Any] = []
        for item in value:
            if isinstance(item, str):
                coerced.append({"query": item})
            else:
                coerced.append(item)
        return coerced


class ConnectionPayload(BaseModel):
    """Сериализуемые параметры подключения ClickHouse."""

    model_config = ConfigDict(extra="forbid")

    host: str
    port: int
    login: str
    password: str

    def to_result_store_params(self) -> ClickHouseConnectionParams:
        """Преобразует payload в параметры подключения store."""
        return ClickHouseConnectionParams(
            host=self.host,
            port=self.port,
            login=self.login,
            password=self.password,
        )


class SourceBenchmarkTaskPayload(BaseModel):
    """Payload baseline benchmark задачи."""

    model_config = ConfigDict(extra="forbid")

    connection: ConnectionPayload
    benchmark_run_id: int
    benchmark_started_at: datetime
    benchmark_id: str
    benchmark_strategy: str = "types_strategy"
    source_database: str
    test_database: Optional[str] = None
    source_table: str
    source_table_ddl: str
    result_connection: Optional[ConnectionPayload] = None
    result_database: Optional[str] = None
    result_table: Optional[str] = None
    result_table_legacy: Optional[str] = None
    result_table_phased: Optional[str] = None
    result_runs_table_phased: Optional[str] = None
    query_plan: QueryPlanPayload
    max_iterations: int
    insert_rows_limit: Optional[int] = None
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    measured_percentiles: List[int] = Field(default_factory=lambda: list(DEFAULT_MEASURED_PERCENTILES))


class VariantBenchmarkTaskPayload(BaseModel):
    """Payload variant benchmark задачи."""

    model_config = ConfigDict(extra="forbid")

    connection: ConnectionPayload
    result_connection: ConnectionPayload
    result_database: str
    result_table: str
    result_table_legacy: Optional[str] = None
    result_table_phased: Optional[str] = None
    result_runs_table_phased: Optional[str] = None

    benchmark_run_id: int
    benchmark_started_at: datetime
    benchmark_id: str
    benchmark_strategy: str = "types_strategy"

    source_database: str
    source_table: str
    variant_database: str
    variant_table: str

    variant_mode: str
    variant_params: Dict[str, Any] = Field(default_factory=dict)
    variant_ddl: str

    max_iterations: int
    insert_rows_limit: Optional[int] = None
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    query_plan: QueryPlanPayload

    source_benchmark: Optional[Dict[str, Any]] = None
    measured_percentiles: List[int] = Field(default_factory=lambda: list(DEFAULT_MEASURED_PERCENTILES))


class _ClickHouseRuntimeClient:
    """Минимальный клиент для benchmark worker-задач."""

    _stream_slots_lock = threading.Lock()
    _stream_slots: dict[tuple[str, int, str], threading.BoundedSemaphore] = {}
    _autogen_session_configured = False
    _autogen_session_configured_lock = threading.Lock()

    def __init__(self, connection: ConnectionPayload) -> None:
        try:
            import clickhouse_connect
        except ImportError as exc:
            raise RuntimeError(
                "clickhouse-connect не установлен. Установи зависимости из requirements.txt"
            ) from exc

        self._configure_clickhouse_common_settings()
        self._client = self._build_clickhouse_client(connection)
        worker_settings = get_clickhouse_celery_worker_settings()
        self._stream_connection = connection
        self._stream_client: Any = None
        self._stream_client_checked = False
        self._stream_insert_client: Any = None
        self._stream_insert_client_checked = False
        self._max_concurrent_streams_per_process = (
            worker_settings.clickhouse_manager_max_concurrent_streams_per_process
        )
        self._stream_slot_acquire_timeout_sec = (
            worker_settings.clickhouse_stream_slot_acquire_timeout_sec
        )
        self._max_copy_n_retries = worker_settings.max_copy_n_retries
        self._max_copy_retry_sleep_sec = worker_settings.max_copy_retry_sleep_sec
        self._max_copy_retry_sleep_sec_increment = (
            worker_settings.max_copy_retry_sleep_sec_increment
        )

    def close(self) -> None:
        """Закрывает клиент."""
        try:
            close_method = getattr(self._client, "close", None)
            if callable(close_method):
                close_method()
        except Exception:
            logger.exception("_ClickHouseRuntimeClient: ошибка close")
        stream_client = self._stream_client
        if stream_client is not None:
            close_method = getattr(stream_client, "close", None)
            if callable(close_method):
                try:
                    close_method()
                except Exception:
                    logger.exception("_ClickHouseRuntimeClient: ошибка close stream client")
        stream_insert_client = getattr(self, "_stream_insert_client", None)
        if stream_insert_client is not None:
            close_method = getattr(stream_insert_client, "close", None)
            if callable(close_method):
                try:
                    close_method()
                except Exception:
                    logger.exception("_ClickHouseRuntimeClient: ошибка close stream insert client")

    def execute(self, query: str, params: Optional[Dict[str, Any]] = None):
        """Проксирует SQL execute."""
        rendered_query = self._bind_query_params(query, params)
        if self._is_read_query(rendered_query):
            result = self._client.query(rendered_query)
            return list(result.result_rows or [])
        self._client.command(rendered_query)
        return []

    @classmethod
    def _bind_query_params(
        cls,
        query: str,
        params: Optional[Dict[str, Any]],
    ) -> str:
        """
        Подставляет `%(name)s` параметры в SQL как литералы.

        Нужно для совместимости с уже существующими SQL-шаблонами.
        """
        if not params:
            return query

        pattern = re.compile(r"%\((?P<key>[A-Za-z_][A-Za-z0-9_]*)\)s")

        def _replace(match: re.Match[str]) -> str:
            key = match.group("key")
            if key not in params:
                raise ValueError(f"Не найден SQL-параметр: {key}")
            return cls._sql_literal(params[key])

        return pattern.sub(_replace, query)

    @staticmethod
    def _sql_literal(value: Any) -> str:
        """Преобразует Python-значение в SQL-литерал ClickHouse."""
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return str(value)
        escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"

    @staticmethod
    def _strip_leading_sql_comments(query: str) -> str:
        """Удаляет ведущие block comments и пробелы."""
        return _strip_leading_sql_comments(query)

    @classmethod
    def _is_read_query(cls, query: str) -> bool:
        """Определяет, что запрос возвращает строки."""
        normalized = cls._strip_leading_sql_comments(query).lower()
        return normalized.startswith(
            ("select", "with", "show", "describe", "desc", "explain")
        )

    def create_database_if_not_exists(self, database: str) -> None:
        """Создаёт БД при отсутствии."""
        self.execute(f"CREATE DATABASE IF NOT EXISTS `{database}`")

    def drop_table_if_exists(
        self,
        database: str,
        table: str,
        *,
        allowed_database: str,
    ) -> None:
        """
        Безопасно удаляет только benchmark-таблицу из явно разрешённой тестовой БД.
        """
        normalized_database = str(database).strip()
        normalized_allowed_database = str(allowed_database).strip()
        normalized_table = str(table).strip()

        if not normalized_database:
            raise ValueError("DROP TABLE: database не должен быть пустым")
        if not normalized_allowed_database:
            raise ValueError("DROP TABLE: allowed_database не должен быть пустым")
        if normalized_database != normalized_allowed_database:
            raise ValueError(
                "DROP TABLE разрешён только в тестовой БД, где создаются benchmark-таблицы"
            )
        if not _is_benchmark_temp_table_name(normalized_table):
            raise ValueError(
                "DROP TABLE разрешён только для benchmark-таблиц "
                "(variant `__bench__...__NNNN` или `__source_baseline__`)"
            )

        self.execute(f"DROP TABLE IF EXISTS `{normalized_database}`.`{normalized_table}`")

    def count_rows(self, database: str, table: str) -> int:
        """Количество строк в таблице."""
        rows = self.execute(
            f"SELECT count() FROM `{database}`.`{table}`"
        )
        if not rows:
            return 0
        return int(rows[0][0] or 0)

    def get_total_compressed_size_bytes(self, database: str, table: str) -> float:
        """
        Суммарный размер таблицы в байтах.

        Приоритет:
          1) `sum(data_compressed_bytes)` из `system.parts`;
          2) fallback `sum(bytes_on_disk)` из `system.parts`.

        Fallback нужен для случаев, когда в конкретной версии/режиме ClickHouse
        `data_compressed_bytes` может быть временно нулевым.
        """
        rows = self.execute(
            """
            SELECT sum(data_compressed_bytes)
            FROM system.parts
            WHERE database = %(database)s
              AND table = %(table)s
              AND active = 1
            """,
            {"database": database, "table": table},
        )
        compressed_size = 0.0
        if rows and rows[0][0] is not None:
            try:
                compressed_size = float(rows[0][0])
            except Exception:
                compressed_size = 0.0
        if compressed_size > 0:
            return compressed_size

        fallback_rows = self.execute(
            """
            SELECT sum(bytes_on_disk)
            FROM system.parts
            WHERE database = %(database)s
              AND table = %(table)s
              AND active = 1
            """,
            {"database": database, "table": table},
        )
        if not fallback_rows or fallback_rows[0][0] is None:
            return 0.0
        try:
            fallback_size = float(fallback_rows[0][0])
        except Exception:
            fallback_size = 0.0
        if fallback_size > 0:
            logger.info(
                "Используем fallback bytes_on_disk для %s.%s: %.0f B",
                database,
                table,
                fallback_size,
            )
        return fallback_size

    def get_table_parts_size_metrics(self, database: str, table: str) -> Dict[str, float]:
        """
        Агрегированные size-метрики таблицы из `system.parts`.

        Основные поля:
          - `data_compressed_bytes`
          - `data_uncompressed_bytes`
          - `bytes_on_disk` (общий размер таблицы на диске, с индексами)
          - `rows`
          - `parts_count`

        Дополнительно (если поддерживается сервером):
          - `primary_key_bytes_in_memory`
          - `secondary_indices_compressed_bytes`
        """
        base_rows = self.execute(
            """
            SELECT
                sum(rows) AS rows,
                sum(data_compressed_bytes) AS data_compressed_bytes,
                sum(data_uncompressed_bytes) AS data_uncompressed_bytes,
                sum(bytes_on_disk) AS bytes_on_disk,
                count() AS parts_count
            FROM system.parts
            WHERE database = %(database)s
              AND table = %(table)s
              AND active = 1
            """,
            {"database": database, "table": table},
        )
        metrics: Dict[str, float] = {
            "rows": 0.0,
            "data_compressed_bytes": 0.0,
            "data_uncompressed_bytes": 0.0,
            "bytes_on_disk": 0.0,
            "parts_count": 0.0,
            "primary_key_bytes_in_memory": 0.0,
            "secondary_indices_compressed_bytes": 0.0,
        }
        if base_rows:
            row = base_rows[0]
            if len(row) >= 5:
                metrics["rows"] = _to_positive_finite_float(row[0])
                metrics["data_compressed_bytes"] = _to_positive_finite_float(row[1])
                metrics["data_uncompressed_bytes"] = _to_positive_finite_float(row[2])
                metrics["bytes_on_disk"] = _to_positive_finite_float(row[3])
                metrics["parts_count"] = _to_positive_finite_float(row[4])

        try:
            extended_rows = self.execute(
                """
                SELECT
                    sum(primary_key_bytes_in_memory) AS primary_key_bytes_in_memory,
                    sum(secondary_indices_compressed_bytes) AS secondary_indices_compressed_bytes
                FROM system.parts
                WHERE database = %(database)s
                  AND table = %(table)s
                  AND active = 1
                """,
                {"database": database, "table": table},
            )
            if extended_rows and len(extended_rows[0]) >= 2:
                metrics["primary_key_bytes_in_memory"] = _to_positive_finite_float(
                    extended_rows[0][0]
                )
                metrics["secondary_indices_compressed_bytes"] = _to_positive_finite_float(
                    extended_rows[0][1]
                )
        except Exception:
            logger.debug(
                "Не удалось получить расширенные size-метрики из system.parts для %s.%s",
                database,
                table,
            )

        return metrics

    def get_column_sizes(self, database: str, table: str) -> Dict[str, Dict[str, Any]]:
        """
        Размеры колонок (compressed bytes) + type.

        Важно для LowCardinality: ClickHouse может хранить фактический объём
        в subcolumns (`col.dictionary`, `col.keys` и т.п.). Поэтому агрегируем
        subcolumns в базовую колонку `col`.
        """
        rows = self.execute(
            """
            SELECT
                name,
                type,
                data_compressed_bytes
            FROM system.columns
            WHERE database = %(database)s
              AND table = %(table)s
            """,
            {"database": database, "table": table},
        )
        aggregated: dict[str, dict[str, Any]] = {}
        has_main_column_type: set[str] = set()

        def _merge_rows(rows_to_merge: Sequence[tuple[Any, Any, Any]]) -> None:
            for raw_name, data_type, compressed_bytes in rows_to_merge:
                full_name = str(raw_name)
                base_name = full_name.split(".", 1)[0]
                is_subcolumn = full_name != base_name
                try:
                    bytes_value = int(compressed_bytes or 0)
                except Exception:
                    bytes_value = 0

                entry = aggregated.get(base_name)
                if entry is None:
                    entry = {
                        "name": base_name,
                        "datatype": str(data_type),
                        "size_compressed_bytes": 0,
                    }
                    aggregated[base_name] = entry

                entry["size_compressed_bytes"] = int(entry["size_compressed_bytes"]) + bytes_value

                # Предпочитаем datatype основной колонки, если он есть.
                if not is_subcolumn:
                    entry["datatype"] = str(data_type)
                    has_main_column_type.add(base_name)
                elif base_name not in has_main_column_type and not entry.get("datatype"):
                    entry["datatype"] = str(data_type)

        _merge_rows(rows)

        # Fallback для случаев, когда system.columns даёт только нули
        # (например, некоторые LowCardinality-представления).
        if _sum_column_compressed_size_bytes(aggregated) <= 0:
            part_bytes_fields = (
                "data_compressed_bytes",
                "column_data_compressed_bytes",
            )
            for bytes_field in part_bytes_fields:
                try:
                    part_rows = self.execute(
                        f"""
                        SELECT
                            `column`,
                            any(type),
                            sum({bytes_field})
                        FROM system.parts_columns
                        WHERE database = %(database)s
                          AND table = %(table)s
                          AND active = 1
                        GROUP BY `column`
                        """,
                        {"database": database, "table": table},
                    )
                    # Не затираем, а домерживаем: datatype из system.columns важнее.
                    # Если в system.columns были только нули, здесь появятся реальные bytes.
                    _merge_rows(part_rows)
                    if _sum_column_compressed_size_bytes(aggregated) > 0:
                        break
                except Exception:
                    logger.exception(
                        "Не удалось получить column sizes из system.parts_columns "
                        "(field=%s) для %s.%s",
                        bytes_field,
                        database,
                        table,
                    )

        # Последний fallback для single-column таблиц: если побайтовой разбивки нет,
        # но общий размер таблицы известен, заполняем им единственную колонку.
        if _sum_column_compressed_size_bytes(aggregated) <= 0 and len(aggregated) == 1:
            total_size_bytes = self.get_total_compressed_size_bytes(database, table)
            if total_size_bytes > 0:
                only_column_name = next(iter(aggregated))
                aggregated[only_column_name]["size_compressed_bytes"] = int(total_size_bytes)

        for entry in aggregated.values():
            bytes_value = int(entry.get("size_compressed_bytes", 0) or 0)
            entry["size_compressed_bytes_readable"] = make_readable_bytes(bytes_value)
        return aggregated

    def get_index_sizes(self, database: str, table: str) -> Dict[str, Dict[str, Any]]:
        """Размеры skip-индексов в bytes."""
        rows = self.execute(
            """
            SELECT
                expr,
                data_compressed_bytes
            FROM system.data_skipping_indices
            WHERE database = %(database)s
              AND table = %(table)s
            """,
            {"database": database, "table": table},
        )
        result: dict[str, dict[str, Any]] = {}
        for expr, compressed_bytes in rows:
            bytes_value = int(compressed_bytes or 0)
            result[str(expr)] = {
                "size_compressed_bytes": bytes_value,
                "size_compressed_bytes_readable": make_readable_bytes(bytes_value),
            }
        return result

    @staticmethod
    def _build_tagged_query(query: str, query_tag: Optional[str]) -> str:
        """Добавляет комментарий-тег к SQL, чтобы запрос проще находился в логах."""
        if not query_tag:
            return query
        return f"/* bench_qid:{query_tag} */ {query}"

    def _execute_command_with_summary_metrics(
        self,
        query: str,
        *,
        query_tag: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        Выполняет SQL через `command` и достаёт метрики только из `result.summary`.
        """
        tagged_query = self._build_tagged_query(query, query_tag)
        try:
            command_result = self._client.command(tagged_query)
        except Exception:
            logger.exception("Не удалось выполнить command SQL для получения summary")
            return _error_query_metrics()

        summary_metrics = self._extract_stream_query_summary(command_result)
        if summary_metrics is not None:
            return summary_metrics

        logger.warning("SQL выполнен, но clickhouse-connect не вернул .summary")
        return _error_query_metrics()

    def execute_select_with_metrics(
        self,
        query: str,
        *,
        query_tag: str,
    ) -> Dict[str, float]:
        """
        Выполняет SELECT и возвращает метрики только из `.summary`.

        Приоритет:
        1) `stream_client.command(...)`;
        2) `stream_client.query(...)`;
        3) `self._client.query(...)`.
        """
        _validate_user_read_only_sql_input(query)
        tagged_query = self._build_tagged_query(query, query_tag)

        stream_client = self._get_stream_client()
        if stream_client is not None:
            try:
                command_result = stream_client.command(tagged_query)
                summary_metrics = self._extract_stream_query_summary(command_result)
                if summary_metrics is not None:
                    return summary_metrics
            except Exception:
                logger.exception("Stream command для select не удался")
            try:
                query_result = stream_client.query(tagged_query)
                summary_metrics = self._extract_stream_query_summary(query_result)
                if summary_metrics is not None:
                    return summary_metrics
            except Exception:
                logger.exception("Stream query для select не удался")

        try:
            query_result = self._client.query(tagged_query)
        except Exception:
            logger.exception("Client query для select не удался")
            return _error_query_metrics()

        summary_metrics = self._extract_stream_query_summary(query_result)
        if summary_metrics is not None:
            return summary_metrics

        logger.warning("SELECT выполнен, но clickhouse-connect не вернул .summary")
        return _error_query_metrics()

    @check_input_params_decorator
    def execute_user_read_only_query(self, query: str) -> list:
        """Выполняет только безопасный read-only SQL из пользовательского query-plan."""
        _assert_read_only_query(query, context="user_query")
        return self.execute(query)

    def _get_stream_client(self) -> Any:
        """
        Возвращает clickhouse-connect client для streaming copy.

        Возвращает `None`, если библиотека/подключение недоступны.
        """
        if getattr(self, "_stream_client_checked", False):
            return getattr(self, "_stream_client", None)

        self._stream_client_checked = True
        try:
            self._stream_client = self._build_clickhouse_client(self._stream_connection)
        except ImportError:
            logger.debug("clickhouse-connect не установлен: stream-клиент недоступен")
            self._stream_client = None
            return None
        except Exception:
            logger.exception("Не удалось создать clickhouse-connect client: используем fallback insert")
            self._stream_client = None
        return self._stream_client

    def _get_stream_insert_client(self) -> Any:
        """
        Возвращает отдельный clickhouse-connect client для raw_insert.

        Важно: клиент записи должен отличаться от клиента чтения (`raw_stream`),
        иначе ClickHouse может вернуть SESSION_IS_LOCKED.
        """
        if getattr(self, "_stream_insert_client_checked", False):
            return getattr(self, "_stream_insert_client", None)

        self._stream_insert_client_checked = True
        try:
            self._stream_insert_client = self._build_clickhouse_client(self._stream_connection)
        except ImportError:
            logger.debug("clickhouse-connect не установлен: stream-insert клиент недоступен")
            self._stream_insert_client = None
            return None
        except Exception:
            logger.exception(
                "Не удалось создать отдельный clickhouse-connect client для raw_insert"
            )
            self._stream_insert_client = None
        return self._stream_insert_client

    @classmethod
    def _configure_clickhouse_common_settings(cls) -> None:
        """
        Применяет legacy-настройку clickhouse-connect:
        `autogenerate_session_id = False`.
        """
        if cls._autogen_session_configured:
            return
        with cls._autogen_session_configured_lock:
            if cls._autogen_session_configured:
                return
            try:
                from clickhouse_connect import common

                common.set_setting("autogenerate_session_id", False)
            except Exception as exc:
                logger.warning(
                    "Не удалось применить clickhouse_connect common setting "
                    "autogenerate_session_id=False: %s",
                    exc,
                )
            cls._autogen_session_configured = True

    @classmethod
    def _build_clickhouse_client(cls, connection: ConnectionPayload) -> Any:
        """
        Создаёт clickhouse-connect client с попыткой отключить auto-session-id.
        """
        import clickhouse_connect

        kwargs = {
            "host": connection.host,
            "port": connection.port,
            "username": connection.login,
            "password": connection.password,
        }
        try:
            return clickhouse_connect.get_client(
                **kwargs,
                autogenerate_session_id=False,
            )
        except TypeError:
            return clickhouse_connect.get_client(**kwargs)

    def _stream_slot_key(self) -> tuple[str, int, str]:
        """Ключ semaphore для ограничения concurrent stream на connection."""
        return (
            self._stream_connection.host,
            self._stream_connection.port,
            self._stream_connection.login,
        )

    def _get_stream_slot(self) -> threading.BoundedSemaphore:
        """Возвращает/создаёт semaphore для текущего connection в рамках процесса."""
        key = self._stream_slot_key()
        with self.__class__._stream_slots_lock:
            slot = self.__class__._stream_slots.get(key)
            if slot is not None:
                return slot
            slot = threading.BoundedSemaphore(
                value=self._max_concurrent_streams_per_process
            )
            self.__class__._stream_slots[key] = slot
            return slot

    def _acquire_stream_slot(self) -> bool:
        """Захватывает stream-slot перед raw_stream/raw_insert."""
        slot = self._get_stream_slot()
        timeout = self._stream_slot_acquire_timeout_sec
        if timeout is None:
            return slot.acquire()
        return slot.acquire(timeout=float(timeout))

    def _release_stream_slot(self) -> None:
        """Освобождает stream-slot после завершения stream-операции."""
        slot = self._get_stream_slot()
        try:
            slot.release()
        except ValueError:
            logger.warning("release_stream_slot вызван лишний раз")

    def get_retry_policy(self) -> tuple[int, float, float]:
        """Возвращает retry policy для insert/select замеров."""
        return (
            self._max_copy_n_retries,
            self._max_copy_retry_sleep_sec,
            self._max_copy_retry_sleep_sec_increment,
        )

    @staticmethod
    def _build_source_select_for_insert(
        *,
        source_database: str,
        source_table: str,
        n_rows: Optional[int],
        offset: int,
        strictly_adhere_n_rows: bool,
        total_rows_in_source_table: Optional[int],
        tested_cols: Optional[Sequence[str]] = None,
    ) -> str:
        """Строит SELECT-часть для insert benchmark (обычный режим или strict-fill)."""
        source_ref = f"`{source_database}`.`{source_table}`"
        filter_columns = [str(col).strip() for col in (tested_cols or []) if str(col).strip()]
        where_clause = ""
        if filter_columns:
            conditions = []
            for column_name in filter_columns:
                escaped_name = column_name.replace("`", "``")
                conditions.append(f"toString(`{escaped_name}`) != ''")
            where_clause = f" WHERE {' AND '.join(conditions)}"

        if n_rows is None:
            return f"SELECT * FROM {source_ref}{where_clause}"

        if (
            strictly_adhere_n_rows
            and total_rows_in_source_table is not None
            and total_rows_in_source_table > 0
            and total_rows_in_source_table < n_rows
        ):
            required_rows = offset + n_rows
            return (
                "WITH\n"
                f"    ifNull((SELECT count() FROM {source_ref}), 0) AS cnt,\n"
                f"    if(cnt = 0, 0, intDiv({required_rows} + cnt - 1, cnt)) AS repeats,\n"
                "    if(repeats = 0, 1, repeats) AS repeats_not_equal_zero\n"
                "SELECT *\n"
                "FROM (\n"
                f"    SELECT * FROM {source_ref}, numbers(repeats_not_equal_zero) AS n\n"
                f"{where_clause}\n"
                f"    LIMIT {n_rows} OFFSET {offset}\n"
                ")"
            )

        return f"SELECT * FROM {source_ref}{where_clause} LIMIT {n_rows} OFFSET {offset}"

    @staticmethod
    def _extract_stream_query_summary(query_summary: Any) -> Optional[Dict[str, float]]:
        """Преобразует summary от clickhouse-connect в словарь метрик."""
        summary: Any = getattr(query_summary, "summary", None)
        if summary is None and isinstance(query_summary, dict):
            summary = query_summary
        if not isinstance(summary, dict):
            return None
        if not any(
            key in summary
            for key in (
                "elapsed_ns",
                "read_rows",
                "read_bytes",
                "written_rows",
                "written_bytes",
            )
        ):
            return None
        return {
            "elapsed_ns": _to_metric_or_error(summary.get("elapsed_ns")),
            "read_rows": _to_metric_or_error(summary.get("read_rows")),
            "read_bytes": _to_metric_or_error(summary.get("read_bytes")),
            "written_rows": _to_metric_or_error(summary.get("written_rows")),
            "written_bytes": _to_metric_or_error(summary.get("written_bytes")),
        }

    @staticmethod
    def _is_stream_empty(stream: Any) -> bool:
        """Проверяет, что `raw_stream` не вернул пустой результат."""
        try:
            headers = getattr(stream, "headers", None)
            if headers is None or not hasattr(headers, "get"):
                return False
            summary_header = headers.get("X-ClickHouse-Summary")
            if not summary_header:
                return False
            summary_payload = json.loads(summary_header)
            read_rows = int(summary_payload.get("read_rows", 0) or 0)
            return read_rows <= 0
        except Exception:
            logger.exception("Не удалось распарсить stream summary header")
            # Legacy-совместимое безопасное поведение:
            # при любой ошибке парсинга считаем stream пустым.
            return True

    def insert_from_source_with_metrics(
        self,
        *,
        source_database: str,
        source_table: str,
        target_database: str,
        target_table: str,
        n_rows: Optional[int],
        offset: int,
        strictly_adhere_n_rows: bool,
        query_tag: str,
        tested_cols: Optional[Sequence[str]] = None,
    ) -> Dict[str, float]:
        """
        Копирует данные из source в target и возвращает метрики.

        Приоритет:
        1) streaming путь через clickhouse-connect (`raw_stream` + `raw_insert`);
        2) fallback через `INSERT INTO ... SELECT ...` + `.summary`.
        """
        if n_rows is not None and n_rows <= 0:
            return _error_query_metrics()
        safe_offset = max(0, offset)
        total_rows_in_source_table: Optional[int] = None
        if n_rows is not None and strictly_adhere_n_rows:
            total_rows_in_source_table = self.count_rows(source_database, source_table)

        source_select_query = self._build_source_select_for_insert(
            source_database=source_database,
            source_table=source_table,
            n_rows=n_rows,
            offset=safe_offset,
            strictly_adhere_n_rows=strictly_adhere_n_rows,
            total_rows_in_source_table=total_rows_in_source_table,
            tested_cols=tested_cols,
        )
        stream_client = self._get_stream_client()
        if stream_client is not None:
            insert_client = self._get_stream_insert_client()
            if insert_client is None:
                insert_client = stream_client
            source_stream = None
            stream_slot_acquired = False
            try:
                stream_slot_acquired = self._acquire_stream_slot()
                if not stream_slot_acquired:
                    logger.error(
                        "Не удалось получить stream slot для %s:%s",
                        self._stream_connection.host,
                        self._stream_connection.port,
                    )
                    return _error_query_metrics()
                source_stream = stream_client.raw_stream(source_select_query, fmt="Native")
                if self._is_stream_empty(source_stream):
                    return _error_query_metrics()
                query_summary = insert_client.raw_insert(
                    table=f"{target_database}.{target_table}",
                    insert_block=source_stream,
                    fmt="Native",
                )
                summary_metrics = self._extract_stream_query_summary(query_summary)
                if summary_metrics is not None:
                    return summary_metrics
                logger.warning("Streaming insert выполнен, но summary недоступен")
                return _error_query_metrics()
            except Exception:
                logger.exception("Streaming insert не удался: переключаемся на fallback INSERT ... SELECT")
            finally:
                if source_stream is not None:
                    close_method = getattr(source_stream, "close", None)
                    if callable(close_method):
                        try:
                            close_method()
                        except Exception:
                            logger.exception("Ошибка закрытия source stream")
                if stream_slot_acquired:
                    self._release_stream_slot()

        insert_query = (
            f"INSERT INTO `{target_database}`.`{target_table}`\n"
            f"{source_select_query}"
        )
        return self._execute_command_with_summary_metrics(
            insert_query,
            query_tag=query_tag,
        )


def _rows_per_second(rows: float, elapsed_ns: float) -> float:
    """Переводит `rows + elapsed_ns` в rows/s."""
    if rows < 0 or elapsed_ns < 0:
        return -1.0
    if elapsed_ns <= 0:
        return -1.0
    elapsed_sec = elapsed_ns / 1_000_000_000.0
    if elapsed_sec <= 0:
        return -1.0
    return rows / elapsed_sec


def _bytes_per_second(size_bytes: float, elapsed_ns: float) -> float:
    """Переводит `bytes + elapsed_ns` в bytes/s."""
    if size_bytes < 0 or elapsed_ns < 0:
        return -1.0
    if elapsed_ns <= 0:
        return -1.0
    elapsed_sec = elapsed_ns / 1_000_000_000.0
    if elapsed_sec <= 0:
        return -1.0
    return size_bytes / elapsed_sec


def _measure_insert(
    client: _ClickHouseRuntimeClient,
    *,
    source_database: str,
    source_table: str,
    target_database: str,
    target_table: str,
    n_rows: Optional[int],
    n_measurements: int,
    tested_cols: Optional[Sequence[str]] = None,
) -> Dict[str, List[float]]:
    """Собирает замеры INSERT со streaming-fast path и strict-fill режимом."""
    elapsed_ns_entries: list[float] = []
    written_rows_per_second_entries: list[float] = []
    read_bytes_per_second_entries: list[float] = []
    written_rows_entries: list[float] = []
    max_retries, initial_sleep_sec, retry_sleep_increment = client.get_retry_policy()

    for measurement_id in range(max(1, n_measurements)):
        offset = max(0, measurement_id * n_rows) if n_rows is not None else 0
        attempt_n = 0
        sleep_sec = initial_sleep_sec
        query_metrics: Dict[str, float] = _error_query_metrics()
        while True:
            query_metrics = client.insert_from_source_with_metrics(
                source_database=source_database,
                source_table=source_table,
                target_database=target_database,
                target_table=target_table,
                n_rows=n_rows,
                offset=offset,
                strictly_adhere_n_rows=True,
                query_tag=f"insert-{uuid.uuid4().hex}",
                tested_cols=tested_cols,
            )
            if not _is_error_query_metrics(query_metrics):
                break

            if max_retries != -1 and attempt_n >= max_retries:
                logger.error(
                    "Не удалось получить корректные insert-метрики для %s.%s (measurement=%d): "
                    "достигнут лимит retries=%d",
                    target_database,
                    target_table,
                    measurement_id,
                    max_retries,
                )
                break

            logger.warning(
                "Ошибка insert-метрик для %s.%s (measurement=%d, attempt=%d). "
                "Повтор через %.2fs",
                target_database,
                target_table,
                measurement_id,
                attempt_n + 1,
                sleep_sec,
            )
            attempt_n += 1
            if sleep_sec > 0:
                time.sleep(sleep_sec)
            sleep_sec += retry_sleep_increment

        elapsed_ns = float(query_metrics["elapsed_ns"])
        read_bytes = float(query_metrics["read_bytes"])
        written_rows = float(query_metrics["written_rows"])
        elapsed_ns_entries.append(elapsed_ns)
        written_rows_per_second_entries.append(_rows_per_second(written_rows, elapsed_ns))
        read_bytes_per_second_entries.append(_bytes_per_second(read_bytes, elapsed_ns))
        written_rows_entries.append(written_rows)

    context = f"insert metrics {target_database}.{target_table}"
    return {
        "elapsed_ns": _filter_positive_finite_measurements(
            elapsed_ns_entries,
            metric_name="elapsed_ns",
            context=context,
        ),
        "rows_per_second": _filter_positive_finite_measurements(
            written_rows_per_second_entries,
            metric_name="rows_per_second",
            context=context,
        ),
        "bytes_per_second": _filter_positive_finite_measurements(
            read_bytes_per_second_entries,
            metric_name="bytes_per_second",
            context=context,
        ),
        "written_rows": _filter_positive_finite_measurements(
            written_rows_entries,
            metric_name="written_rows",
            context=context,
        ),
    }


def _normalize_select_query_payload(
    query_entry: Any,
    *,
    default_measurements: int,
) -> QueryPayload:
    """Нормализует query entry к `QueryPayload`."""
    if isinstance(query_entry, QueryPayload):
        payload = query_entry
    elif isinstance(query_entry, str):
        payload = QueryPayload(query=query_entry)
    elif isinstance(query_entry, dict):
        payload = QueryPayload.model_validate(query_entry)
    else:
        raise ValueError(f"Некорректный test query payload: {query_entry!r}")

    if payload.select_operations_count is None:
        fallback_count = max(1, int(default_measurements))
        return payload.model_copy(update={"select_operations_count": fallback_count})
    return payload


def _measure_select_queries(
    client: _ClickHouseRuntimeClient,
    *,
    test_queries: Sequence[QueryPayload | str | Dict[str, Any]],
    n_measurements: int,
) -> Dict[str, Any]:
    """Собирает замеры SELECT-запросов с поддержкой warm/cold режимов."""
    elapsed_ns_entries: list[float] = []
    read_rows_per_second_entries: list[float] = []
    read_bytes_per_second_entries: list[float] = []
    per_query_entries: list[dict[str, Any]] = []
    max_retries, initial_sleep_sec, retry_sleep_increment = client.get_retry_policy()

    if not test_queries:
        return {
            "elapsed_ns": elapsed_ns_entries,
            "rows_per_second": read_rows_per_second_entries,
            "bytes_per_second": read_bytes_per_second_entries,
            "per_query": per_query_entries,
        }

    for query_index, raw_query_payload in enumerate(test_queries):
        query_payload = _normalize_select_query_payload(
            raw_query_payload,
            default_measurements=n_measurements,
        )
        query_id = query_payload.query_id or f"query_{query_index}"
        query = query_payload.query
        query_cache_mode = query_payload.cache_mode
        query_measurements_count = int(query_payload.select_operations_count or 1)
        query_warmup_queries = list(query_payload.warmup_queries)

        query_elapsed_ns_entries: list[float] = []
        query_rows_per_second_entries: list[float] = []
        query_bytes_per_second_entries: list[float] = []
        cold_settings_assignments: Optional[List[str]] = None

        if query_cache_mode == "cold":
            cold_settings_assignments = list(_COLD_SELECT_SETTINGS_ASSIGNMENTS)

        if query_cache_mode == "warm":
            for warmup_query in query_warmup_queries:
                client.execute_user_read_only_query(warmup_query)

        for measurement_id in range(max(1, query_measurements_count)):
            effective_query = query
            if query_cache_mode == "cold":
                effective_query = _with_cold_select_settings(
                    query,
                    settings_assignments=cold_settings_assignments,
                )

            attempt_n = 0
            sleep_sec = initial_sleep_sec
            query_metrics: Dict[str, float] = _error_query_metrics()
            while True:
                query_metrics = client.execute_select_with_metrics(
                    effective_query,
                    query_tag=f"select-{uuid.uuid4().hex}",
                )
                if not _is_error_query_metrics(query_metrics):
                    break

                if max_retries != -1 and attempt_n >= max_retries:
                    logger.error(
                        "Не удалось получить корректные select-метрики "
                        "(query=%s, measurement=%d): достигнут лимит retries=%d",
                        query,
                        measurement_id,
                        max_retries,
                    )
                    break

                logger.warning(
                    "Ошибка select-метрик (query=%s, measurement=%d, attempt=%d). Повтор через %.2fs",
                    query,
                    measurement_id,
                    attempt_n + 1,
                    sleep_sec,
                )
                attempt_n += 1
                if sleep_sec > 0:
                    time.sleep(sleep_sec)
                sleep_sec += retry_sleep_increment

            elapsed_ns = float(query_metrics["elapsed_ns"])
            read_rows = float(query_metrics["read_rows"])
            read_bytes = float(query_metrics["read_bytes"])
            query_rows_per_second = _rows_per_second(read_rows, elapsed_ns)
            query_bytes_per_second = _bytes_per_second(read_bytes, elapsed_ns)

            query_elapsed_ns_entries.append(elapsed_ns)
            query_rows_per_second_entries.append(query_rows_per_second)
            query_bytes_per_second_entries.append(query_bytes_per_second)

        query_context = f"select metrics query[{query_index}]"
        query_elapsed_ns_entries = _filter_positive_finite_measurements(
            query_elapsed_ns_entries,
            metric_name="elapsed_ns",
            context=query_context,
        )
        query_rows_per_second_entries = _filter_positive_finite_measurements(
            query_rows_per_second_entries,
            metric_name="rows_per_second",
            context=query_context,
        )
        query_bytes_per_second_entries = _filter_positive_finite_measurements(
            query_bytes_per_second_entries,
            metric_name="bytes_per_second",
            context=query_context,
        )
        elapsed_ns_entries.extend(query_elapsed_ns_entries)
        read_rows_per_second_entries.extend(query_rows_per_second_entries)
        read_bytes_per_second_entries.extend(query_bytes_per_second_entries)

        per_query_entries.append(
            {
                "query_index": query_index,
                "query_id": query_id,
                "query": query,
                "cache_mode": query_cache_mode,
                "select_operations_count": query_measurements_count,
                "warmup_queries": query_warmup_queries,
                "elapsed_ns_measurements": query_elapsed_ns_entries,
                "rows_per_second_measurements": query_rows_per_second_entries,
                "bytes_per_second_measurements": query_bytes_per_second_entries,
            }
        )

    return {
        "elapsed_ns": elapsed_ns_entries,
        "rows_per_second": read_rows_per_second_entries,
        "bytes_per_second": read_bytes_per_second_entries,
        "per_query": per_query_entries,
    }


def _build_select_per_query_metrics(
    per_query_entries: Sequence[Dict[str, Any]],
    measured_percentiles: Sequence[int],
) -> List[Dict[str, Any]]:
    """
    Строит детальные select-метрики отдельно по каждому запросу.

    Возвращает список, где каждый элемент содержит:
      - исходный query и query_index;
      - measurements по latency/rows/s/bytes/s;
      - percentiles для каждой метрики.
    """
    result: list[dict[str, Any]] = []
    for fallback_index, raw_entry in enumerate(per_query_entries):
        query = str(raw_entry.get("query", ""))
        query_index = int(raw_entry.get("query_index", fallback_index))
        query_id = str(raw_entry.get("query_id", f"query_{query_index}"))

        entry_context = f"select per-query metrics query[{query_index}]"
        elapsed_ns_measurements = _filter_positive_finite_measurements(
            list(float(value) for value in (raw_entry.get("elapsed_ns_measurements", []) or [])),
            metric_name="elapsed_ns",
            context=entry_context,
        )
        rows_per_second_measurements = _filter_positive_finite_measurements(
            list(float(value) for value in (raw_entry.get("rows_per_second_measurements", []) or [])),
            metric_name="rows_per_second",
            context=entry_context,
        )
        bytes_per_second_measurements = _filter_positive_finite_measurements(
            list(float(value) for value in (raw_entry.get("bytes_per_second_measurements", []) or [])),
            metric_name="bytes_per_second",
            context=entry_context,
        )

        elapsed_ms_measurements = [
            value / 1_000_000.0 for value in elapsed_ns_measurements
        ]

        elapsed_ms_percentiles = compute_percentiles(
            elapsed_ms_measurements,
            measured_percentiles,
        )
        rows_per_second_percentiles = compute_percentiles(
            rows_per_second_measurements,
            measured_percentiles,
        )
        bytes_per_second_percentiles = compute_percentiles(
            bytes_per_second_measurements,
            measured_percentiles,
        )

        result.append(
            {
                "query_index": query_index,
                "query_id": query_id,
                "query": query,
                "cache_mode": str(raw_entry.get("cache_mode", "warm")),
                "select_operations_count": int(
                    raw_entry.get(
                        "select_operations_count",
                        max(1, len(elapsed_ms_measurements)),
                    )
                ),
                "warmup_queries": list(raw_entry.get("warmup_queries", []) or []),
                "elapsed_ms_measurements": elapsed_ms_measurements,
                "elapsed_ms_percentiles": elapsed_ms_percentiles,
                "rows_per_second_measurements": rows_per_second_measurements,
                "rows_per_second_percentiles": rows_per_second_percentiles,
                "bytes_per_second_measurements": bytes_per_second_measurements,
                "bytes_per_second_percentiles": bytes_per_second_percentiles,
            }
        )
    return result


def _extract_source_select_per_query_metrics(
    source_metrics: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Возвращает per-query метрики source select.

    Поддерживает оба формата:
      - новый: `source_table_select_metrics_by_query`;
      - старый: один агрегированный набор (`source_table_select_*`), который
        преобразуется в single-query представление.
    """
    direct_value = source_metrics.get("source_table_select_metrics_by_query")
    if isinstance(direct_value, list):
        normalized_entries: list[dict[str, Any]] = []
        for fallback_index, entry in enumerate(direct_value):
            if not isinstance(entry, dict):
                continue
            normalized_entry = dict(entry)
            query_index = int(normalized_entry.get("query_index", fallback_index))
            normalized_entry.setdefault("query_index", query_index)
            normalized_entry.setdefault("query_id", f"query_{query_index}")
            normalized_entries.append(normalized_entry)
        return normalized_entries

    legacy_query = source_metrics.get("source_table_select_test_query")
    legacy_elapsed_ms_measurements = list(
        source_metrics.get("source_table_select_time_ms_measurements", []) or []
    )
    legacy_elapsed_ms_percentiles = list(
        source_metrics.get("source_table_select_time_ms_measurements_percentiles", []) or []
    )
    legacy_rows_per_second_measurements = list(
        source_metrics.get("source_table_select_rows_per_second_measurements", []) or []
    )
    legacy_rows_per_second_percentiles = list(
        source_metrics.get("source_table_select_rows_per_second_measurements_percentiles", []) or []
    )
    legacy_bytes_per_second_measurements = list(
        source_metrics.get("source_table_select_bytes_per_second_measurements", []) or []
    )
    legacy_bytes_per_second_percentiles = list(
        source_metrics.get("source_table_select_bytes_per_second_measurements_percentiles", []) or []
    )
    if (
        not legacy_query
        and not legacy_elapsed_ms_measurements
        and not legacy_elapsed_ms_percentiles
        and not legacy_rows_per_second_measurements
        and not legacy_rows_per_second_percentiles
        and not legacy_bytes_per_second_measurements
        and not legacy_bytes_per_second_percentiles
    ):
        return []

    return [
        {
            "query_index": 0,
            "query_id": "query_0",
            "query": str(legacy_query or ""),
            "cache_mode": "warm",
            "select_operations_count": len(legacy_elapsed_ms_measurements),
            "warmup_queries": [],
            "elapsed_ms_measurements": [float(v) for v in legacy_elapsed_ms_measurements],
            "elapsed_ms_percentiles": [float(v) for v in legacy_elapsed_ms_percentiles],
            "rows_per_second_measurements": [float(v) for v in legacy_rows_per_second_measurements],
            "rows_per_second_percentiles": [float(v) for v in legacy_rows_per_second_percentiles],
            "bytes_per_second_measurements": [float(v) for v in legacy_bytes_per_second_measurements],
            "bytes_per_second_percentiles": [float(v) for v in legacy_bytes_per_second_percentiles],
        }
    ]


def _compute_select_time_speedup_by_query(
    source_per_query: Sequence[Dict[str, Any]],
    tested_per_query: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Считает speed-up (`source/tested`) отдельно по каждому select-запросу."""
    def _coerce_float_list(values: Any) -> list[float]:
        result_values: list[float] = []
        if not isinstance(values, list):
            return result_values
        for value in values:
            try:
                result_values.append(float(value))
            except Exception:
                continue
        return result_values

    source_by_index: dict[int, Dict[str, Any]] = {}
    source_by_id: dict[str, Dict[str, Any]] = {}
    for fallback_index, entry in enumerate(source_per_query):
        query_index = int(entry.get("query_index", fallback_index))
        source_by_index[query_index] = entry
        query_id = str(entry.get("query_id", f"query_{query_index}"))
        source_by_id[query_id] = entry

    result: list[dict[str, Any]] = []
    for fallback_index, tested_entry in enumerate(tested_per_query):
        query_index = int(tested_entry.get("query_index", fallback_index))
        query_id = str(tested_entry.get("query_id", f"query_{query_index}"))
        source_entry = source_by_id.get(query_id) or source_by_index.get(query_index)
        source_percentiles = (
            _coerce_float_list(source_entry.get("elapsed_ms_percentiles", []))
            if source_entry is not None
            else []
        )
        tested_percentiles = _coerce_float_list(tested_entry.get("elapsed_ms_percentiles", []))
        speed_up_coefs = compute_speedup_coefficients(source_percentiles, tested_percentiles)
        result.append(
            {
                "query_index": query_index,
                "query_id": query_id,
                "query": tested_entry.get("query"),
                "source_query": source_entry.get("query") if source_entry is not None else None,
                "elapsed_ms_percentiles_speed_up_coefs": speed_up_coefs,
            }
        )
    return result


def _build_per_query_expression_context(
    *,
    source_per_query: Sequence[Dict[str, Any]],
    tested_per_query: Sequence[Dict[str, Any]],
    speedup_per_query: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Собирает per-query контекст для scoring expression."""

    def _to_query_id_map(entries: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        result: dict[str, Dict[str, Any]] = {}
        for fallback_index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            query_index = int(entry.get("query_index", fallback_index))
            query_id = str(entry.get("query_id", f"query_{query_index}"))
            result[query_id] = entry
        return result

    def _to_query_index_map(entries: Sequence[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
        result: dict[int, Dict[str, Any]] = {}
        for fallback_index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            query_index = int(entry.get("query_index", fallback_index))
            result[query_index] = entry
        return result

    return {
        "source": list(source_per_query),
        "tested": list(tested_per_query),
        "speedup": list(speedup_per_query),
        "source_by_query_id": _to_query_id_map(source_per_query),
        "tested_by_query_id": _to_query_id_map(tested_per_query),
        "speedup_by_query_id": _to_query_id_map(speedup_per_query),
        "source_by_query_index": _to_query_index_map(source_per_query),
        "tested_by_query_index": _to_query_index_map(tested_per_query),
        "speedup_by_query_index": _to_query_index_map(speedup_per_query),
    }


def _extract_source_metrics(source_benchmark_payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Безопасно достаёт baseline metrics из payload source benchmark."""
    if not source_benchmark_payload:
        return {}
    metrics = source_benchmark_payload.get("metrics")
    if isinstance(metrics, dict):
        return metrics
    return {}


def _build_baseline_copy_ddl(
    source_table_ddl: str,
    *,
    target_database: str,
    target_table: str,
) -> str:
    """
    Строит DDL временной baseline-таблицы на базе исходного DDL.

    Основной путь: парсим через `TableDDL` и только меняем полное имя таблицы.
    """
    parsed = TableDDL.from_ddl(source_table_ddl)
    parsed.name = f"{target_database}.{target_table}"
    return parsed.to_ddl()


def _rewrite_queries_to_baseline_copy(
    queries: Sequence[str],
    *,
    source_database: str,
    source_table: str,
    baseline_database: str,
    baseline_table: str,
) -> List[str]:
    """
    Переписывает ссылки на исходную таблицу в SQL на baseline-копию.

    Цель: baseline select/warmup должны выполняться по копии исходного DDL,
    а не по оригинальной source-таблице.
    """
    source_ref_quoted = f"`{source_database}`.`{source_table}`"
    source_ref_plain = f"{source_database}.{source_table}"
    source_ref_mixed_db = f"`{source_database}`.{source_table}"
    source_ref_mixed_table = f"{source_database}.`{source_table}`"
    baseline_ref_quoted = f"`{baseline_database}`.`{baseline_table}`"

    rewritten: list[str] = []
    for query in queries:
        updated = query.replace(source_ref_quoted, baseline_ref_quoted)
        updated = updated.replace(source_ref_plain, baseline_ref_quoted)
        updated = updated.replace(source_ref_mixed_db, baseline_ref_quoted)
        updated = updated.replace(source_ref_mixed_table, baseline_ref_quoted)
        rewritten.append(updated)
    return rewritten


def _rewrite_query_payloads_to_baseline_copy(
    queries: Sequence[QueryPayload],
    *,
    source_database: str,
    source_table: str,
    baseline_database: str,
    baseline_table: str,
) -> List[QueryPayload]:
    """
    Переписывает table refs в query-level payload на baseline-копию.

    Меняет и основной `query`, и query-level `warmup_queries`.
    """
    rewritten_payloads: list[QueryPayload] = []
    for query_payload in queries:
        rewritten_query = _rewrite_queries_to_baseline_copy(
            [query_payload.query],
            source_database=source_database,
            source_table=source_table,
            baseline_database=baseline_database,
            baseline_table=baseline_table,
        )[0]
        rewritten_warmups = _rewrite_queries_to_baseline_copy(
            list(query_payload.warmup_queries),
            source_database=source_database,
            source_table=source_table,
            baseline_database=baseline_database,
            baseline_table=baseline_table,
        )
        rewritten_payloads.append(
            query_payload.model_copy(
                update={
                    "query": rewritten_query,
                    "warmup_queries": rewritten_warmups,
                }
            )
        )
    return rewritten_payloads


def _to_json_or_none(value: Any) -> Optional[str]:
    """Сериализует структуру в JSON-строку или возвращает None."""
    if value is None:
        return None
    return json_dumps(value)


def _to_legacy_pretty_json_or_none(value: Any) -> Optional[str]:
    """Сериализует структуру в legacy-совместимый pretty JSON или возвращает None."""
    if value is None:
        return None
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=str,
    )


def _build_baseline_variant_result(
    *,
    payload: SourceBenchmarkTaskPayload,
    baseline_database: str,
    baseline_table: str,
    baseline_ddl: str,
    metrics: Dict[str, Any],
    baseline_score: Optional[float],
    baseline_score_calculation_json: Optional[str],
) -> BenchmarkVariantResult:
    """
    Строит `BenchmarkVariantResult` для baseline-замера исходного DDL.

    Записывается отдельной строкой в result-store как `variant_mode=source_baseline`.
    """
    measured_percentiles = list(metrics.get("measured_percentiles", []) or [])

    source_insert_ms = list(metrics.get("source_table_insert_time_ms_measurements", []) or [])
    source_insert_ms_percentiles = list(
        metrics.get("source_table_insert_time_ms_measurements_percentiles", []) or []
    )
    source_insert_rows_per_sec = list(
        metrics.get("source_table_insert_rows_per_second_measurements", []) or []
    )
    source_insert_rows_per_sec_percentiles = list(
        metrics.get("source_table_insert_rows_per_second_measurements_percentiles", []) or []
    )
    source_insert_bytes_per_sec = list(
        metrics.get("source_table_insert_bytes_per_second_measurements", []) or []
    )
    source_insert_bytes_per_sec_readable = list(
        metrics.get("source_table_insert_bytes_per_second_measurements_readable", []) or []
    )
    source_insert_bytes_per_sec_percentiles = list(
        metrics.get("source_table_insert_bytes_per_second_measurements_percentiles", []) or []
    )
    source_insert_bytes_per_sec_percentiles_readable = list(
        metrics.get("source_table_insert_bytes_per_second_measurements_percentiles_readable", [])
        or []
    )

    source_select_ms = list(metrics.get("source_table_select_time_ms_measurements", []) or [])
    source_select_ms_percentiles = list(
        metrics.get("source_table_select_time_ms_measurements_percentiles", []) or []
    )
    source_select_rows_per_sec = list(
        metrics.get("source_table_select_rows_per_second_measurements", []) or []
    )
    source_select_rows_per_sec_percentiles = list(
        metrics.get("source_table_select_rows_per_second_measurements_percentiles", []) or []
    )
    source_select_bytes_per_sec = list(
        metrics.get("source_table_select_bytes_per_second_measurements", []) or []
    )
    source_select_bytes_per_sec_readable = list(
        metrics.get("source_table_select_bytes_per_second_measurements_readable", []) or []
    )
    source_select_bytes_per_sec_percentiles = list(
        metrics.get("source_table_select_bytes_per_second_measurements_percentiles", []) or []
    )
    source_select_bytes_per_sec_percentiles_readable = list(
        metrics.get("source_table_select_bytes_per_second_measurements_percentiles_readable", [])
        or []
    )

    source_total_size_bytes = float(
        metrics.get("source_table_consumed_compressed_size_bytes_overall", 0.0) or 0.0
    )
    tested_total_size_bytes = float(
        metrics.get("tested_table_consumed_compressed_size_bytes_overall", source_total_size_bytes)
        or source_total_size_bytes
    )
    tested_total_size_bytes_with_indexes = float(
        metrics.get(
            "tested_table_consumed_compressed_size_bytes_with_indexes",
            metrics.get("tested_table_total_size_bytes_with_indexes", tested_total_size_bytes),
        )
        or tested_total_size_bytes
    )
    source_rows = int(metrics.get("total_n_rows_in_source_table", 0) or 0)
    tested_rows = int(metrics.get("total_n_rows_in_tested_table", source_rows) or source_rows)
    tested_columns_size_map = (
        metrics.get("tested_table_consumed_compressed_size_bytes_by_each_column")
        or metrics.get("source_table_consumed_compressed_size_bytes_by_each_column")
    )
    compression_overall_coef: Optional[float] = None
    if source_total_size_bytes > 0:
        compression_overall_coef = tested_total_size_bytes / source_total_size_bytes

    return BenchmarkVariantResult(
        benchmark_run_id=payload.benchmark_run_id,
        benchmark_started_at=payload.benchmark_started_at,
        benchmark_id=payload.benchmark_id,
        source_database=payload.source_database,
        source_table=payload.source_table,
        variant_table=baseline_table,
        variant_mode="source_baseline",
        variant_params={
            "kind": "source_baseline",
            "baseline_database": baseline_database,
            "baseline_table": baseline_table,
        },
        source_table_ddl=payload.source_table_ddl,
        tested_table_ddl=baseline_ddl,
        is_source_table_copy=True,
        total_n_rows_in_tested_table=tested_rows,
        total_n_rows_in_source_table=source_rows,
        measured_percentiles=measured_percentiles,
        insert_test_n_rows=payload.insert_rows_limit,
        tested_table_insert_time_ms_measurements=source_insert_ms,
        source_table_insert_time_ms_measurements=source_insert_ms,
        tested_table_insert_time_ms_measurements_percentiles=source_insert_ms_percentiles,
        source_table_insert_time_ms_measurements_percentiles=source_insert_ms_percentiles,
        tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs=(
            compute_speedup_coefficients(source_insert_ms_percentiles, source_insert_ms_percentiles)
        ),
        tested_table_insert_rows_per_second_measurements=source_insert_rows_per_sec,
        source_table_insert_rows_per_second_measurements=source_insert_rows_per_sec,
        tested_table_insert_rows_per_second_measurements_percentiles=(
            source_insert_rows_per_sec_percentiles
        ),
        source_table_insert_rows_per_second_measurements_percentiles=(
            source_insert_rows_per_sec_percentiles
        ),
        tested_table_insert_bytes_per_second_measurements=source_insert_bytes_per_sec,
        tested_table_insert_bytes_per_second_measurements_readable=source_insert_bytes_per_sec_readable,
        source_table_insert_bytes_per_second_measurements=source_insert_bytes_per_sec,
        source_table_insert_bytes_per_second_measurements_readable=(
            source_insert_bytes_per_sec_readable
        ),
        tested_table_insert_bytes_per_second_measurements_percentiles=(
            source_insert_bytes_per_sec_percentiles
        ),
        tested_table_insert_bytes_per_second_measurements_percentiles_readable=(
            source_insert_bytes_per_sec_percentiles_readable
        ),
        source_table_insert_bytes_per_second_measurements_percentiles=(
            source_insert_bytes_per_sec_percentiles
        ),
        source_table_insert_bytes_per_second_measurements_percentiles_readable=(
            source_insert_bytes_per_sec_percentiles_readable
        ),
        tested_table_select_test_query=metrics.get("source_table_select_test_query"),
        source_table_select_test_query=metrics.get("source_table_select_test_query"),
        tested_table_select_time_ms_measurements=source_select_ms,
        source_table_select_time_ms_measurements=source_select_ms,
        tested_table_select_time_ms_measurements_percentiles=source_select_ms_percentiles,
        source_table_select_time_ms_measurements_percentiles=source_select_ms_percentiles,
        tested_table_select_time_ms_measurements_percentiles_speed_up_coefs=(
            compute_speedup_coefficients(source_select_ms_percentiles, source_select_ms_percentiles)
        ),
        tested_table_select_rows_per_second_measurements=source_select_rows_per_sec,
        source_table_select_rows_per_second_measurements=source_select_rows_per_sec,
        tested_table_select_rows_per_second_measurements_percentiles=(
            source_select_rows_per_sec_percentiles
        ),
        source_table_select_rows_per_second_measurements_percentiles=(
            source_select_rows_per_sec_percentiles
        ),
        tested_table_select_bytes_per_second_measurements=source_select_bytes_per_sec,
        tested_table_select_bytes_per_second_measurements_readable=source_select_bytes_per_sec_readable,
        source_table_select_bytes_per_second_measurements=source_select_bytes_per_sec,
        source_table_select_bytes_per_second_measurements_readable=(
            source_select_bytes_per_sec_readable
        ),
        tested_table_select_bytes_per_second_measurements_percentiles=(
            source_select_bytes_per_sec_percentiles
        ),
        tested_table_select_bytes_per_second_measurements_percentiles_readable=(
            source_select_bytes_per_sec_percentiles_readable
        ),
        source_table_select_bytes_per_second_measurements_percentiles=(
            source_select_bytes_per_sec_percentiles
        ),
        source_table_select_bytes_per_second_measurements_percentiles_readable=(
            source_select_bytes_per_sec_percentiles_readable
        ),
        tested_table_select_metrics_by_query_json=_to_legacy_pretty_json_or_none(
            metrics.get("source_table_select_metrics_by_query")
        ),
        source_table_select_metrics_by_query_json=_to_legacy_pretty_json_or_none(
            metrics.get("source_table_select_metrics_by_query")
        ),
        tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json=_to_legacy_pretty_json_or_none(
            _compute_select_time_speedup_by_query(
                metrics.get("source_table_select_metrics_by_query", []) or [],
                metrics.get("source_table_select_metrics_by_query", []) or [],
            )
        ),
        tested_table_consumed_compressed_size_bytes_by_each_column=_to_legacy_pretty_json_or_none(
            tested_columns_size_map
        ),
        source_table_consumed_compressed_size_bytes_by_each_column=_to_legacy_pretty_json_or_none(
            metrics.get("source_table_consumed_compressed_size_bytes_by_each_column")
        ),
        tested_table_consumed_compressed_size_bytes_overall=tested_total_size_bytes,
        tested_table_consumed_compressed_size_bytes_overall_readable=make_readable_bytes(
            tested_total_size_bytes
        ),
        tested_table_consumed_compressed_size_bytes_with_indexes=tested_total_size_bytes_with_indexes,
        tested_table_consumed_compressed_size_bytes_with_indexes_readable=make_readable_bytes(
            tested_total_size_bytes_with_indexes
        ),
        source_table_consumed_compressed_size_bytes_overall=source_total_size_bytes,
        source_table_consumed_compressed_size_bytes_overall_readable=make_readable_bytes(
            source_total_size_bytes
        ),
        tested_table_compression_overall_coef=compression_overall_coef,
        tested_table_compression_by_each_column_coef=_to_legacy_pretty_json_or_none({}),
        source_table_n_rows_in_size_test=source_rows,
        tested_table_n_rows_in_size_test=int(
            metrics.get("tested_table_n_rows_in_size_test", tested_rows) or tested_rows
        ),
        score_calculation_json=baseline_score_calculation_json,
        score=baseline_score,
        extra_json=_to_json_or_none(
            {
                "baseline_database": baseline_database,
                "baseline_table": baseline_table,
            }
        ),
    )


def _store_source_benchmark_result_if_configured(
    *,
    payload: SourceBenchmarkTaskPayload,
    baseline_database: str,
    baseline_table: str,
    baseline_ddl: str,
    result: SourceBenchmarkResult,
) -> None:
    """Сохраняет baseline-результат в result-store, если target задан в payload."""
    if payload.result_connection is None:
        return
    if not payload.result_database or not payload.result_table:
        return

    store = ClickHouseBenchmarkResultStore(
        connection=payload.result_connection.to_result_store_params(),
        database=payload.result_database,
        table=payload.result_table,
        legacy_table=payload.result_table_legacy,
        phased_table=payload.result_table_phased,
        phased_runs_table=payload.result_runs_table_phased,
        create_legacy_table=not _is_phased_strategy(payload.benchmark_strategy),
        create_table_if_missing=True,
    )
    try:
        row_result = _build_baseline_variant_result(
            payload=payload,
            baseline_database=baseline_database,
            baseline_table=baseline_table,
            baseline_ddl=baseline_ddl,
            metrics=result.metrics,
            baseline_score=result.score,
            baseline_score_calculation_json=result.score_calculation_json,
        )
        store.store_worker_result(
            benchmark_run_id=payload.benchmark_run_id,
            benchmark_started_at=payload.benchmark_started_at,
            benchmark_id=payload.benchmark_id,
            benchmark_strategy=payload.benchmark_strategy,
            source_database=payload.source_database,
            source_table=payload.source_table,
            variant_table=baseline_table,
            variant_mode="source_baseline",
            variant_params=dict(row_result.variant_params),
            tested_table_ddl_fallback=baseline_ddl,
            source_table_ddl_fallback=payload.source_table_ddl,
            result=row_result,
        )
    finally:
        store.close()


def run_source_benchmark(payload: SourceBenchmarkTaskPayload) -> SourceBenchmarkResult:
    """
    Реальное выполнение baseline benchmark на исходном DDL.

    Поведение соответствует legacy-подходу:
    1) создаём временную таблицу-копию исходного DDL;
    2) измеряем baseline insert (source -> baseline copy);
    3) измеряем baseline select на baseline-копии;
    4) прокидываем baseline-метрики в `SourceBenchmarkResult.metrics`.
    """
    client = _ClickHouseRuntimeClient(payload.connection)
    baseline_database = payload.test_database or f"{payload.source_database}__benchmark_tmp"
    baseline_table = f"{payload.source_table}__source_baseline__{uuid.uuid4().hex}"
    try:
        source_total_rows = client.count_rows(payload.source_database, payload.source_table)
        if source_total_rows <= 0:
            logger.warning(
                "run_source_benchmark: source таблица %s.%s содержит 0 строк, "
                "baseline-бенчмарк пропущен",
                payload.source_database,
                payload.source_table,
            )
            return SourceBenchmarkResult(
                benchmark_run_id=payload.benchmark_run_id,
                benchmark_started_at=payload.benchmark_started_at,
                benchmark_id=payload.benchmark_id,
                source_database=payload.source_database,
                source_table=payload.source_table,
                source_table_ddl=payload.source_table_ddl,
                score_calculation_json=_to_pretty_score_calculation_json(
                    {
                        "mode": payload.scoring.mode,
                        "status": "skipped",
                        "reason": "source_table_empty",
                        "final_score": None,
                    }
                ),
                score=None,
                metrics={
                    "status": "skipped",
                    "skip_reason": "source_table_empty",
                    "total_n_rows_in_source_table": 0,
                    "total_n_rows_in_tested_table": 0,
                },
            )

        client.create_database_if_not_exists(baseline_database)
        client.drop_table_if_exists(
            baseline_database,
            baseline_table,
            allowed_database=baseline_database,
        )
        baseline_ddl = _build_baseline_copy_ddl(
            payload.source_table_ddl,
            target_database=baseline_database,
            target_table=baseline_table,
        )
        client.execute(baseline_ddl)

        baseline_test_queries = _rewrite_query_payloads_to_baseline_copy(
            payload.query_plan.test_queries,
            source_database=payload.source_database,
            source_table=payload.source_table,
            baseline_database=baseline_database,
            baseline_table=baseline_table,
        )

        insert_stats = _measure_insert(
            client,
            source_database=payload.source_database,
            source_table=payload.source_table,
            target_database=baseline_database,
            target_table=baseline_table,
            n_rows=payload.insert_rows_limit,
            n_measurements=payload.max_iterations,
        )
        insert_time_ms_measurements = [
            value / 1_000_000.0 for value in insert_stats["elapsed_ns"]
        ]
        insert_time_ms_percentiles = compute_percentiles(
            insert_time_ms_measurements,
            payload.measured_percentiles,
        )
        insert_rows_per_second_percentiles = compute_percentiles(
            insert_stats["rows_per_second"],
            payload.measured_percentiles,
        )
        insert_bytes_per_second_percentiles = compute_percentiles(
            insert_stats["bytes_per_second"],
            payload.measured_percentiles,
        )

        select_stats = _measure_select_queries(
            client,
            test_queries=baseline_test_queries,
            n_measurements=payload.max_iterations,
        )
        source_select_per_query_metrics = _build_select_per_query_metrics(
            select_stats.get("per_query", []),
            payload.measured_percentiles,
        )

        select_time_ms_measurements = [
            value / 1_000_000.0 for value in select_stats["elapsed_ns"]
        ]
        select_time_ms_percentiles = compute_percentiles(
            select_time_ms_measurements,
            payload.measured_percentiles,
        )
        select_rows_per_second_percentiles = compute_percentiles(
            select_stats["rows_per_second"],
            payload.measured_percentiles,
        )
        select_bytes_per_second_percentiles = compute_percentiles(
            select_stats["bytes_per_second"],
            payload.measured_percentiles,
        )

        source_total_rows = client.count_rows(payload.source_database, payload.source_table)
        tested_total_rows = client.count_rows(baseline_database, baseline_table)
        source_columns_sizes = client.get_column_sizes(payload.source_database, payload.source_table)
        source_indexes_sizes = client.get_index_sizes(payload.source_database, payload.source_table)
        source_total_size_bytes = client.get_total_compressed_size_bytes(
            payload.source_database,
            payload.source_table,
        )
        source_columns_sizes, source_indexes_sizes, source_total_size_bytes = (
            _wait_for_table_size_materialization_if_needed(
                client,
                database=payload.source_database,
                table=payload.source_table,
                column_sizes=source_columns_sizes,
                index_sizes=source_indexes_sizes,
                total_size_bytes=source_total_size_bytes,
            )
        )
        source_total_size_bytes = _normalize_total_size_bytes(
            source_total_size_bytes,
            column_sizes=source_columns_sizes,
            context=f"run_source_benchmark source {payload.source_database}.{payload.source_table}",
        )
        source_parts_metrics = client.get_table_parts_size_metrics(
            payload.source_database,
            payload.source_table,
        )
        source_parts_data_size = _to_positive_finite_float(
            source_parts_metrics.get("data_compressed_bytes")
        )
        if source_parts_data_size > 0:
            source_total_size_bytes = _normalize_total_size_bytes(
                source_parts_data_size,
                column_sizes=source_columns_sizes,
                context=(
                    f"run_source_benchmark source(parts) "
                    f"{payload.source_database}.{payload.source_table}"
                ),
            )

        tested_columns_sizes = client.get_column_sizes(baseline_database, baseline_table)
        tested_indexes_sizes = client.get_index_sizes(baseline_database, baseline_table)
        tested_total_size_bytes = client.get_total_compressed_size_bytes(
            baseline_database,
            baseline_table,
        )
        tested_columns_sizes, tested_indexes_sizes, tested_total_size_bytes = (
            _wait_for_table_size_materialization_if_needed(
                client,
                database=baseline_database,
                table=baseline_table,
                column_sizes=tested_columns_sizes,
                index_sizes=tested_indexes_sizes,
                total_size_bytes=tested_total_size_bytes,
            )
        )
        tested_total_size_bytes = _normalize_total_size_bytes(
            tested_total_size_bytes,
            column_sizes=tested_columns_sizes,
            context=f"run_source_benchmark baseline {baseline_database}.{baseline_table}",
        )
        tested_parts_metrics = client.get_table_parts_size_metrics(
            baseline_database,
            baseline_table,
        )
        tested_parts_data_size = _to_positive_finite_float(
            tested_parts_metrics.get("data_compressed_bytes")
        )
        if tested_parts_data_size > 0:
            tested_total_size_bytes = _normalize_total_size_bytes(
                tested_parts_data_size,
                column_sizes=tested_columns_sizes,
                context=(
                    f"run_source_benchmark baseline(parts) "
                    f"{baseline_database}.{baseline_table}"
                ),
            )
        if tested_total_size_bytes <= 0 and source_total_size_bytes > 0:
            tested_total_size_bytes = source_total_size_bytes
        source_total_size_bytes_with_indexes = _resolve_total_size_with_indexes_bytes(
            parts_metrics=source_parts_metrics,
            normalized_data_size_bytes=source_total_size_bytes,
        )
        tested_total_size_bytes_with_indexes = _resolve_total_size_with_indexes_bytes(
            parts_metrics=tested_parts_metrics,
            normalized_data_size_bytes=tested_total_size_bytes,
        )

        metrics: dict[str, Any] = {
            "measured_percentiles": list(payload.measured_percentiles),
            "insert_test_n_rows": payload.insert_rows_limit,
            "source_table_insert_time_ms_measurements": insert_time_ms_measurements,
            "source_table_insert_time_ms_measurements_percentiles": insert_time_ms_percentiles,
            "source_table_insert_rows_per_second_measurements": insert_stats["rows_per_second"],
            "source_table_insert_rows_per_second_measurements_percentiles": (
                insert_rows_per_second_percentiles
            ),
            "source_table_insert_bytes_per_second_measurements": insert_stats["bytes_per_second"],
            "source_table_insert_bytes_per_second_measurements_percentiles": (
                insert_bytes_per_second_percentiles
            ),
            "source_table_insert_bytes_per_second_measurements_readable": [
                make_readable_bytes(value) for value in insert_stats["bytes_per_second"]
            ],
            "source_table_insert_bytes_per_second_measurements_percentiles_readable": [
                make_readable_bytes(value) for value in insert_bytes_per_second_percentiles
            ],
            "source_table_select_test_query": (
                baseline_test_queries[0].query if baseline_test_queries else ""
            ),
            "source_table_select_time_ms_measurements": select_time_ms_measurements,
            "source_table_select_time_ms_measurements_percentiles": select_time_ms_percentiles,
            "source_table_select_rows_per_second_measurements": select_stats["rows_per_second"],
            "source_table_select_rows_per_second_measurements_percentiles": (
                select_rows_per_second_percentiles
            ),
            "source_table_select_bytes_per_second_measurements": select_stats["bytes_per_second"],
            "source_table_select_bytes_per_second_measurements_percentiles": (
                select_bytes_per_second_percentiles
            ),
            "source_table_select_bytes_per_second_measurements_readable": [
                make_readable_bytes(value) for value in select_stats["bytes_per_second"]
            ],
            "source_table_select_bytes_per_second_measurements_percentiles_readable": [
                make_readable_bytes(value) for value in select_bytes_per_second_percentiles
            ],
            "source_table_select_metrics_by_query": source_select_per_query_metrics,
            "tested_table_consumed_compressed_size_bytes_by_each_column": tested_columns_sizes,
            "source_table_consumed_compressed_size_bytes_by_each_column": source_columns_sizes,
            "tested_table_consumed_compressed_size_bytes_overall": tested_total_size_bytes,
            "tested_table_consumed_compressed_size_bytes_overall_readable": make_readable_bytes(
                tested_total_size_bytes
            ),
            "tested_table_consumed_compressed_size_bytes_with_indexes": tested_total_size_bytes_with_indexes,
            "tested_table_consumed_compressed_size_bytes_with_indexes_readable": make_readable_bytes(
                tested_total_size_bytes_with_indexes
            ),
            # Backward-compatible internal aliases for older runs/tests.
            "tested_table_total_size_bytes_with_indexes": tested_total_size_bytes_with_indexes,
            "tested_table_total_size_bytes_with_indexes_readable": make_readable_bytes(
                tested_total_size_bytes_with_indexes
            ),
            "source_table_consumed_compressed_size_bytes_overall": source_total_size_bytes,
            "source_table_consumed_compressed_size_bytes_overall_readable": make_readable_bytes(
                source_total_size_bytes
            ),
            "source_table_total_size_bytes_with_indexes": source_total_size_bytes_with_indexes,
            "source_table_total_size_bytes_with_indexes_readable": make_readable_bytes(
                source_total_size_bytes_with_indexes
            ),
            "tested_table_n_rows_in_size_test": tested_total_rows,
            "source_table_n_rows_in_size_test": source_total_rows,
            "total_n_rows_in_tested_table": tested_total_rows,
            "total_n_rows_in_source_table": source_total_rows,
        }

        builtin_baseline_score, builtin_baseline_score_details = _compute_builtin_source_score(
            select_time_ms_percentiles=select_time_ms_percentiles,
        )
        _, baseline_geomean_details = _compute_builtin_variant_score(
            source_insert_time_ms_measurements=insert_time_ms_measurements,
            tested_insert_time_ms_measurements=insert_time_ms_measurements,
            source_select_time_ms_measurements=select_time_ms_measurements,
            tested_select_time_ms_measurements=select_time_ms_measurements,
            source_total_size_bytes=source_total_size_bytes_with_indexes,
            tested_total_size_bytes=tested_total_size_bytes_with_indexes,
        )
        source_bucket = _build_metric_bucket(
            measured_percentiles=payload.measured_percentiles,
            time_ms_percentiles=select_time_ms_percentiles,
            rows_per_second_percentiles=select_rows_per_second_percentiles,
            bytes_per_second_percentiles=select_bytes_per_second_percentiles,
        )
        insert_bucket = _build_metric_bucket(
            measured_percentiles=payload.measured_percentiles,
            time_ms_percentiles=insert_time_ms_percentiles,
            rows_per_second_percentiles=insert_rows_per_second_percentiles,
            bytes_per_second_percentiles=insert_bytes_per_second_percentiles,
        )
        baseline_select_time_speedup_by_query = _compute_select_time_speedup_by_query(
            source_select_per_query_metrics,
            source_select_per_query_metrics,
        )
        baseline_per_query_context = _build_per_query_expression_context(
            source_per_query=source_select_per_query_metrics,
            tested_per_query=source_select_per_query_metrics,
            speedup_per_query=baseline_select_time_speedup_by_query,
        )

        baseline_score, baseline_score_calculation_json = _resolve_score(
            scoring=payload.scoring,
            builtin_score=builtin_baseline_score,
            builtin_score_details=builtin_baseline_score_details,
            expression_context={
                "measured_percentiles": list(payload.measured_percentiles),
                "source": {
                    "insert": insert_bucket,
                    "select": source_bucket,
                },
                "tested": {
                    "insert": insert_bucket,
                    "select": source_bucket,
                },
                "speedup": {
                    "insert": {
                        "time_ms_percentiles": compute_speedup_coefficients(
                            insert_time_ms_percentiles,
                            insert_time_ms_percentiles,
                        ),
                        "time_ms_by_percentile": build_percentile_lookup(
                            payload.measured_percentiles,
                            compute_speedup_coefficients(
                                insert_time_ms_percentiles,
                                insert_time_ms_percentiles,
                            ),
                        ),
                    },
                    "select": {
                        "time_ms_percentiles": compute_speedup_coefficients(
                            select_time_ms_percentiles,
                            select_time_ms_percentiles,
                        ),
                        "time_ms_by_percentile": build_percentile_lookup(
                            payload.measured_percentiles,
                            compute_speedup_coefficients(
                                select_time_ms_percentiles,
                                select_time_ms_percentiles,
                            ),
                        ),
                    },
                },
                "compression_overall_coef": (
                    (tested_total_size_bytes / source_total_size_bytes)
                    if source_total_size_bytes > 0
                    else None
                ),
                "ratios": {
                    "insert": baseline_geomean_details.get("inputs", {}).get("insert_ratio"),
                    "select": baseline_geomean_details.get("inputs", {}).get("select_ratio"),
                    "compression": baseline_geomean_details.get("inputs", {}).get(
                        "compression_ratio"
                    ),
                },
                "medians": {
                    "source_insert_time_ms": baseline_geomean_details.get("inputs", {}).get(
                        "source_insert_median_ms"
                    ),
                    "tested_insert_time_ms": baseline_geomean_details.get("inputs", {}).get(
                        "tested_insert_median_ms"
                    ),
                    "source_select_time_ms": baseline_geomean_details.get("inputs", {}).get(
                        "source_select_median_ms"
                    ),
                    "tested_select_time_ms": baseline_geomean_details.get("inputs", {}).get(
                        "tested_select_median_ms"
                    ),
                },
                "source_size_bytes": source_total_size_bytes_with_indexes,
                "tested_size_bytes": tested_total_size_bytes_with_indexes,
                "source_insert_time_ms_percentiles": list(insert_time_ms_percentiles),
                "source_insert_time_ms_by_percentile": build_percentile_lookup(
                    payload.measured_percentiles,
                    insert_time_ms_percentiles,
                ),
                "tested_insert_time_ms_percentiles": list(insert_time_ms_percentiles),
                "tested_insert_time_ms_by_percentile": build_percentile_lookup(
                    payload.measured_percentiles,
                    insert_time_ms_percentiles,
                ),
                "source_select_time_ms_percentiles": list(select_time_ms_percentiles),
                "source_select_time_ms_by_percentile": build_percentile_lookup(
                    payload.measured_percentiles,
                    select_time_ms_percentiles,
                ),
                "tested_select_time_ms_percentiles": list(select_time_ms_percentiles),
                "tested_select_time_ms_by_percentile": build_percentile_lookup(
                    payload.measured_percentiles,
                    select_time_ms_percentiles,
                ),
                "select_time_speedup_by_query": baseline_select_time_speedup_by_query,
                "per_query": baseline_per_query_context,
                "tested_table_select_metrics_by_query_json": baseline_per_query_context.get(
                    "tested_by_query_id", {}
                ),
                "source_table_select_metrics_by_query_json": baseline_per_query_context.get(
                    "source_by_query_id", {}
                ),
                "tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json": (
                    baseline_per_query_context.get("speedup_by_query_id", {})
                ),
            },
            context_label=(
                "run_source_benchmark "
                f"{payload.benchmark_id} {payload.source_database}.{payload.source_table}"
            ),
        )

        source_result = SourceBenchmarkResult(
            benchmark_run_id=payload.benchmark_run_id,
            benchmark_started_at=payload.benchmark_started_at,
            benchmark_id=payload.benchmark_id,
            source_database=payload.source_database,
            source_table=payload.source_table,
            source_table_ddl=payload.source_table_ddl,
            score_calculation_json=baseline_score_calculation_json,
            score=baseline_score,
            metrics=metrics,
        )
        _store_source_benchmark_result_if_configured(
            payload=payload,
            baseline_database=baseline_database,
            baseline_table=baseline_table,
            baseline_ddl=baseline_ddl,
            result=source_result,
        )
        return source_result
    finally:
        try:
            client.drop_table_if_exists(
                baseline_database,
                baseline_table,
                allowed_database=baseline_database,
            )
        except Exception:
            logger.exception(
                "run_source_benchmark: ошибка drop table %s.%s",
                baseline_database,
                baseline_table,
            )
        client.close()


def run_variant_benchmark(
    payload: VariantBenchmarkTaskPayload,
    *,
    celery_task_id: Optional[str] = None,
    celery_worker_hostname: Optional[str] = None,
) -> BenchmarkVariantResult:
    """Реальное выполнение variant benchmark с сохранением результата в ClickHouse."""
    client = _ClickHouseRuntimeClient(payload.connection)
    result_store = ClickHouseBenchmarkResultStore(
        connection=payload.result_connection.to_result_store_params(),
        database=payload.result_database,
        table=payload.result_table,
        legacy_table=payload.result_table_legacy,
        phased_table=payload.result_table_phased,
        phased_runs_table=payload.result_runs_table_phased,
        create_legacy_table=not _is_phased_strategy(payload.benchmark_strategy),
        create_table_if_missing=True,
    )

    source_metrics = _extract_source_metrics(payload.source_benchmark)
    measured_percentiles = list(payload.measured_percentiles)
    if not measured_percentiles:
        measured_percentiles = list(DEFAULT_MEASURED_PERCENTILES)
    insert_tested_cols: list[str] = []
    raw_index_choices = payload.variant_params.get("index_choices")
    if isinstance(raw_index_choices, dict):
        for column_name, index_payload in raw_index_choices.items():
            if index_payload:
                insert_tested_cols.append(str(column_name))

    worker_started_at = datetime.now(timezone.utc)
    try:
        client.create_database_if_not_exists(payload.variant_database)
        client.drop_table_if_exists(
            payload.variant_database,
            payload.variant_table,
            allowed_database=payload.variant_database,
        )
        client.execute(payload.variant_ddl)

        insert_stats = _measure_insert(
            client,
            source_database=payload.source_database,
            source_table=payload.source_table,
            target_database=payload.variant_database,
            target_table=payload.variant_table,
            n_rows=payload.insert_rows_limit,
            n_measurements=payload.max_iterations,
            tested_cols=insert_tested_cols,
        )

        tested_insert_time_ms = [
            value / 1_000_000.0 for value in insert_stats["elapsed_ns"]
        ]
        tested_insert_time_ms_percentiles = compute_percentiles(
            tested_insert_time_ms,
            measured_percentiles,
        )
        tested_insert_rows_per_second_percentiles = compute_percentiles(
            insert_stats["rows_per_second"],
            measured_percentiles,
        )
        tested_insert_bytes_per_second_percentiles = compute_percentiles(
            insert_stats["bytes_per_second"],
            measured_percentiles,
        )

        select_stats = _measure_select_queries(
            client,
            test_queries=payload.query_plan.test_queries,
            n_measurements=payload.max_iterations,
        )
        tested_select_per_query_metrics = _build_select_per_query_metrics(
            select_stats.get("per_query", []),
            measured_percentiles,
        )
        source_select_per_query_metrics = _extract_source_select_per_query_metrics(source_metrics)
        tested_select_time_ms = [
            value / 1_000_000.0 for value in select_stats["elapsed_ns"]
        ]
        tested_select_time_ms_percentiles = compute_percentiles(
            tested_select_time_ms,
            measured_percentiles,
        )
        tested_select_rows_per_second_percentiles = compute_percentiles(
            select_stats["rows_per_second"],
            measured_percentiles,
        )
        tested_select_bytes_per_second_percentiles = compute_percentiles(
            select_stats["bytes_per_second"],
            measured_percentiles,
        )

        tested_rows_count = client.count_rows(payload.variant_database, payload.variant_table)
        source_rows_count = int(source_metrics.get("total_n_rows_in_source_table", 0) or 0)

        tested_columns_sizes = client.get_column_sizes(payload.variant_database, payload.variant_table)
        tested_indexes_sizes = client.get_index_sizes(payload.variant_database, payload.variant_table)
        tested_total_size_bytes = client.get_total_compressed_size_bytes(
            payload.variant_database,
            payload.variant_table,
        )
        tested_columns_sizes, tested_indexes_sizes, tested_total_size_bytes = (
            _wait_for_table_size_materialization_if_needed(
                client,
                database=payload.variant_database,
                table=payload.variant_table,
                column_sizes=tested_columns_sizes,
                index_sizes=tested_indexes_sizes,
                total_size_bytes=tested_total_size_bytes,
            )
        )
        tested_total_size_bytes = _normalize_total_size_bytes(
            tested_total_size_bytes,
            column_sizes=tested_columns_sizes,
            context=f"run_variant_benchmark tested {payload.variant_database}.{payload.variant_table}",
        )
        tested_parts_metrics = client.get_table_parts_size_metrics(
            payload.variant_database,
            payload.variant_table,
        )
        tested_parts_data_size = _to_positive_finite_float(
            tested_parts_metrics.get("data_compressed_bytes")
        )
        if tested_parts_data_size > 0:
            tested_total_size_bytes = _normalize_total_size_bytes(
                tested_parts_data_size,
                column_sizes=tested_columns_sizes,
                context=(
                    f"run_variant_benchmark tested(parts) "
                    f"{payload.variant_database}.{payload.variant_table}"
                ),
            )
        tested_total_size_bytes_with_indexes = _resolve_total_size_with_indexes_bytes(
            parts_metrics=tested_parts_metrics,
            normalized_data_size_bytes=tested_total_size_bytes,
        )
        source_total_size_bytes = float(
            source_metrics.get("source_table_consumed_compressed_size_bytes_overall", 0.0) or 0.0
        )
        source_total_size_bytes = _normalize_total_size_bytes(
            source_total_size_bytes,
            column_sizes=(
                source_metrics.get("source_table_consumed_compressed_size_bytes_by_each_column", {})
                or {}
            ),
            context=f"run_variant_benchmark source-metrics {payload.source_database}.{payload.source_table}",
        )
        source_total_size_bytes_with_indexes = float(
            source_metrics.get("source_table_total_size_bytes_with_indexes", 0.0) or 0.0
        )
        if source_total_size_bytes_with_indexes <= 0 and source_total_size_bytes > 0:
            source_total_size_bytes_with_indexes = source_total_size_bytes

        if source_total_size_bytes <= 0 or source_total_size_bytes_with_indexes <= 0:
            # Защита от редких baseline-анomalies: читаем live size source-таблицы.
            live_source_columns_sizes = client.get_column_sizes(
                payload.source_database,
                payload.source_table,
            )
            live_source_index_sizes = client.get_index_sizes(
                payload.source_database,
                payload.source_table,
            )
            live_source_total_size_bytes = client.get_total_compressed_size_bytes(
                payload.source_database,
                payload.source_table,
            )
            (
                live_source_columns_sizes,
                live_source_index_sizes,
                live_source_total_size_bytes,
            ) = _wait_for_table_size_materialization_if_needed(
                client,
                database=payload.source_database,
                table=payload.source_table,
                column_sizes=live_source_columns_sizes,
                index_sizes=live_source_index_sizes,
                total_size_bytes=live_source_total_size_bytes,
            )
            live_source_total_size_bytes = _normalize_total_size_bytes(
                live_source_total_size_bytes,
                column_sizes=live_source_columns_sizes,
                context=(
                    f"run_variant_benchmark source-live "
                    f"{payload.source_database}.{payload.source_table}"
                ),
            )
            live_source_parts_metrics = client.get_table_parts_size_metrics(
                payload.source_database,
                payload.source_table,
            )
            live_source_parts_data_size = _to_positive_finite_float(
                live_source_parts_metrics.get("data_compressed_bytes")
            )
            if live_source_parts_data_size > 0:
                live_source_total_size_bytes = _normalize_total_size_bytes(
                    live_source_parts_data_size,
                    column_sizes=live_source_columns_sizes,
                    context=(
                        f"run_variant_benchmark source-live(parts) "
                        f"{payload.source_database}.{payload.source_table}"
                    ),
                )
            live_source_total_size_bytes_with_indexes = _resolve_total_size_with_indexes_bytes(
                parts_metrics=live_source_parts_metrics,
                normalized_data_size_bytes=live_source_total_size_bytes,
            )
            if live_source_total_size_bytes > 0:
                source_total_size_bytes = live_source_total_size_bytes
            if live_source_total_size_bytes_with_indexes > 0:
                source_total_size_bytes_with_indexes = live_source_total_size_bytes_with_indexes
        if source_total_size_bytes_with_indexes <= 0 and source_total_size_bytes > 0:
            source_total_size_bytes_with_indexes = source_total_size_bytes

        tested_table_indexes_sizes_percent_from_col_size: dict[str, float] = {}
        for index_name, index_stats in tested_indexes_sizes.items():
            col_stats = tested_columns_sizes.get(index_name)
            if not col_stats:
                continue
            col_size = float(col_stats.get("size_compressed_bytes", 0.0) or 0.0)
            index_size = float(index_stats.get("size_compressed_bytes", 0.0) or 0.0)
            if col_size > 0:
                tested_table_indexes_sizes_percent_from_col_size[index_name] = round(
                    (index_size / col_size) * 100.0,
                    2,
                )

        source_insert_time_ms_percentiles = list(
            source_metrics.get("source_table_insert_time_ms_measurements_percentiles", []) or []
        )
        source_select_time_ms_percentiles = list(
            source_metrics.get("source_table_select_time_ms_measurements_percentiles", []) or []
        )
        tested_insert_time_speedup = compute_speedup_coefficients(
            source_insert_time_ms_percentiles,
            tested_insert_time_ms_percentiles,
        )
        tested_select_time_speedup = compute_speedup_coefficients(
            source_select_time_ms_percentiles,
            tested_select_time_ms_percentiles,
        )
        tested_select_time_speedup_by_query = _compute_select_time_speedup_by_query(
            source_select_per_query_metrics,
            tested_select_per_query_metrics,
        )

        source_columns_size_map: Dict[str, Dict[str, Any]] = dict(
            source_metrics.get("source_table_consumed_compressed_size_bytes_by_each_column", {}) or {}
        )
        compression_by_column_coef: dict[str, float] = {}
        for col_name, tested_col_stats in tested_columns_sizes.items():
            source_col_stats = source_columns_size_map.get(col_name)
            if not source_col_stats:
                continue
            source_bytes = float(source_col_stats.get("size_compressed_bytes", 0.0) or 0.0)
            tested_bytes = float(tested_col_stats.get("size_compressed_bytes", 0.0) or 0.0)
            if tested_bytes > 0:
                compression_by_column_coef[col_name] = round(source_bytes / tested_bytes, 4)

        compression_overall_coef: Optional[float]
        if source_total_size_bytes > 0 and tested_total_size_bytes > 0:
            compression_overall_coef = round(source_total_size_bytes / tested_total_size_bytes, 4)
        else:
            compression_overall_coef = None

        source_insert_bucket = _build_metric_bucket(
            measured_percentiles=measured_percentiles,
            time_ms_percentiles=source_insert_time_ms_percentiles,
            rows_per_second_percentiles=list(
                source_metrics.get("source_table_insert_rows_per_second_measurements_percentiles", [])
                or []
            ),
            bytes_per_second_percentiles=list(
                source_metrics.get("source_table_insert_bytes_per_second_measurements_percentiles", [])
                or []
            ),
        )
        tested_insert_bucket = _build_metric_bucket(
            measured_percentiles=measured_percentiles,
            time_ms_percentiles=tested_insert_time_ms_percentiles,
            rows_per_second_percentiles=tested_insert_rows_per_second_percentiles,
            bytes_per_second_percentiles=tested_insert_bytes_per_second_percentiles,
        )
        source_select_bucket = _build_metric_bucket(
            measured_percentiles=measured_percentiles,
            time_ms_percentiles=source_select_time_ms_percentiles,
            rows_per_second_percentiles=list(
                source_metrics.get("source_table_select_rows_per_second_measurements_percentiles", [])
                or []
            ),
            bytes_per_second_percentiles=list(
                source_metrics.get("source_table_select_bytes_per_second_measurements_percentiles", [])
                or []
            ),
        )
        tested_select_bucket = _build_metric_bucket(
            measured_percentiles=measured_percentiles,
            time_ms_percentiles=tested_select_time_ms_percentiles,
            rows_per_second_percentiles=tested_select_rows_per_second_percentiles,
            bytes_per_second_percentiles=tested_select_bytes_per_second_percentiles,
        )
        insert_speedup_bucket = {
            "time_ms_percentiles": list(tested_insert_time_speedup),
            "time_ms_by_percentile": build_percentile_lookup(
                measured_percentiles,
                tested_insert_time_speedup,
            ),
        }
        select_speedup_bucket = {
            "time_ms_percentiles": list(tested_select_time_speedup),
            "time_ms_by_percentile": build_percentile_lookup(
                measured_percentiles,
                tested_select_time_speedup,
            ),
        }
        # Backward compatibility: старые payload source benchmark могли не нести
        # сырые measurements, а только percentiles.
        source_insert_ms_for_score = list(
            source_metrics.get("source_table_insert_time_ms_measurements", []) or []
        )
        if not source_insert_ms_for_score:
            source_insert_ms_for_score = list(source_insert_time_ms_percentiles)
        source_select_ms_for_score = list(
            source_metrics.get("source_table_select_time_ms_measurements", []) or []
        )
        if not source_select_ms_for_score:
            source_select_ms_for_score = list(source_select_time_ms_percentiles)
        builtin_score, builtin_score_details = _compute_builtin_variant_score(
            source_insert_time_ms_measurements=source_insert_ms_for_score,
            tested_insert_time_ms_measurements=tested_insert_time_ms,
            source_select_time_ms_measurements=source_select_ms_for_score,
            tested_select_time_ms_measurements=tested_select_time_ms,
            source_total_size_bytes=source_total_size_bytes_with_indexes,
            tested_total_size_bytes=tested_total_size_bytes_with_indexes,
        )
        per_query_expression_context = _build_per_query_expression_context(
            source_per_query=source_select_per_query_metrics,
            tested_per_query=tested_select_per_query_metrics,
            speedup_per_query=tested_select_time_speedup_by_query,
        )
        score, score_calculation_json = _resolve_score(
            scoring=payload.scoring,
            builtin_score=builtin_score,
            builtin_score_details=builtin_score_details,
            expression_context={
                "measured_percentiles": list(measured_percentiles),
                "source": {
                    "insert": source_insert_bucket,
                    "select": source_select_bucket,
                },
                "tested": {
                    "insert": tested_insert_bucket,
                    "select": tested_select_bucket,
                },
                "speedup": {
                    "insert": insert_speedup_bucket,
                    "select": select_speedup_bucket,
                    "compression_overall_coef": compression_overall_coef,
                },
                "compression_overall_coef": compression_overall_coef,
                "compression": {
                    "overall_coef": compression_overall_coef,
                },
                "ratios": {
                    "insert": builtin_score_details.get("inputs", {}).get("insert_ratio"),
                    "select": builtin_score_details.get("inputs", {}).get("select_ratio"),
                    "compression": builtin_score_details.get("inputs", {}).get(
                        "compression_ratio"
                    ),
                },
                "medians": {
                    "source_insert_time_ms": builtin_score_details.get("inputs", {}).get(
                        "source_insert_median_ms"
                    ),
                    "tested_insert_time_ms": builtin_score_details.get("inputs", {}).get(
                        "tested_insert_median_ms"
                    ),
                    "source_select_time_ms": builtin_score_details.get("inputs", {}).get(
                        "source_select_median_ms"
                    ),
                    "tested_select_time_ms": builtin_score_details.get("inputs", {}).get(
                        "tested_select_median_ms"
                    ),
                },
                "source_size_bytes": source_total_size_bytes_with_indexes,
                "tested_size_bytes": tested_total_size_bytes_with_indexes,
                "source_insert_time_ms_percentiles": source_insert_bucket[
                    "time_ms_percentiles"
                ],
                "source_insert_time_ms_by_percentile": source_insert_bucket[
                    "time_ms_by_percentile"
                ],
                "tested_insert_time_ms_percentiles": tested_insert_bucket[
                    "time_ms_percentiles"
                ],
                "tested_insert_time_ms_by_percentile": tested_insert_bucket[
                    "time_ms_by_percentile"
                ],
                "insert_time_speedup_percentiles": insert_speedup_bucket[
                    "time_ms_percentiles"
                ],
                "insert_time_speedup_by_percentile": insert_speedup_bucket[
                    "time_ms_by_percentile"
                ],
                "source_select_time_ms_percentiles": source_select_bucket[
                    "time_ms_percentiles"
                ],
                "source_select_time_ms_by_percentile": source_select_bucket[
                    "time_ms_by_percentile"
                ],
                "tested_select_time_ms_percentiles": tested_select_bucket[
                    "time_ms_percentiles"
                ],
                "tested_select_time_ms_by_percentile": tested_select_bucket[
                    "time_ms_by_percentile"
                ],
                "select_time_speedup_percentiles": select_speedup_bucket[
                    "time_ms_percentiles"
                ],
                "select_time_speedup_by_percentile": select_speedup_bucket[
                    "time_ms_by_percentile"
                ],
                "select_time_speedup_by_query": tested_select_time_speedup_by_query,
                "per_query": per_query_expression_context,
                "tested_table_select_metrics_by_query_json": per_query_expression_context.get(
                    "tested_by_query_id", {}
                ),
                "source_table_select_metrics_by_query_json": per_query_expression_context.get(
                    "source_by_query_id", {}
                ),
                "tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json": (
                    per_query_expression_context.get("speedup_by_query_id", {})
                ),
            },
            context_label=(
                "run_variant_benchmark "
                f"{payload.benchmark_id} {payload.source_database}.{payload.source_table} "
                f"{payload.variant_table}"
            ),
        )
        force_score_to_minus_one_reason: Optional[str] = None
        force_score_to_minus_one_status: Optional[str] = None
        if payload.variant_mode == "types" and not compression_by_column_coef:
            force_score_to_minus_one_status = "forced_missing_column_compression_coef"
            force_score_to_minus_one_reason = (
                "tested_table_compression_by_each_column_coef пустой при variant_mode=types; "
                "вариант принудительно помечен score=-1"
            )
        elif payload.variant_mode == "indexes":
            if not tested_indexes_sizes:
                force_score_to_minus_one_status = "forced_missing_tested_table_indexes_sizes"
                force_score_to_minus_one_reason = (
                    "tested_table_indexes_sizes пустой при variant_mode=indexes; "
                    "вариант принудительно помечен score=-1"
                )
            elif not tested_table_indexes_sizes_percent_from_col_size:
                force_score_to_minus_one_status = (
                    "forced_missing_tested_table_indexes_sizes_percent_from_col_size"
                )
                force_score_to_minus_one_reason = (
                    "tested_table_indexes_sizes_percent_from_col_size пустой при "
                    "variant_mode=indexes; вариант принудительно помечен score=-1"
                )

        if force_score_to_minus_one_reason is not None:
            previous_score = score
            previous_score_details: Any = score_calculation_json
            if score_calculation_json:
                try:
                    previous_score_details = json.loads(score_calculation_json)
                except Exception:
                    previous_score_details = score_calculation_json
            score = -1.0
            score_calculation_json = _to_pretty_score_calculation_json(
                {
                    "mode": "forced_fallback",
                    "status": force_score_to_minus_one_status,
                    "reason": force_score_to_minus_one_reason,
                    "previous_score": previous_score,
                    "previous_score_details": previous_score_details,
                    "final_score": score,
                }
            )
            logger.warning(
                "run_variant_benchmark %s %s.%s %s: %s",
                payload.benchmark_id,
                payload.source_database,
                payload.source_table,
                payload.variant_table,
                force_score_to_minus_one_reason,
            )

        execution_uuid = str(payload.variant_params.get("execution_uuid") or "").strip()
        worker_finished_at = datetime.now(timezone.utc)
        result = BenchmarkVariantResult(
            benchmark_run_id=payload.benchmark_run_id,
            benchmark_started_at=payload.benchmark_started_at,
            benchmark_id=payload.benchmark_id,
            source_database=payload.source_database,
            source_table=payload.source_table,
            variant_table=payload.variant_table,
            variant_mode=payload.variant_mode,
            variant_params=dict(payload.variant_params),
            id=execution_uuid or None,
            celery_task_id=(str(celery_task_id).strip() if celery_task_id else None),
            celery_worker_hostname=(
                str(celery_worker_hostname).strip()
                if celery_worker_hostname
                else None
            ),
            worker_started_at=worker_started_at,
            worker_finished_at=worker_finished_at,
            source_table_ddl=(
                payload.source_benchmark.get("source_table_ddl")
                if payload.source_benchmark
                else None
            ),
            tested_table_ddl=payload.variant_ddl,
            is_source_table_copy=False,
            index_params=None,
            total_n_rows_in_tested_table=tested_rows_count,
            total_n_rows_in_source_table=source_rows_count,
            measured_percentiles=measured_percentiles,
            insert_test_n_rows=payload.insert_rows_limit,
            tested_table_insert_time_ms_measurements=tested_insert_time_ms,
            source_table_insert_time_ms_measurements=list(
                source_metrics.get("source_table_insert_time_ms_measurements", []) or []
            ),
            tested_table_insert_time_ms_measurements_percentiles=tested_insert_time_ms_percentiles,
            source_table_insert_time_ms_measurements_percentiles=source_insert_time_ms_percentiles,
            tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs=tested_insert_time_speedup,
            tested_table_insert_rows_per_second_measurements=insert_stats["rows_per_second"],
            source_table_insert_rows_per_second_measurements=list(
                source_metrics.get("source_table_insert_rows_per_second_measurements", []) or []
            ),
            tested_table_insert_rows_per_second_measurements_percentiles=(
                tested_insert_rows_per_second_percentiles
            ),
            source_table_insert_rows_per_second_measurements_percentiles=list(
                source_metrics.get("source_table_insert_rows_per_second_measurements_percentiles", [])
                or []
            ),
            tested_table_insert_bytes_per_second_measurements=insert_stats["bytes_per_second"],
            tested_table_insert_bytes_per_second_measurements_readable=[
                make_readable_bytes(value) for value in insert_stats["bytes_per_second"]
            ],
            source_table_insert_bytes_per_second_measurements=list(
                source_metrics.get("source_table_insert_bytes_per_second_measurements", []) or []
            ),
            source_table_insert_bytes_per_second_measurements_readable=list(
                source_metrics.get("source_table_insert_bytes_per_second_measurements_readable", [])
                or []
            ),
            tested_table_insert_bytes_per_second_measurements_percentiles=(
                tested_insert_bytes_per_second_percentiles
            ),
            tested_table_insert_bytes_per_second_measurements_percentiles_readable=[
                make_readable_bytes(value) for value in tested_insert_bytes_per_second_percentiles
            ],
            source_table_insert_bytes_per_second_measurements_percentiles=list(
                source_metrics.get("source_table_insert_bytes_per_second_measurements_percentiles", [])
                or []
            ),
            source_table_insert_bytes_per_second_measurements_percentiles_readable=list(
                source_metrics.get(
                    "source_table_insert_bytes_per_second_measurements_percentiles_readable",
                    [],
                )
                or []
            ),
            tested_table_select_test_query=(
                payload.query_plan.test_queries[0].query
                if payload.query_plan.test_queries
                else None
            ),
            source_table_select_test_query=(
                source_metrics.get("source_table_select_test_query")
                if source_metrics
                else None
            ),
            tested_table_select_time_ms_measurements=tested_select_time_ms,
            source_table_select_time_ms_measurements=list(
                source_metrics.get("source_table_select_time_ms_measurements", []) or []
            ),
            tested_table_select_time_ms_measurements_percentiles=tested_select_time_ms_percentiles,
            source_table_select_time_ms_measurements_percentiles=source_select_time_ms_percentiles,
            tested_table_select_time_ms_measurements_percentiles_speed_up_coefs=tested_select_time_speedup,
            tested_table_select_rows_per_second_measurements=select_stats["rows_per_second"],
            source_table_select_rows_per_second_measurements=list(
                source_metrics.get("source_table_select_rows_per_second_measurements", []) or []
            ),
            tested_table_select_rows_per_second_measurements_percentiles=(
                tested_select_rows_per_second_percentiles
            ),
            source_table_select_rows_per_second_measurements_percentiles=list(
                source_metrics.get("source_table_select_rows_per_second_measurements_percentiles", [])
                or []
            ),
            tested_table_select_bytes_per_second_measurements=select_stats["bytes_per_second"],
            tested_table_select_bytes_per_second_measurements_readable=[
                make_readable_bytes(value) for value in select_stats["bytes_per_second"]
            ],
            source_table_select_bytes_per_second_measurements=list(
                source_metrics.get("source_table_select_bytes_per_second_measurements", []) or []
            ),
            source_table_select_bytes_per_second_measurements_readable=list(
                source_metrics.get("source_table_select_bytes_per_second_measurements_readable", [])
                or []
            ),
            tested_table_select_bytes_per_second_measurements_percentiles=(
                tested_select_bytes_per_second_percentiles
            ),
            tested_table_select_bytes_per_second_measurements_percentiles_readable=[
                make_readable_bytes(value) for value in tested_select_bytes_per_second_percentiles
            ],
            source_table_select_bytes_per_second_measurements_percentiles=list(
                source_metrics.get("source_table_select_bytes_per_second_measurements_percentiles", [])
                or []
            ),
            source_table_select_bytes_per_second_measurements_percentiles_readable=list(
                source_metrics.get(
                    "source_table_select_bytes_per_second_measurements_percentiles_readable",
                    [],
                )
                or []
            ),
            tested_table_select_metrics_by_query_json=(
                json.dumps(
                    tested_select_per_query_metrics,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                if tested_select_per_query_metrics
                else None
            ),
            source_table_select_metrics_by_query_json=(
                json.dumps(
                    source_select_per_query_metrics,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                if source_select_per_query_metrics
                else None
            ),
            tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json=(
                json.dumps(
                    tested_select_time_speedup_by_query,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                if tested_select_time_speedup_by_query
                else None
            ),
            # Legacy-совместимый формат хранения: человекочитаемый JSON с отступами.
            tested_table_consumed_compressed_size_bytes_by_each_column=json.dumps(
                tested_columns_sizes,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            source_table_consumed_compressed_size_bytes_by_each_column=(
                json.dumps(
                    source_columns_size_map,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                if source_columns_size_map
                else None
            ),
            tested_table_consumed_compressed_size_bytes_overall=tested_total_size_bytes,
            tested_table_consumed_compressed_size_bytes_overall_readable=make_readable_bytes(
                tested_total_size_bytes
            ),
            tested_table_consumed_compressed_size_bytes_with_indexes=tested_total_size_bytes_with_indexes,
            tested_table_consumed_compressed_size_bytes_with_indexes_readable=make_readable_bytes(
                tested_total_size_bytes_with_indexes
            ),
            source_table_consumed_compressed_size_bytes_overall=source_total_size_bytes,
            source_table_consumed_compressed_size_bytes_overall_readable=make_readable_bytes(
                source_total_size_bytes
            ),
            tested_table_compression_overall_coef=compression_overall_coef,
            # Legacy-совместимый формат хранения: человекочитаемый JSON с отступами.
            tested_table_compression_by_each_column_coef=json.dumps(
                compression_by_column_coef,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            source_table_n_rows_in_size_test=int(
                source_metrics.get("source_table_n_rows_in_size_test", 0) or 0
            ),
            tested_table_n_rows_in_size_test=tested_rows_count,
            # Legacy-совместимый формат хранения: человекочитаемый JSON с отступами.
            tested_table_cols_sizes=json.dumps(
                tested_columns_sizes,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            # Legacy-совместимый формат хранения: человекочитаемый JSON с отступами.
            tested_table_indexes_sizes=json.dumps(
                tested_indexes_sizes,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            # Legacy-совместимый формат хранения: человекочитаемый JSON с отступами.
            tested_table_indexes_sizes_percent_from_col_size=json.dumps(
                tested_table_indexes_sizes_percent_from_col_size,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            score_calculation_json=score_calculation_json,
            score=score,
        )

        result_store.store_worker_result(
            benchmark_run_id=payload.benchmark_run_id,
            benchmark_started_at=payload.benchmark_started_at,
            benchmark_id=payload.benchmark_id,
            benchmark_strategy=payload.benchmark_strategy,
            source_database=payload.source_database,
            source_table=payload.source_table,
            variant_table=payload.variant_table,
            variant_mode=payload.variant_mode,
            variant_params=payload.variant_params,
            tested_table_ddl_fallback=payload.variant_ddl,
            source_table_ddl_fallback=(
                payload.source_benchmark.get("source_table_ddl")
                if payload.source_benchmark
                else None
            ),
            result=result,
        )

        return result
    finally:
        try:
            client.drop_table_if_exists(
                payload.variant_database,
                payload.variant_table,
                allowed_database=payload.variant_database,
            )
        except Exception:
            logger.exception(
                "run_variant_benchmark: ошибка drop table %s.%s",
                payload.variant_database,
                payload.variant_table,
            )
        result_store.close()
        client.close()


def _build_default_celery_app():
    """Создаёт default Celery app для worker-процесса."""
    try:
        from celery import Celery
    except ImportError:
        logger.warning("Celery не установлен: worker app не создан")
        return None

    settings = get_clickhouse_celery_worker_settings()
    app = Celery(
        "bench_clickhouse_worker",
        broker=settings.broker_url,
        backend=settings.backend_url,
    )
    app.conf.update(
        worker_concurrency=settings.celery_worker_concurrency,
        # Важный guard: для ignore_result задач ошибки тоже не должны
        # накапливаться в backend (иначе снова растет потребление памяти).
        task_store_errors_even_if_ignored=False,
        # Ограничиваем TTL результатов baseline-задач, которые всё же читаются launcher-ом.
        result_expires=600,
    )
    logger.info(
        "Celery app инициализирован (broker=%s, concurrency=%d)",
        settings.broker_url,
        settings.celery_worker_concurrency,
    )
    return app


app = _build_default_celery_app()


if app is not None:
    try:
        from celery.signals import worker_ready
    except ImportError:  # pragma: no cover - Celery отсутствует.
        worker_ready = None

    if worker_ready is not None:

        @worker_ready.connect
        def _announce_worker_build_info(sender=None, **kwargs):
            """Логирует build metadata при старте Celery worker (как в legacy)."""
            del sender, kwargs
            _log_worker_build_metadata()

    @app.task(name=SOURCE_BENCHMARK_TASK_NAME, ignore_result=False)
    def source_benchmark_task(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Celery task: baseline benchmark исходной таблицы."""
        typed_payload = SourceBenchmarkTaskPayload.model_validate(payload)
        logger.info(
            "Celery worker: старт source task (benchmark_run_id=%d, benchmark_id=%s, table=%s.%s)",
            typed_payload.benchmark_run_id,
            typed_payload.benchmark_id,
            typed_payload.source_database,
            typed_payload.source_table,
        )
        result = run_source_benchmark(typed_payload)
        return result.model_dump(mode="json")


    @app.task(name=VARIANT_BENCHMARK_TASK_NAME, ignore_result=True)
    def variant_benchmark_task(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Celery task: benchmark варианта таблицы + сохранение результата."""
        raw_context = {
            "benchmark_run_id": payload.get("benchmark_run_id"),
            "benchmark_id": payload.get("benchmark_id"),
            "variant_mode": payload.get("variant_mode"),
            "variant_database": payload.get("variant_database"),
            "variant_table": payload.get("variant_table"),
        }

        try:
            typed_payload = VariantBenchmarkTaskPayload.model_validate(payload)
        except Exception as exc:
            # Важный guard: невалидный payload не должен валить pipeline.
            logger.exception(
                "Celery worker: пропуск variant task из-за невалидного payload "
                "(benchmark_run_id=%s, benchmark_id=%s, mode=%s, table=%s.%s)",
                raw_context["benchmark_run_id"],
                raw_context["benchmark_id"],
                raw_context["variant_mode"],
                raw_context["variant_database"],
                raw_context["variant_table"],
            )
            return {
                "status": "skipped_invalid_variant_payload",
                "error": str(exc),
                **raw_context,
            }

        logger.info(
            "Celery worker: старт variant task "
            "(benchmark_run_id=%d, benchmark_id=%s, mode=%s, table=%s.%s)",
            typed_payload.benchmark_run_id,
            typed_payload.benchmark_id,
            typed_payload.variant_mode,
            typed_payload.variant_database,
            typed_payload.variant_table,
        )

        try:
            celery_task_id: Optional[str] = None
            celery_worker_hostname: Optional[str] = None
            try:
                request = getattr(variant_benchmark_task, "request", None)
                if request is not None:
                    celery_task_id = str(getattr(request, "id", "") or "").strip() or None
                    celery_worker_hostname = (
                        str(getattr(request, "hostname", "") or "").strip() or None
                    )
            except Exception:
                celery_task_id = None
                celery_worker_hostname = None

            result = run_variant_benchmark(
                typed_payload,
                celery_task_id=celery_task_id,
                celery_worker_hostname=celery_worker_hostname,
            )
        except Exception as exc:
            # Важный guard: невалидный/ошибочный вариант считается пропущенным,
            # чтобы общий benchmark не зависал и progress учитывал задачу.
            logger.exception(
                "Celery worker: пропуск variant task из-за ошибки выполнения "
                "(benchmark_run_id=%d, benchmark_id=%s, mode=%s, table=%s.%s)",
                typed_payload.benchmark_run_id,
                typed_payload.benchmark_id,
                typed_payload.variant_mode,
                typed_payload.variant_database,
                typed_payload.variant_table,
            )
            return {
                "status": "skipped_invalid_variant",
                "error": str(exc),
                "benchmark_run_id": typed_payload.benchmark_run_id,
                "benchmark_id": typed_payload.benchmark_id,
                "variant_mode": typed_payload.variant_mode,
                "variant_database": typed_payload.variant_database,
                "variant_table": typed_payload.variant_table,
            }

        return result.model_dump(mode="json")
