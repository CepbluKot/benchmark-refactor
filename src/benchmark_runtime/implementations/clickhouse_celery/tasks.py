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
from hashlib import sha256
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
_OPTIMIZE_FINAL_WAIT_TIMEOUT_SEC = float(
    os.getenv("BENCH_OPTIMIZE_FINAL_WAIT_TIMEOUT_SEC", "600.0")
)
_OPTIMIZE_FINAL_WAIT_POLL_SEC = float(
    os.getenv("BENCH_OPTIMIZE_FINAL_WAIT_POLL_SEC", "1.0")
)
_ENABLE_OPTIMIZE_FINAL = str(os.getenv("BENCH_ENABLE_OPTIMIZE_FINAL", "1")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_QUERY_LOG_METRICS_POLL_ATTEMPTS = max(
    1,
    int(os.getenv("BENCH_QUERY_LOG_METRICS_POLL_ATTEMPTS", "5")),
)
_QUERY_LOG_METRICS_POLL_SLEEP_SEC = max(
    0.0,
    float(os.getenv("BENCH_QUERY_LOG_METRICS_POLL_SLEEP_SEC", "0.2")),
)
_QUERY_LOG_METRICS_POLL_TOTAL_WAIT_SEC = max(
    0.0,
    float(os.getenv("BENCH_QUERY_LOG_METRICS_POLL_TOTAL_WAIT_SEC", "15.0")),
)
_OPTIMIZE_FINAL_PERMISSION_DENIED = False


def _is_optimize_access_denied(exc: Exception) -> bool:
    """Определяет ошибку отсутствия прав на OPTIMIZE."""
    message = str(exc or "").lower()
    return "access_denied" in message or "not enough privileges" in message


def _is_nullable_sorting_key_error(exc: Exception) -> bool:
    """Определяет ошибку ClickHouse `ILLEGAL_COLUMN` для Nullable в ORDER BY."""
    message = str(exc or "").lower()
    if "sorting key contains nullable columns" not in message:
        return False
    return ("code: 44" in message) or ("illegal_column" in message)


def _is_memory_limit_exceeded_error(exc: Exception) -> bool:
    """Определяет ошибку ClickHouse `MEMORY_LIMIT_EXCEEDED`."""
    message = str(exc or "").lower()
    if "memory limit" not in message and "memory_limit_exceeded" not in message:
        return False
    return ("code: 241" in message) or ("memory_limit_exceeded" in message)


def _ensure_allow_nullable_key_in_ddl(ddl_sql: str) -> str:
    """
    Гарантирует `allow_nullable_key = 1` в SETTINGS CREATE TABLE DDL.

    Используется как fallback для старых версий ClickHouse, где ORDER BY
    с Nullable-колонками запрещён по умолчанию.
    """
    parsed = TableDDL.from_ddl(ddl_sql)
    settings_indices = [
        idx
        for idx, option in enumerate(parsed.other_table_options)
        if re.match(r"^\s*SETTINGS\b", option, flags=re.IGNORECASE)
    ]
    if not settings_indices:
        parsed.other_table_options.append("SETTINGS allow_nullable_key = 1")
        return parsed.to_ddl()

    settings_idx = settings_indices[0]
    option = parsed.other_table_options[settings_idx]
    settings_body = re.sub(
        r"^\s*SETTINGS\b",
        "",
        option,
        flags=re.IGNORECASE,
    ).strip()
    assignments = [
        item.strip()
        for item in TableDDL._split_top_level_commas(settings_body)
        if item.strip()
    ]
    normalized_assignments: list[str] = []
    has_allow_nullable_key = False
    for assignment in assignments:
        if re.match(r"^\s*`?allow_nullable_key`?\s*=", assignment, flags=re.IGNORECASE):
            normalized_assignments.append("allow_nullable_key = 1")
            has_allow_nullable_key = True
            continue
        normalized_assignments.append(assignment)
    if not has_allow_nullable_key:
        normalized_assignments.append("allow_nullable_key = 1")
    parsed.other_table_options[settings_idx] = (
        "SETTINGS " + ", ".join(normalized_assignments)
    )
    return parsed.to_ddl()


def _should_run_optimize_final() -> bool:
    """
    Возвращает, нужно ли запускать OPTIMIZE FINAL в текущем worker-процессе.

    OPTIMIZE может быть отключён:
      - через BENCH_ENABLE_OPTIMIZE_FINAL=0;
      - автоматически после первой ACCESS_DENIED ошибки.
    """
    return _ENABLE_OPTIMIZE_FINAL and not _OPTIMIZE_FINAL_PERMISSION_DENIED


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


def _extract_base_identifier(token: str) -> str:
    """Возвращает имя идентификатора без бэктиков и префикса `db.`."""
    cleaned = str(token or "").strip().strip("`").strip()
    if "." in cleaned:
        cleaned = cleaned.rsplit(".", 1)[-1]
    return cleaned.strip().strip("`")


def _extract_index_column_from_expr(expr: Any) -> Optional[str]:
    """
    Пытается извлечь имя колонки из `expr` skip-индекса.

    Поддерживает частые формы:
      - `country`
      - `` `country` ``
      - `db.country`
      - `lowerUTF8(message)`
      - `tokenbf_v1(message, ...)`
    """
    text = str(expr or "").strip()
    if not text:
        return None

    direct_match = re.fullmatch(
        r"(?:`?[A-Za-z_][A-Za-z0-9_]*`?\.)*`?([A-Za-z_][A-Za-z0-9_]*)`?",
        text,
    )
    if direct_match:
        return _extract_base_identifier(direct_match.group(1))

    backtick_identifiers = re.findall(r"`([^`]+)`", text)
    if backtick_identifiers:
        return _extract_base_identifier(backtick_identifiers[-1])

    bare_identifiers = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)
    if not bare_identifiers:
        return None
    reserved = {
        "AND",
        "OR",
        "NOT",
        "NULL",
        "TRUE",
        "FALSE",
        "AS",
        "CAST",
        "LOWER",
        "UPPER",
        "LOWERUTF8",
        "UPPERUTF8",
        "TOKENBF_V1",
        "NGRAMBF_V1",
        "BLOOM_FILTER",
        "SET",
        "MINMAX",
    }
    for token in reversed(bare_identifiers):
        if token.upper() in reserved:
            continue
        candidate = _extract_base_identifier(token)
        if candidate:
            return candidate
    return None


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


def _filter_non_negative_finite_measurements(
    values: Sequence[float],
    *,
    metric_name: str,
    context: str,
) -> List[float]:
    """Оставляет только валидные замеры (>= 0 и конечные)."""
    cleaned: list[float] = []
    dropped = 0
    for value in values:
        try:
            numeric = float(value)
        except Exception:
            dropped += 1
            continue
        if math.isfinite(numeric) and numeric >= 0:
            cleaned.append(numeric)
        else:
            dropped += 1

    if dropped > 0:
        logger.warning(
            "%s: отброшено %d невалидных замеров `%s` (< 0/NaN/Inf)",
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


def _median_positive_finite(values: Sequence[Any]) -> Optional[float]:
    """Считает медиану по валидным значениям (>0, finite)."""
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


def _median_from_measurements_or_percentiles(
    measurements: Sequence[Any],
    percentiles: Sequence[Any],
) -> Optional[float]:
    """Берёт медиану из measurements, при их отсутствии fallback на percentiles."""
    direct = _median_positive_finite(measurements)
    if direct is not None:
        return direct
    return _median_positive_finite(percentiles)


def _build_score_context_medians(
    *,
    source_insert_time_ms: Sequence[Any],
    tested_insert_time_ms: Sequence[Any],
    source_select_time_ms: Sequence[Any],
    tested_select_time_ms: Sequence[Any],
    source_insert_rows_per_second: Sequence[Any],
    tested_insert_rows_per_second: Sequence[Any],
    source_select_rows_per_second: Sequence[Any],
    tested_select_rows_per_second: Sequence[Any],
    source_insert_bytes_per_second: Sequence[Any],
    tested_insert_bytes_per_second: Sequence[Any],
    source_select_bytes_per_second: Sequence[Any],
    tested_select_bytes_per_second: Sequence[Any],
    insert_time_speedup: Sequence[Any],
    select_time_speedup: Sequence[Any],
    source_per_query: Sequence[Dict[str, Any]],
    tested_per_query: Sequence[Dict[str, Any]],
    speedup_per_query: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Собирает медианы всех ключевых метрик для score_calculation_json."""

    def _collect_values(entries: Sequence[Dict[str, Any]], key: str) -> list[Any]:
        values: list[Any] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            raw_values = entry.get(key, [])
            if isinstance(raw_values, Sequence) and not isinstance(
                raw_values, (str, bytes, bytearray)
            ):
                values.extend(list(raw_values))
        return values

    def _query_id(entry: Dict[str, Any], fallback_index: int) -> str:
        raw_id = str(entry.get("query_id", "")).strip()
        if raw_id:
            return raw_id
        try:
            idx = int(entry.get("query_index", fallback_index))
        except Exception:
            idx = fallback_index
        return f"query_{idx}"

    def _entry_map(entries: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        mapped: Dict[str, Dict[str, Any]] = {}
        for fallback_index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            mapped[_query_id(entry, fallback_index)] = entry
        return mapped

    source_by_query_id = _entry_map(source_per_query)
    tested_by_query_id = _entry_map(tested_per_query)
    speedup_by_query_id = _entry_map(speedup_per_query)

    source_select_read_bytes = _median_from_measurements_or_percentiles(
        _collect_values(source_per_query, "read_bytes_measurements"),
        _collect_values(source_per_query, "read_bytes_percentiles"),
    )
    tested_select_read_bytes = _median_from_measurements_or_percentiles(
        _collect_values(tested_per_query, "read_bytes_measurements"),
        _collect_values(tested_per_query, "read_bytes_percentiles"),
    )
    select_read_bytes_speedup: Optional[float] = None
    try:
        source_rb = float(source_select_read_bytes) if source_select_read_bytes is not None else None
        tested_rb = float(tested_select_read_bytes) if tested_select_read_bytes is not None else None
        if (
            source_rb is not None
            and tested_rb is not None
            and math.isfinite(source_rb)
            and math.isfinite(tested_rb)
            and source_rb > 0
            and tested_rb > 0
        ):
            select_read_bytes_speedup = source_rb / tested_rb
            if not math.isfinite(select_read_bytes_speedup) or select_read_bytes_speedup <= 0:
                select_read_bytes_speedup = None
    except Exception:
        select_read_bytes_speedup = None

    ordered_query_ids: list[str] = []
    seen_query_ids: set[str] = set()
    for entries in (source_per_query, tested_per_query, speedup_per_query):
        for fallback_index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            query_id = _query_id(entry, fallback_index)
            if query_id in seen_query_ids:
                continue
            seen_query_ids.add(query_id)
            ordered_query_ids.append(query_id)

    per_query_medians: Dict[str, Dict[str, Any]] = {}
    for query_id in ordered_query_ids:
        source_entry = source_by_query_id.get(query_id, {})
        tested_entry = tested_by_query_id.get(query_id, {})
        speedup_entry = speedup_by_query_id.get(query_id, {})

        source_elapsed_ms = _median_from_measurements_or_percentiles(
            source_entry.get("elapsed_ms_measurements", []) or [],
            source_entry.get("elapsed_ms_percentiles", []) or [],
        )
        tested_elapsed_ms = _median_from_measurements_or_percentiles(
            tested_entry.get("elapsed_ms_measurements", []) or [],
            tested_entry.get("elapsed_ms_percentiles", []) or [],
        )
        elapsed_ms_speedup = _median_from_measurements_or_percentiles(
            speedup_entry.get("elapsed_ms_measurements_speed_up_coefs", []) or [],
            speedup_entry.get("elapsed_ms_percentiles_speed_up_coefs", []) or [],
        )
        source_rows_per_second = _median_from_measurements_or_percentiles(
            source_entry.get("rows_per_second_measurements", []) or [],
            source_entry.get("rows_per_second_percentiles", []) or [],
        )
        tested_rows_per_second = _median_from_measurements_or_percentiles(
            tested_entry.get("rows_per_second_measurements", []) or [],
            tested_entry.get("rows_per_second_percentiles", []) or [],
        )
        source_bytes_per_second = _median_from_measurements_or_percentiles(
            source_entry.get("bytes_per_second_measurements", []) or [],
            source_entry.get("bytes_per_second_percentiles", []) or [],
        )
        tested_bytes_per_second = _median_from_measurements_or_percentiles(
            tested_entry.get("bytes_per_second_measurements", []) or [],
            tested_entry.get("bytes_per_second_percentiles", []) or [],
        )
        source_read_bytes = _median_from_measurements_or_percentiles(
            source_entry.get("read_bytes_measurements", []) or [],
            source_entry.get("read_bytes_percentiles", []) or [],
        )
        tested_read_bytes = _median_from_measurements_or_percentiles(
            tested_entry.get("read_bytes_measurements", []) or [],
            tested_entry.get("read_bytes_percentiles", []) or [],
        )

        per_query_medians[query_id] = {
            "source_elapsed_ms": source_elapsed_ms,
            "tested_elapsed_ms": tested_elapsed_ms,
            "elapsed_ms_speedup": elapsed_ms_speedup,
            "source_rows_per_second": source_rows_per_second,
            "tested_rows_per_second": tested_rows_per_second,
            "source_bytes_per_second": source_bytes_per_second,
            "source_bytes_per_second_readable": (
                make_readable_bytes(source_bytes_per_second)
                if source_bytes_per_second is not None
                else None
            ),
            "tested_bytes_per_second": tested_bytes_per_second,
            "tested_bytes_per_second_readable": (
                make_readable_bytes(tested_bytes_per_second)
                if tested_bytes_per_second is not None
                else None
            ),
            "source_read_bytes": source_read_bytes,
            "source_read_bytes_readable": (
                make_readable_bytes(source_read_bytes)
                if source_read_bytes is not None
                else None
            ),
            "tested_read_bytes": tested_read_bytes,
            "tested_read_bytes_readable": (
                make_readable_bytes(tested_read_bytes)
                if tested_read_bytes is not None
                else None
            ),
        }

    source_insert_bytes_per_second_median = _median_positive_finite(
        source_insert_bytes_per_second
    )
    tested_insert_bytes_per_second_median = _median_positive_finite(
        tested_insert_bytes_per_second
    )
    source_select_bytes_per_second_median = _median_positive_finite(
        source_select_bytes_per_second
    )
    tested_select_bytes_per_second_median = _median_positive_finite(
        tested_select_bytes_per_second
    )

    return {
        "source_insert_time_ms": _median_positive_finite(source_insert_time_ms),
        "tested_insert_time_ms": _median_positive_finite(tested_insert_time_ms),
        "source_select_time_ms": _median_positive_finite(source_select_time_ms),
        "tested_select_time_ms": _median_positive_finite(tested_select_time_ms),
        "source_insert_rows_per_second": _median_positive_finite(
            source_insert_rows_per_second
        ),
        "tested_insert_rows_per_second": _median_positive_finite(
            tested_insert_rows_per_second
        ),
        "source_select_rows_per_second": _median_positive_finite(
            source_select_rows_per_second
        ),
        "tested_select_rows_per_second": _median_positive_finite(
            tested_select_rows_per_second
        ),
        "source_insert_bytes_per_second": source_insert_bytes_per_second_median,
        "source_insert_bytes_per_second_readable": (
            make_readable_bytes(source_insert_bytes_per_second_median)
            if source_insert_bytes_per_second_median is not None
            else None
        ),
        "tested_insert_bytes_per_second": tested_insert_bytes_per_second_median,
        "tested_insert_bytes_per_second_readable": (
            make_readable_bytes(tested_insert_bytes_per_second_median)
            if tested_insert_bytes_per_second_median is not None
            else None
        ),
        "source_select_bytes_per_second": source_select_bytes_per_second_median,
        "source_select_bytes_per_second_readable": (
            make_readable_bytes(source_select_bytes_per_second_median)
            if source_select_bytes_per_second_median is not None
            else None
        ),
        "source_select_read_bytes": source_select_read_bytes,
        "source_select_read_bytes_readable": (
            make_readable_bytes(source_select_read_bytes)
            if source_select_read_bytes is not None
            else None
        ),
        "tested_select_bytes_per_second": tested_select_bytes_per_second_median,
        "tested_select_bytes_per_second_readable": (
            make_readable_bytes(tested_select_bytes_per_second_median)
            if tested_select_bytes_per_second_median is not None
            else None
        ),
        "tested_select_read_bytes": tested_select_read_bytes,
        "tested_select_read_bytes_readable": (
            make_readable_bytes(tested_select_read_bytes)
            if tested_select_read_bytes is not None
            else None
        ),
        "insert_time_speedup": _median_positive_finite(insert_time_speedup),
        "select_time_speedup": _median_positive_finite(select_time_speedup),
        "select_read_bytes_speedup": select_read_bytes_speedup,
        "per_query": per_query_medians,
    }


def _compute_variant_ratio_details(
    *,
    source_insert_time_ms_measurements: Sequence[float],
    tested_insert_time_ms_measurements: Sequence[float],
    source_select_time_ms_measurements: Sequence[float],
    tested_select_time_ms_measurements: Sequence[float],
    source_total_size_bytes: Optional[float],
    tested_total_size_bytes: Optional[float],
) -> tuple[Optional[float], Dict[str, Any]]:
    """
    Вычисляет ratio-детали и геометрическое среднее для контекста формулы score.

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
                "Не удалось вычислить ratio-детали: нужны валидные медианы "
                "insert/select и валидные размеры source/tested"
            )
        ),
    }
    return score, details


def _resolve_score(
    *,
    scoring: ScoringConfig,
    stage_name: Optional[str],
    expression_context: Dict[str, Any],
    context_label: str,
) -> tuple[Optional[float], str]:
    """
    Вычисляет итоговый score по конфигу scoring.

    Всегда вычисляет безопасное expression (expression-only режим).
    """
    stage_override = scoring.stage_override(stage_name)
    effective_expression = (
        stage_override.expression if stage_override is not None else scoring.expression
    )
    effective_on_error_score = (
        stage_override.on_error_score
        if stage_override is not None and stage_override.on_error_score is not None
        else scoring.on_error_score
    )
    effective_top_selection = (
        stage_override.top_selection
        if stage_override is not None
        else scoring.top_selection
    )
    effective_variables = (
        stage_override.variables
        if stage_override is not None and stage_override.variables is not None
        else scoring.variables
    )

    resolved_variables: Dict[str, float] = {}
    resolved_variables_details: Dict[str, Dict[str, Any]] = {}
    for variable_name, variable_expression in (effective_variables or {}).items():
        variable_context: Dict[str, Any] = {
            **expression_context,
            **resolved_variables,
        }
        try:
            variable_value = evaluate_score_expression(
                variable_expression,
                variable_context,
            )
        except ScoreEvaluationError as exc:
            logger.warning(
                "%s: ошибка вычисления scoring.variables.%s: %s",
                context_label,
                variable_name,
                exc,
            )
            base_details_with_variables: Dict[str, Any] = {
                "mode": "expression",
                "expression": effective_expression,
                "on_error_score": effective_on_error_score,
                "stage_name": stage_name,
                "stage_override_used": stage_override is not None,
                "variables": effective_variables or {},
                "resolved_variables": resolved_variables_details,
                "context": expression_context,
            }
            if effective_on_error_score is not None:
                fallback_score = float(effective_on_error_score)
                return fallback_score, _to_pretty_score_calculation_json(
                    {
                        **base_details_with_variables,
                        "status": "fallback_on_variable_error",
                        "error": str(exc),
                        "error_variable": variable_name,
                        "final_score": fallback_score,
                    }
                )
            return None, _to_pretty_score_calculation_json(
                {
                    **base_details_with_variables,
                    "status": "variable_error",
                    "error": str(exc),
                    "error_variable": variable_name,
                    "final_score": None,
                }
            )
        resolved_variable_value = float(variable_value)
        resolved_variables[variable_name] = resolved_variable_value
        resolved_variables_details[variable_name] = {
            "expression": variable_expression,
            "value": resolved_variable_value,
        }

    final_expression_context: Dict[str, Any] = {
        **expression_context,
        **resolved_variables,
    }

    base_details: Dict[str, Any] = {
        "mode": "expression",
        "expression": effective_expression,
        "top_selection": effective_top_selection,
        "on_error_score": effective_on_error_score,
        "stage_name": stage_name,
        "stage_override_used": stage_override is not None,
        "variables": effective_variables or {},
        "resolved_variables": resolved_variables_details,
        "context": expression_context,
    }

    try:
        score = evaluate_score_expression(
            effective_expression or "",
            final_expression_context,
        )
    except ScoreEvaluationError as exc:
        logger.warning(
            "%s: ошибка вычисления scoring.expression: %s",
            context_label,
            exc,
        )
        if effective_on_error_score is not None:
            fallback_score = float(effective_on_error_score)
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
        if effective_on_error_score is not None:
            fallback_score = float(effective_on_error_score)
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
    query_type: Literal["hit", "miss", "manual", "generic"] = "generic"
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
    insert_operations_count: int
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

    insert_operations_count: int
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
        self._stream_copy_disabled = False
        self._stream_copy_failure_count = 0
        self._stream_copy_disable_after_failures = (
            worker_settings.clickhouse_stream_copy_disable_after_failures
        )
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

    def optimize_table_final(self, database: str, table: str) -> None:
        """Принудительно схлопывает парты перед SELECT-замерами."""
        self.execute(f"OPTIMIZE TABLE `{database}`.`{table}` FINAL")

    def wait_for_no_active_merges(
        self,
        database: str,
        table: str,
        *,
        timeout_sec: float = _OPTIMIZE_FINAL_WAIT_TIMEOUT_SEC,
        poll_sec: float = _OPTIMIZE_FINAL_WAIT_POLL_SEC,
    ) -> bool:
        """
        Ждёт завершения merge-процессов по таблице.

        Возвращает:
          - True: merges завершились;
          - False: timeout.
        """
        deadline = time.monotonic() + max(0.0, float(timeout_sec))
        sleep_sec = max(0.0, float(poll_sec))
        while True:
            rows = self.execute(
                """
                SELECT count()
                FROM system.merges
                WHERE database = %(database)s
                  AND table = %(table)s
                """,
                {"database": database, "table": table},
            )
            active_merges = 0
            if rows:
                try:
                    active_merges = int(rows[0][0] or 0)
                except Exception:
                    active_merges = 0
            if active_merges <= 0:
                return True
            if time.monotonic() >= deadline:
                return False
            if sleep_sec > 0:
                time.sleep(sleep_sec)

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
        params = {"database": database, "table": table}
        rows: list[Any] = []
        last_error: Optional[Exception] = None
        used_query_label: str = ""

        # Порядок: сначала строгие варианты с active=1; затем fallback без active.
        query_candidates: list[tuple[str, str]] = [
            (
                "active_direct_named",
                """
                SELECT
                    name,
                    expr,
                    data_compressed_bytes
                FROM system.data_skipping_indices
                WHERE database = %(database)s
                  AND table = %(table)s
                  AND active = 1
                """,
            ),
            (
                "active_direct_expr",
                """
                SELECT
                    expr,
                    data_compressed_bytes
                FROM system.data_skipping_indices
                WHERE database = %(database)s
                  AND table = %(table)s
                  AND active = 1
                """,
            ),
            (
                "active_join_part_name_named",
                """
                SELECT
                    d.name,
                    d.expr,
                    d.data_compressed_bytes
                FROM system.data_skipping_indices AS d
                INNER JOIN system.parts AS p
                    ON p.database = d.database
                   AND p.table = d.table
                   AND p.name = d.part_name
                WHERE d.database = %(database)s
                  AND d.table = %(table)s
                  AND p.active = 1
                """,
            ),
            (
                "active_join_part_name_expr",
                """
                SELECT
                    d.expr,
                    d.data_compressed_bytes
                FROM system.data_skipping_indices AS d
                INNER JOIN system.parts AS p
                    ON p.database = d.database
                   AND p.table = d.table
                   AND p.name = d.part_name
                WHERE d.database = %(database)s
                  AND d.table = %(table)s
                  AND p.active = 1
                """,
            ),
            (
                "active_join_part_named",
                """
                SELECT
                    d.name,
                    d.expr,
                    d.data_compressed_bytes
                FROM system.data_skipping_indices AS d
                INNER JOIN system.parts AS p
                    ON p.database = d.database
                   AND p.table = d.table
                   AND p.name = d.part
                WHERE d.database = %(database)s
                  AND d.table = %(table)s
                  AND p.active = 1
                """,
            ),
            (
                "active_join_part_expr",
                """
                SELECT
                    d.expr,
                    d.data_compressed_bytes
                FROM system.data_skipping_indices AS d
                INNER JOIN system.parts AS p
                    ON p.database = d.database
                   AND p.table = d.table
                   AND p.name = d.part
                WHERE d.database = %(database)s
                  AND d.table = %(table)s
                  AND p.active = 1
                """,
            ),
            # Последний fallback (когда active-filter технически недоступен в этой версии CH).
            (
                "no_active_named",
                """
                SELECT
                    name,
                    expr,
                    data_compressed_bytes
                FROM system.data_skipping_indices
                WHERE database = %(database)s
                  AND table = %(table)s
                """,
            ),
            (
                "no_active_expr",
                """
                SELECT
                    expr,
                    data_compressed_bytes
                FROM system.data_skipping_indices
                WHERE database = %(database)s
                  AND table = %(table)s
                """,
            ),
        ]

        for query_label, query_text in query_candidates:
            try:
                rows = self.execute(query_text, params)
                used_query_label = query_label
                break
            except Exception as exc:
                last_error = exc
                continue
        else:
            if last_error is not None:
                logger.error(
                    "Не удалось получить размеры skip-индексов для %s.%s: %s",
                    database,
                    table,
                    last_error,
                )
            else:
                logger.error(
                    "Не удалось получить размеры skip-индексов для %s.%s",
                    database,
                    table,
                )
            rows = []

        if used_query_label.startswith("no_active_"):
            logger.warning(
                "Размеры skip-индексов для %s.%s получены без active=1 "
                "(в этой версии CH active-filter недоступен для system.data_skipping_indices)",
                database,
                table,
            )

        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, (list, tuple)):
                continue
            if len(row) >= 3:
                raw_name, raw_expr, compressed_bytes = row[0], row[1], row[2]
            elif len(row) >= 2:
                raw_name, raw_expr, compressed_bytes = row[0], row[0], row[1]
            else:
                continue

            index_name = str(raw_name or "").strip()
            expr = str(raw_expr or "").strip()
            if not index_name:
                index_name = expr

            bytes_value = int(compressed_bytes or 0)
            column_name = _extract_index_column_from_expr(expr) or _extract_index_column_from_expr(
                index_name
            )

            existing = result.get(index_name)
            if existing is None:
                result[index_name] = {
                    "expr": expr or None,
                    "column": column_name,
                    "size_compressed_bytes": bytes_value,
                }
                continue

            existing["size_compressed_bytes"] = int(
                existing.get("size_compressed_bytes", 0) or 0
            ) + bytes_value
            if expr and not existing.get("expr"):
                existing["expr"] = expr
            if column_name and not existing.get("column"):
                existing["column"] = column_name

        for stats in result.values():
            bytes_value = int(stats.get("size_compressed_bytes", 0) or 0)
            stats["size_compressed_bytes_readable"] = make_readable_bytes(bytes_value)
        return result

    @staticmethod
    def _build_tagged_query(query: str, query_tag: Optional[str]) -> str:
        """Добавляет комментарий-тег к SQL, чтобы запрос проще находился в логах."""
        if not query_tag:
            return query
        return f"/* bench_qid:{query_tag} */ {query}"

    @staticmethod
    def _build_query_id(
        query_tag: Optional[str],
        *,
        suffix: str,
    ) -> str:
        """Строит детерминированный query_id для поиска метрик в system.query_log."""
        raw_tag = str(query_tag or "").strip() or uuid.uuid4().hex
        normalized_tag = re.sub(r"[^0-9A-Za-z_.:-]+", "_", raw_tag).strip("_")
        if not normalized_tag:
            normalized_tag = uuid.uuid4().hex
        normalized_suffix = re.sub(r"[^0-9A-Za-z_.:-]+", "_", str(suffix or "q")).strip("_")
        if not normalized_suffix:
            normalized_suffix = "q"
        query_id = f"bench_{normalized_suffix}_{normalized_tag}"
        if len(query_id) > 120:
            query_id = query_id[:120]
        return query_id

    def _execute_command_with_summary_metrics(
        self,
        query: str,
        *,
        query_tag: Optional[str] = None,
        raise_on_execute_error: bool = False,
    ) -> Dict[str, float]:
        """
        Выполняет SQL через `command` и достаёт метрики из `system.query_log`.
        """
        query_id = self._build_query_id(query_tag, suffix="cmd")
        tagged_query = self._build_tagged_query(query, query_tag)
        try:
            self._client.command(
                tagged_query,
                settings={"query_id": query_id},
            )
        except Exception:
            logger.exception("Не удалось выполнить command SQL для query_log-метрик")
            if raise_on_execute_error:
                raise
            return _error_query_metrics()

        query_log_metrics = self._query_log_metrics_by_query_id(query_id=query_id)
        if query_log_metrics is not None:
            return query_log_metrics

        logger.warning(
            "SQL выполнен, но метрики в system.query_log не найдены "
            "(query_id=%s, ожидаем type='QueryFinish')",
            query_id,
        )
        return _error_query_metrics()

    def execute_select_with_metrics(
        self,
        query: str,
        *,
        query_tag: str,
    ) -> Dict[str, float]:
        """
        Выполняет SELECT и возвращает метрики только из `system.query_log`.

        Приоритет:
        1) `stream_client.command(...)`;
        2) `stream_client.query(...)`;
        3) `self._client.query(...)`.
        """
        _validate_user_read_only_sql_input(query)
        tagged_query = self._build_tagged_query(query, query_tag)

        stream_client = self._get_stream_client()
        if stream_client is not None:
            stream_command_query_id = self._build_query_id(
                query_tag,
                suffix="sel_stream_command",
            )
            try:
                stream_client.command(
                    tagged_query,
                    settings={"query_id": stream_command_query_id},
                )
                query_log_metrics = self._query_log_metrics_by_query_id(
                    query_id=stream_command_query_id
                )
                if query_log_metrics is not None:
                    return query_log_metrics
            except Exception:
                logger.exception("Stream command для select не удался")
            stream_query_query_id = self._build_query_id(
                query_tag,
                suffix="sel_stream_query",
            )
            try:
                stream_client.query(
                    tagged_query,
                    settings={"query_id": stream_query_query_id},
                )
                query_log_metrics = self._query_log_metrics_by_query_id(
                    query_id=stream_query_query_id
                )
                if query_log_metrics is not None:
                    return query_log_metrics
            except Exception:
                logger.exception("Stream query для select не удался")

        client_query_id = self._build_query_id(query_tag, suffix="sel_client_query")
        try:
            self._client.query(
                tagged_query,
                settings={"query_id": client_query_id},
            )
        except Exception:
            logger.exception("Client query для select не удался")
            return _error_query_metrics()

        query_log_metrics = self._query_log_metrics_by_query_id(query_id=client_query_id)
        if query_log_metrics is not None:
            return query_log_metrics

        logger.warning(
            "SELECT выполнен, но метрики в system.query_log не найдены "
            "(query_id=%s, ожидаем type='QueryFinish')",
            client_query_id,
        )
        return _error_query_metrics()

    def _query_log_metrics_by_query_id(
        self,
        *,
        query_id: Optional[str],
    ) -> Optional[Dict[str, float]]:
        """
        Читает query-метрики из `system.query_log` по `query_id`.

        system.query_log асинхронный, поэтому опрашиваем с retry.
        """
        normalized_query_id = str(query_id or "").strip()
        if not normalized_query_id:
            return None

        poll_attempts = _QUERY_LOG_METRICS_POLL_ATTEMPTS
        poll_sleep_sec = _QUERY_LOG_METRICS_POLL_SLEEP_SEC
        poll_total_wait_sec = _QUERY_LOG_METRICS_POLL_TOTAL_WAIT_SEC

        query_candidates: list[str] = [
            """
            SELECT
                query_duration_ms,
                read_rows,
                read_bytes,
                written_rows,
                written_bytes
            FROM system.query_log
            WHERE type = 'QueryFinish'
              AND query_id = %(query_id)s
            ORDER BY event_time_microseconds DESC
            LIMIT 1
            """,
            """
            SELECT
                query_duration_ms,
                read_rows,
                read_bytes,
                written_rows,
                written_bytes
            FROM system.query_log
            WHERE type = 'QueryFinish'
              AND query_id = %(query_id)s
            ORDER BY event_time DESC
            LIMIT 1
            """,
        ]

        started_at = time.monotonic()
        min_attempts_by_time = 1
        if poll_sleep_sec > 0:
            min_attempts_by_time = int(poll_total_wait_sec / poll_sleep_sec) + 1
        effective_attempts = max(poll_attempts, min_attempts_by_time)

        for attempt_id in range(effective_attempts):
            for query_text in query_candidates:
                try:
                    rows = self.execute(query_text, {"query_id": normalized_query_id})
                except Exception:
                    continue
                if not rows:
                    continue
                row = rows[0]
                if not isinstance(row, (list, tuple)) or len(row) < 5:
                    continue
                elapsed_ms = _to_metric_or_error(row[0])
                if elapsed_ms < 0:
                    elapsed_ns = -1.0
                else:
                    elapsed_ns = float(elapsed_ms) * 1_000_000.0
                return {
                    "elapsed_ns": elapsed_ns,
                    "read_rows": _to_metric_or_error(row[1]),
                    "read_bytes": _to_metric_or_error(row[2]),
                    "written_rows": _to_metric_or_error(row[3]),
                    "written_bytes": _to_metric_or_error(row[4]),
                }
            if attempt_id + 1 >= effective_attempts:
                continue
            if poll_sleep_sec <= 0:
                continue
            elapsed_sec = time.monotonic() - started_at
            remaining_sec = poll_total_wait_sec - elapsed_sec
            if remaining_sec <= 0:
                break
            time.sleep(min(poll_sleep_sec, remaining_sec))
        return None

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
        tested_cols: Optional[Sequence[str]] = None,
        deterministic_order_by: Optional[str] = None,
    ) -> str:
        """Строит SELECT-часть для insert benchmark (обычный режим или strict-fill)."""
        source_ref = f"`{source_database}`.`{source_table}`"
        source_alias = "src"
        projection = f"{source_alias}.*"
        filter_columns = [str(col).strip() for col in (tested_cols or []) if str(col).strip()]
        where_clause = ""
        if filter_columns:
            conditions = []
            for column_name in filter_columns:
                escaped_name = column_name.replace("`", "``")
                conditions.append(f"toString(`{escaped_name}`) != ''")
            where_clause = f" WHERE {' AND '.join(conditions)}"
        order_by_clause = ""
        if deterministic_order_by:
            order_by_clause = f" ORDER BY {deterministic_order_by}"

        if n_rows is None:
            return (
                f"SELECT {projection} "
                f"FROM {source_ref} AS {source_alias}"
                f"{where_clause}{order_by_clause}"
            )

        if strictly_adhere_n_rows:
            required_rows = offset + n_rows
            return (
                "WITH\n"
                # Важно: считаем cnt на том же фильтре, что и в INSERT SELECT.
                # Иначе при OFFSET можно недооценить repeats и вставить меньше n_rows.
                f"    ifNull((SELECT count() FROM {source_ref}{where_clause}), 0) AS cnt,\n"
                f"    if(cnt = 0, 0, intDiv({required_rows} + cnt - 1, cnt)) AS repeats,\n"
                "    if(repeats = 0, 1, repeats) AS repeats_not_equal_zero\n"
                f"SELECT {projection}\n"
                f"FROM {source_ref} AS {source_alias}\n"
                "CROSS JOIN numbers(repeats_not_equal_zero) AS n\n"
                f"{where_clause}\n"
                f"{order_by_clause}\n"
                f"LIMIT {n_rows} OFFSET {offset}"
            )

        return (
            f"SELECT {projection} FROM {source_ref} AS {source_alias}"
            f"{where_clause}{order_by_clause} "
            f"LIMIT {n_rows} OFFSET {offset}"
        )

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
        deterministic_order_by: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        Копирует данные из source в target и возвращает метрики.

        Приоритет:
        1) streaming путь через clickhouse-connect (`raw_stream` + `raw_insert`);
        2) fallback через `INSERT INTO ... SELECT ...`.

        Метрики:
        - для streaming-insert берём напрямую из `query_summary` (clickhouse-connect);
        - для fallback `INSERT ... SELECT` используем обычный command-путь.
        """
        if n_rows is not None and n_rows <= 0:
            return _error_query_metrics()
        safe_offset = max(0, offset)
        fallback_strict_fill = bool(strictly_adhere_n_rows)

        def _build_source_select_query(strict_fill: bool) -> str:
            return self._build_source_select_for_insert(
                source_database=source_database,
                source_table=source_table,
                n_rows=n_rows,
                offset=safe_offset,
                strictly_adhere_n_rows=bool(strict_fill),
                tested_cols=tested_cols,
                deterministic_order_by=deterministic_order_by,
            )

        source_select_query = _build_source_select_query(fallback_strict_fill)
        stream_copy_disabled = bool(getattr(self, "_stream_copy_disabled", False))
        stream_client = None if stream_copy_disabled else self._get_stream_client()
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
                insert_query_id = self._build_query_id(
                    query_tag,
                    suffix="insert_stream_raw_insert",
                )
                query_summary = insert_client.raw_insert(
                    table=f"{target_database}.{target_table}",
                    insert_block=source_stream,
                    fmt="Native",
                    settings={"query_id": insert_query_id},
                )
                summary_metrics = self._extract_stream_query_summary(query_summary)
                if summary_metrics is not None:
                    self._stream_copy_failure_count = 0
                    return summary_metrics
                logger.warning(
                    "Streaming insert выполнен, но clickhouse-connect не вернул summary-метрики "
                    "(query_id=%s)",
                    insert_query_id,
                )
                return _error_query_metrics()
            except Exception as stream_exc:
                if _is_memory_limit_exceeded_error(stream_exc):
                    # При OOM в stream-copy сразу отключаем stream path и смягчаем fallback INSERT.
                    self._stream_copy_disabled = True
                    fallback_strict_fill = False
                    logger.exception(
                        "Streaming insert не удался из-за MEMORY_LIMIT_EXCEEDED: "
                        "переключаемся на fallback INSERT ... SELECT (strict_fill=0) "
                        "и отключаем stream copy до конца текущей worker-задачи",
                    )
                    continue_after_stream_error = False
                else:
                    continue_after_stream_error = True
                failure_count = int(getattr(self, "_stream_copy_failure_count", 0)) + 1
                self._stream_copy_failure_count = failure_count
                disable_after_failures = int(
                    getattr(self, "_stream_copy_disable_after_failures", 1)
                )
                if self._stream_copy_disabled or failure_count >= disable_after_failures:
                    self._stream_copy_disabled = True
                    logger.exception(
                        "Streaming insert не удался (failures=%d/%d): переключаемся на "
                        "fallback INSERT ... SELECT и отключаем stream copy "
                        "до конца текущей worker-задачи",
                        failure_count,
                        disable_after_failures,
                    )
                elif continue_after_stream_error:
                    logger.exception(
                        "Streaming insert не удался (failures=%d/%d): переключаемся на "
                        "fallback INSERT ... SELECT, stream copy остаётся включён",
                        failure_count,
                        disable_after_failures,
                    )
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

        def _run_fallback_insert(strict_fill: bool) -> Dict[str, float]:
            fallback_select = _build_source_select_query(strict_fill)
            insert_query = (
                f"INSERT INTO `{target_database}`.`{target_table}`\n"
                f"{fallback_select}"
            )
            return self._execute_command_with_summary_metrics(
                insert_query,
                query_tag=query_tag,
                raise_on_execute_error=True,
            )

        try:
            return _run_fallback_insert(fallback_strict_fill)
        except Exception as fallback_exc:
            if (
                fallback_strict_fill
                and _is_memory_limit_exceeded_error(fallback_exc)
                and n_rows is not None
            ):
                logger.warning(
                    "Fallback INSERT ... SELECT упал с MEMORY_LIMIT_EXCEEDED "
                    "(strict_fill=1). Повторяем один раз с strict_fill=0 "
                    "(table=%s.%s)",
                    target_database,
                    target_table,
                )
                try:
                    return _run_fallback_insert(False)
                except Exception as retry_exc:
                    if _is_memory_limit_exceeded_error(retry_exc):
                        raise RuntimeError(
                            "Не удалось выполнить INSERT benchmark: MEMORY_LIMIT_EXCEEDED "
                            f"для {target_database}.{target_table} (strict_fill=0 fallback)"
                        ) from retry_exc
                    raise
            if _is_memory_limit_exceeded_error(fallback_exc):
                raise RuntimeError(
                    "Не удалось выполнить INSERT benchmark: MEMORY_LIMIT_EXCEEDED "
                    f"для {target_database}.{target_table}"
                ) from fallback_exc
            raise


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
    deterministic_order_by: Optional[str] = None,
) -> Dict[str, List[float]]:
    """Собирает замеры INSERT со streaming-fast path и strict-fill режимом."""
    elapsed_ns_entries: list[float] = []
    written_rows_per_second_entries: list[float] = []
    read_bytes_per_second_entries: list[float] = []
    written_rows_entries: list[float] = []
    max_retries, initial_sleep_sec, retry_sleep_increment = client.get_retry_policy()
    expected_rows_per_measurement = float(n_rows) if n_rows is not None else None

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
                deterministic_order_by=deterministic_order_by,
            )
            if not _is_error_query_metrics(query_metrics):
                # Гарантируем "ровно n_rows" на каждой insert-итерации, если лимит задан.
                if expected_rows_per_measurement is not None:
                    inserted_rows = float(query_metrics.get("written_rows", -1.0))
                    if inserted_rows + 1e-9 < expected_rows_per_measurement:
                        logger.warning(
                            "INSERT вставил меньше требуемого объёма "
                            "(table=%s.%s, measurement=%d, expected_rows=%d, inserted_rows=%.0f). "
                            "Считаем итерацию неуспешной и повторяем.",
                            target_database,
                            target_table,
                            measurement_id,
                            int(expected_rows_per_measurement),
                            inserted_rows,
                        )
                        query_metrics = _error_query_metrics()
                    else:
                        break
                else:
                    break

            if max_retries != -1 and attempt_n >= max_retries:
                if expected_rows_per_measurement is not None:
                    raise RuntimeError(
                        "Не удалось вставить требуемый объём строк "
                        f"для {target_database}.{target_table} (measurement={measurement_id}, "
                        f"expected_rows={int(expected_rows_per_measurement)}, retries={max_retries})"
                    )
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
    read_bytes_entries: list[float] = []
    per_query_entries: list[dict[str, Any]] = []
    max_retries, initial_sleep_sec, retry_sleep_increment = client.get_retry_policy()

    if not test_queries:
        return {
            "elapsed_ns": elapsed_ns_entries,
            "rows_per_second": read_rows_per_second_entries,
            "bytes_per_second": read_bytes_per_second_entries,
            "read_bytes": read_bytes_entries,
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
        query_read_bytes_entries: list[float] = []
        cold_settings_assignments: Optional[List[str]] = None

        if query_cache_mode == "cold":
            cold_settings_assignments = list(_COLD_SELECT_SETTINGS_ASSIGNMENTS)

        for measurement_id in range(max(1, query_measurements_count)):
            if query_cache_mode == "warm":
                effective_warmups = (
                    list(query_warmup_queries)
                    if query_warmup_queries
                    else [query]
                )
                for warmup_query in effective_warmups:
                    client.execute_user_read_only_query(warmup_query)

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
            query_read_bytes_entries.append(read_bytes)

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
        query_read_bytes_entries = _filter_non_negative_finite_measurements(
            query_read_bytes_entries,
            metric_name="read_bytes",
            context=query_context,
        )
        elapsed_ns_entries.extend(query_elapsed_ns_entries)
        read_rows_per_second_entries.extend(query_rows_per_second_entries)
        read_bytes_per_second_entries.extend(query_bytes_per_second_entries)
        read_bytes_entries.extend(query_read_bytes_entries)

        per_query_entries.append(
            {
                "query_index": query_index,
                "query_id": query_id,
                "query": query,
                "query_type": query_payload.query_type,
                "cache_mode": query_cache_mode,
                "select_operations_count": query_measurements_count,
                "warmup_queries": query_warmup_queries,
                "elapsed_ns_measurements": query_elapsed_ns_entries,
                "rows_per_second_measurements": query_rows_per_second_entries,
                "bytes_per_second_measurements": query_bytes_per_second_entries,
                "read_bytes_measurements": query_read_bytes_entries,
            }
        )

    return {
        "elapsed_ns": elapsed_ns_entries,
        "rows_per_second": read_rows_per_second_entries,
        "bytes_per_second": read_bytes_per_second_entries,
        "read_bytes": read_bytes_entries,
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
        read_bytes_measurements = _filter_non_negative_finite_measurements(
            list(float(value) for value in (raw_entry.get("read_bytes_measurements", []) or [])),
            metric_name="read_bytes",
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
        read_bytes_percentiles = compute_percentiles(
            read_bytes_measurements,
            measured_percentiles,
        )
        bytes_per_second_measurements_readable = [
            make_readable_bytes(value) for value in bytes_per_second_measurements
        ]
        bytes_per_second_percentiles_readable = [
            make_readable_bytes(value) for value in bytes_per_second_percentiles
        ]
        read_bytes_measurements_readable = [
            make_readable_bytes(value) for value in read_bytes_measurements
        ]
        read_bytes_percentiles_readable = [
            make_readable_bytes(value) for value in read_bytes_percentiles
        ]
        elapsed_ms_median = _median_positive_finite(elapsed_ms_measurements)

        result.append(
            {
                "query_index": query_index,
                "query_id": query_id,
                "query": query,
                "query_type": str(raw_entry.get("query_type") or "generic"),
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
                "bytes_per_second_measurements_readable": bytes_per_second_measurements_readable,
                "bytes_per_second_percentiles": bytes_per_second_percentiles,
                "bytes_per_second_percentiles_readable": bytes_per_second_percentiles_readable,
                "read_bytes_measurements": read_bytes_measurements,
                "read_bytes_measurements_readable": read_bytes_measurements_readable,
                "read_bytes_percentiles": read_bytes_percentiles,
                "read_bytes_percentiles_readable": read_bytes_percentiles_readable,
                "elapsed_ms_median": elapsed_ms_median,
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
            normalized_entry.setdefault("query_type", "generic")
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
    legacy_bytes_per_second_measurements_readable = list(
        source_metrics.get("source_table_select_bytes_per_second_measurements_readable", []) or []
    )
    legacy_bytes_per_second_percentiles = list(
        source_metrics.get("source_table_select_bytes_per_second_measurements_percentiles", []) or []
    )
    legacy_bytes_per_second_percentiles_readable = list(
        source_metrics.get(
            "source_table_select_bytes_per_second_measurements_percentiles_readable",
            [],
        )
        or []
    )
    if (
        not legacy_query
        and not legacy_elapsed_ms_measurements
        and not legacy_elapsed_ms_percentiles
        and not legacy_rows_per_second_measurements
        and not legacy_rows_per_second_percentiles
        and not legacy_bytes_per_second_measurements
        and not legacy_bytes_per_second_percentiles
        and not legacy_bytes_per_second_measurements_readable
        and not legacy_bytes_per_second_percentiles_readable
    ):
        return []

    if not legacy_bytes_per_second_measurements_readable:
        legacy_bytes_per_second_measurements_readable = [
            make_readable_bytes(float(v)) for v in legacy_bytes_per_second_measurements
        ]
    if not legacy_bytes_per_second_percentiles_readable:
        legacy_bytes_per_second_percentiles_readable = [
            make_readable_bytes(float(v)) for v in legacy_bytes_per_second_percentiles
        ]

    return [
        {
            "query_index": 0,
            "query_id": "query_0",
            "query": str(legacy_query or ""),
            "query_type": "generic",
            "cache_mode": "warm",
            "select_operations_count": len(legacy_elapsed_ms_measurements),
            "warmup_queries": [],
            "elapsed_ms_measurements": [float(v) for v in legacy_elapsed_ms_measurements],
            "elapsed_ms_percentiles": [float(v) for v in legacy_elapsed_ms_percentiles],
            "rows_per_second_measurements": [float(v) for v in legacy_rows_per_second_measurements],
            "rows_per_second_percentiles": [float(v) for v in legacy_rows_per_second_percentiles],
            "bytes_per_second_measurements": [float(v) for v in legacy_bytes_per_second_measurements],
            "bytes_per_second_measurements_readable": [
                str(v) for v in legacy_bytes_per_second_measurements_readable
            ],
            "bytes_per_second_percentiles": [float(v) for v in legacy_bytes_per_second_percentiles],
            "bytes_per_second_percentiles_readable": [
                str(v) for v in legacy_bytes_per_second_percentiles_readable
            ],
            "read_bytes_measurements": [],
            "read_bytes_measurements_readable": [],
            "read_bytes_percentiles": [],
            "read_bytes_percentiles_readable": [],
            "elapsed_ms_median": _median_positive_finite(
                [float(v) for v in legacy_elapsed_ms_measurements]
            ),
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
        source_read_bytes_percentiles = (
            _coerce_float_list(source_entry.get("read_bytes_percentiles", []))
            if source_entry is not None
            else []
        )
        tested_read_bytes_percentiles = _coerce_float_list(
            tested_entry.get("read_bytes_percentiles", [])
        )
        read_bytes_speed_up_coefs = compute_speedup_coefficients(
            source_read_bytes_percentiles,
            tested_read_bytes_percentiles,
        )
        result.append(
            {
                "query_index": query_index,
                "query_id": query_id,
                "query": tested_entry.get("query"),
                "query_type": (
                    tested_entry.get("query_type")
                    or (source_entry.get("query_type") if source_entry is not None else None)
                    or "generic"
                ),
                "source_query": source_entry.get("query") if source_entry is not None else None,
                "elapsed_ms_percentiles_speed_up_coefs": speed_up_coefs,
                "read_bytes_percentiles_speed_up_coefs": read_bytes_speed_up_coefs,
            }
        )
    return result


def _extract_read_bytes_speedup_by_query(
    speedup_per_query: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Оставляет из per-query speedup только read_bytes коэффициенты."""
    result: list[dict[str, Any]] = []
    for fallback_index, entry in enumerate(speedup_per_query):
        if not isinstance(entry, dict):
            continue
        query_index = int(entry.get("query_index", fallback_index))
        query_id = str(entry.get("query_id", f"query_{query_index}"))
        read_bytes_speedup = entry.get("read_bytes_percentiles_speed_up_coefs", [])
        if not isinstance(read_bytes_speedup, list):
            read_bytes_speedup = []
        result.append(
            {
                "query_index": query_index,
                "query_id": query_id,
                "query": entry.get("query"),
                "query_type": entry.get("query_type") or "generic",
                "source_query": entry.get("source_query"),
                "read_bytes_percentiles_speed_up_coefs": read_bytes_speedup,
            }
        )
    return result


def _map_per_query_entries_by_query_id(
    entries: Sequence[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Строит map `query_id -> entry` для per-query payload."""
    result: dict[str, Dict[str, Any]] = {}
    for fallback_index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        query_index = int(entry.get("query_index", fallback_index))
        query_id = str(entry.get("query_id", f"query_{query_index}"))
        result[query_id] = entry
    return result


def _build_per_query_expression_context(
    *,
    source_per_query: Sequence[Dict[str, Any]],
    tested_per_query: Sequence[Dict[str, Any]],
    speedup_per_query: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Собирает per-query контекст для scoring expression."""

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
        "source_by_query_id": _map_per_query_entries_by_query_id(source_per_query),
        "tested_by_query_id": _map_per_query_entries_by_query_id(tested_per_query),
        "speedup_by_query_id": _map_per_query_entries_by_query_id(speedup_per_query),
        "source_by_query_index": _to_query_index_map(source_per_query),
        "tested_by_query_index": _to_query_index_map(tested_per_query),
        "speedup_by_query_index": _to_query_index_map(speedup_per_query),
    }


def _resolve_measurement_quality_flag(
    per_query_metrics: Sequence[Dict[str, Any]],
) -> str:
    """Noise gating disabled: measurement quality is always `stable`."""
    del per_query_metrics
    return "stable"


def _build_measurement_quality_details(
    per_query_metrics: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Строит нейтральные детали качества (noise gating отключен)."""
    total_queries = 0
    for entry in per_query_metrics:
        if not isinstance(entry, dict):
            continue
        total_queries += 1

    return {
        "quality_flag": "stable",
        "total_queries": total_queries,
    }


def _extract_source_metrics(source_benchmark_payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Безопасно достаёт baseline metrics из payload source benchmark."""
    if not source_benchmark_payload:
        return {}
    metrics = source_benchmark_payload.get("metrics")
    if isinstance(metrics, dict):
        return metrics
    return {}


def _build_query_plan_signature(test_queries: Sequence[QueryPayload]) -> str:
    """Строит стабильную сигнатуру query-плана для дедупликации результатов."""
    signature_payload: list[dict[str, Any]] = []
    for query in test_queries:
        signature_payload.append(
            {
                "query_id": str(query.query_id or "").strip(),
                "query": str(query.query or "").strip(),
                "query_type": str(query.query_type or "").strip(),
                "cache_mode": str(query.cache_mode or "").strip(),
                "select_operations_count": (
                    int(query.select_operations_count)
                    if query.select_operations_count is not None
                    else None
                ),
                "warmup_queries": [str(value) for value in list(query.warmup_queries)],
            }
        )
    serialized = json.dumps(
        signature_payload,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def _augment_variant_params_with_runtime_context(
    payload: VariantBenchmarkTaskPayload,
) -> Dict[str, Any]:
    """
    Дополняет variant_params runtime-сигнатурами для безопасного DDL-дедупа.

    Эти поля нужны, чтобы не переиспользовать метрики между задачами с разными
    query-планами/лимитами измерений.
    """
    params = dict(payload.variant_params or {})
    params["__runtime_query_signature"] = _build_query_plan_signature(
        payload.query_plan.test_queries
    )
    params["__runtime_insert_rows_limit"] = payload.insert_rows_limit
    params["__runtime_insert_operations_count"] = payload.insert_operations_count
    params["__runtime_measured_percentiles_signature"] = json.dumps(
        [int(value) for value in list(payload.measured_percentiles)],
        ensure_ascii=False,
        sort_keys=False,
        default=str,
    )
    return params


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


def _resolve_deterministic_insert_order_by_expression(
    source_table_ddl: Optional[str],
) -> Optional[str]:
    """
    Возвращает ORDER BY выражение исходной таблицы для детерминированного INSERT ... SELECT.

    Если парсинг DDL не удался, возвращает `None` (fallback к прежнему поведению).
    """
    ddl_text = str(source_table_ddl or "").strip()
    if not ddl_text:
        return None
    try:
        parsed = TableDDL.from_ddl(ddl_text)
    except Exception:
        return None
    order_by_expr = str(parsed.order_by or "").strip()
    if not order_by_expr:
        return None
    if order_by_expr.lower() == "tuple()":
        return None
    return order_by_expr


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


def _build_primary_index_size_json(
    *,
    size_bytes: float,
    total_size_bytes_with_indexes: Optional[float],
) -> Optional[str]:
    """Собирает JSON для метрик primary index."""
    normalized_size_bytes = _to_positive_finite_float(size_bytes)
    if normalized_size_bytes <= 0:
        return None
    normalized_total_size = _to_positive_finite_float(total_size_bytes_with_indexes)
    percent_from_total_size: Optional[float] = None
    if normalized_total_size > 0:
        percent_from_total_size = round(
            (normalized_size_bytes / normalized_total_size) * 100.0,
            4,
        )
    return _to_json_or_none(
        {
            "size_bytes": normalized_size_bytes,
            "size_bytes_readable": make_readable_bytes(normalized_size_bytes),
            "size_percent_from_total_size": percent_from_total_size,
        }
    )


def _build_table_size_value_json(
    *,
    size_bytes: Optional[float],
    size_bytes_readable: Optional[str],
    bytes_on_disk_sum: Optional[float],
) -> Optional[str]:
    """Строит JSON значения размера с дополнительным полем `sum(bytes_on_disk)`."""
    payload: Dict[str, Any] = {}

    if size_bytes is not None:
        numeric_size = float(size_bytes)
        payload["size_bytes"] = numeric_size
        payload["size_bytes_readable"] = (
            str(size_bytes_readable or "").strip() or make_readable_bytes(numeric_size)
        )

    normalized_bytes_on_disk = _to_positive_finite_float(bytes_on_disk_sum)
    if normalized_bytes_on_disk > 0:
        payload["bytes_on_disk_sum"] = normalized_bytes_on_disk
        payload["bytes_on_disk_sum_readable"] = make_readable_bytes(normalized_bytes_on_disk)

    if not payload:
        return None
    return _to_json_or_none(payload)


def _build_baseline_variant_result(
    *,
    payload: SourceBenchmarkTaskPayload,
    baseline_database: str,
    baseline_table: str,
    baseline_ddl: str,
    metrics: Dict[str, Any],
    baseline_score: Optional[float],
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
    source_bytes_on_disk_sum = float(
        metrics.get(
            "source_table_bytes_on_disk_sum",
            metrics.get("source_table_total_size_bytes_with_indexes", 0.0),
        )
        or 0.0
    )
    tested_bytes_on_disk_sum = float(
        metrics.get(
            "tested_table_bytes_on_disk_sum",
            metrics.get(
                "tested_table_total_size_bytes_with_indexes",
                tested_total_size_bytes_with_indexes,
            ),
        )
        or tested_total_size_bytes_with_indexes
    )
    tested_size_with_indexes_json = _build_table_size_value_json(
        size_bytes=tested_total_size_bytes_with_indexes,
        size_bytes_readable=make_readable_bytes(tested_total_size_bytes_with_indexes),
        bytes_on_disk_sum=tested_bytes_on_disk_sum,
    )
    source_size_overall_json = _build_table_size_value_json(
        size_bytes=source_total_size_bytes,
        size_bytes_readable=make_readable_bytes(source_total_size_bytes),
        bytes_on_disk_sum=source_bytes_on_disk_sum,
    )
    tested_table_primary_index_size_json = metrics.get("tested_table_primary_index_size_json")
    if tested_table_primary_index_size_json is None:
        tested_table_primary_index_size_json = _build_primary_index_size_json(
            size_bytes=float(metrics.get("tested_table_primary_index_size_bytes", 0.0) or 0.0),
            total_size_bytes_with_indexes=tested_total_size_bytes_with_indexes,
        )
    elif not isinstance(tested_table_primary_index_size_json, str):
        tested_table_primary_index_size_json = _to_json_or_none(
            tested_table_primary_index_size_json
        )
    source_rows = int(metrics.get("total_n_rows_in_source_table", 0) or 0)
    tested_rows = int(metrics.get("total_n_rows_in_tested_table", source_rows) or source_rows)
    tested_columns_size_map = (
        metrics.get("tested_table_consumed_compressed_size_bytes_by_each_column")
        or metrics.get("source_table_consumed_compressed_size_bytes_by_each_column")
    )
    measurement_quality_details_payload = metrics.get("measurement_quality_details_json")
    if isinstance(measurement_quality_details_payload, str):
        measurement_quality_details_json_value = measurement_quality_details_payload
    else:
        measurement_quality_details_json_value = _to_json_or_none(
            measurement_quality_details_payload
        )
    baseline_row_score_calculation_json = _to_pretty_score_calculation_json(
        {
            "mode": "source_baseline",
            "status": "ok" if baseline_score is not None else "empty",
            "final_score": baseline_score,
            "note": (
                "source_baseline row does not store self-comparison metrics "
                "(speedup/compression comparison fields are empty by design)"
            ),
        }
    )
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
        # baseline не сравнивается сам с собой: поля сравнений храним пустыми.
        tested_table_insert_time_ms_measurements_percentiles_speed_up_coefs=[],
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
        # baseline не сравнивается сам с собой: поля сравнений храним пустыми.
        tested_table_select_time_ms_measurements_percentiles_speed_up_coefs=[],
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
        # baseline не сравнивается сам с собой: per-query speedup не заполняем.
        tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json=None,
        tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json=None,
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
        tested_table_consumed_compressed_size_bytes_with_indexes_json=tested_size_with_indexes_json,
        tested_table_primary_index_size_json=tested_table_primary_index_size_json,
        source_table_consumed_compressed_size_bytes_overall=source_total_size_bytes,
        source_table_consumed_compressed_size_bytes_overall_readable=make_readable_bytes(
            source_total_size_bytes
        ),
        source_table_consumed_compressed_size_bytes_overall_json=source_size_overall_json,
        # baseline не сравнивается сам с собой: коэффициенты сравнения пустые.
        tested_table_compression_overall_coef=None,
        tested_table_compression_by_each_column_coef=None,
        source_table_n_rows_in_size_test=source_rows,
        tested_table_n_rows_in_size_test=int(
            metrics.get("tested_table_n_rows_in_size_test", tested_rows) or tested_rows
        ),
        measurement_quality_flag=str(metrics.get("measurement_quality_flag") or "stable"),
        measurement_quality_details_json=measurement_quality_details_json_value,
        score_calculation_json=baseline_row_score_calculation_json,
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
        deterministic_insert_order_by = _resolve_deterministic_insert_order_by_expression(
            payload.source_table_ddl
        )

        insert_stats = _measure_insert(
            client,
            source_database=payload.source_database,
            source_table=payload.source_table,
            target_database=baseline_database,
            target_table=baseline_table,
            n_rows=payload.insert_rows_limit,
            n_measurements=payload.insert_operations_count,
            deterministic_order_by=deterministic_insert_order_by,
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

        if _should_run_optimize_final():
            try:
                client.optimize_table_final(baseline_database, baseline_table)
                if not client.wait_for_no_active_merges(baseline_database, baseline_table):
                    logger.warning(
                        "run_source_benchmark: timeout ожидания merges=0 после OPTIMIZE FINAL "
                        "для %s.%s",
                        baseline_database,
                        baseline_table,
                    )
            except Exception as exc:
                if _is_optimize_access_denied(exc):
                    global _OPTIMIZE_FINAL_PERMISSION_DENIED
                    _OPTIMIZE_FINAL_PERMISSION_DENIED = True
                    logger.warning(
                        "run_source_benchmark: OPTIMIZE FINAL отключён для текущего worker "
                        "после ACCESS_DENIED (%s.%s)",
                        baseline_database,
                        baseline_table,
                    )
                else:
                    logger.exception(
                        "run_source_benchmark: не удалось стабилизировать таблицу после INSERT "
                        "(%s.%s)",
                        baseline_database,
                        baseline_table,
                    )

        select_stats = _measure_select_queries(
            client,
            test_queries=baseline_test_queries,
            n_measurements=payload.insert_operations_count,
        )
        source_select_per_query_metrics = _build_select_per_query_metrics(
            select_stats.get("per_query", []),
            payload.measured_percentiles,
        )
        measurement_quality_flag = _resolve_measurement_quality_flag(
            source_select_per_query_metrics
        )
        measurement_quality_details = _build_measurement_quality_details(
            source_select_per_query_metrics
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

        # В baseline-режиме "source" и "tested" метрики должны измеряться
        # на одном и том же объёме данных (копия исходного DDL), чтобы избежать
        # перекоса при сравнении полной source-таблицы vs test-копии.
        baseline_total_rows = client.count_rows(baseline_database, baseline_table)
        baseline_columns_sizes = client.get_column_sizes(baseline_database, baseline_table)
        baseline_indexes_sizes = client.get_index_sizes(baseline_database, baseline_table)
        baseline_total_size_bytes = client.get_total_compressed_size_bytes(
            baseline_database,
            baseline_table,
        )
        (
            baseline_columns_sizes,
            baseline_indexes_sizes,
            baseline_total_size_bytes,
        ) = _wait_for_table_size_materialization_if_needed(
            client,
            database=baseline_database,
            table=baseline_table,
            column_sizes=baseline_columns_sizes,
            index_sizes=baseline_indexes_sizes,
            total_size_bytes=baseline_total_size_bytes,
        )
        baseline_total_size_bytes = _normalize_total_size_bytes(
            baseline_total_size_bytes,
            column_sizes=baseline_columns_sizes,
            context=f"run_source_benchmark baseline {baseline_database}.{baseline_table}",
        )
        baseline_parts_metrics = client.get_table_parts_size_metrics(
            baseline_database,
            baseline_table,
        )
        baseline_parts_data_size = _to_positive_finite_float(
            baseline_parts_metrics.get("data_compressed_bytes")
        )
        if baseline_parts_data_size > 0:
            baseline_total_size_bytes = _normalize_total_size_bytes(
                baseline_parts_data_size,
                column_sizes=baseline_columns_sizes,
                context=(
                    f"run_source_benchmark baseline(parts) "
                    f"{baseline_database}.{baseline_table}"
                ),
            )
        baseline_total_size_bytes_with_indexes = _resolve_total_size_with_indexes_bytes(
            parts_metrics=baseline_parts_metrics,
            normalized_data_size_bytes=baseline_total_size_bytes,
        )
        baseline_bytes_on_disk_sum = _to_positive_finite_float(
            baseline_parts_metrics.get("bytes_on_disk")
        )
        if baseline_bytes_on_disk_sum <= 0 and baseline_total_size_bytes_with_indexes > 0:
            baseline_bytes_on_disk_sum = baseline_total_size_bytes_with_indexes
        baseline_primary_index_size_bytes = _to_positive_finite_float(
            baseline_parts_metrics.get("primary_key_bytes_in_memory")
        )
        baseline_primary_index_size_json = _build_primary_index_size_json(
            size_bytes=baseline_primary_index_size_bytes,
            total_size_bytes_with_indexes=baseline_total_size_bytes_with_indexes,
        )
        baseline_tested_size_with_indexes_json = _build_table_size_value_json(
            size_bytes=baseline_total_size_bytes_with_indexes,
            size_bytes_readable=make_readable_bytes(baseline_total_size_bytes_with_indexes),
            bytes_on_disk_sum=baseline_bytes_on_disk_sum,
        )
        baseline_source_size_overall_json = _build_table_size_value_json(
            size_bytes=baseline_total_size_bytes,
            size_bytes_readable=make_readable_bytes(baseline_total_size_bytes),
            bytes_on_disk_sum=baseline_bytes_on_disk_sum,
        )

        source_total_rows = baseline_total_rows
        tested_total_rows = baseline_total_rows
        source_columns_sizes = baseline_columns_sizes
        tested_columns_sizes = baseline_columns_sizes
        source_indexes_sizes = baseline_indexes_sizes
        tested_indexes_sizes = baseline_indexes_sizes
        source_total_size_bytes = baseline_total_size_bytes
        tested_total_size_bytes = baseline_total_size_bytes
        source_total_size_bytes_with_indexes = baseline_total_size_bytes_with_indexes
        tested_total_size_bytes_with_indexes = baseline_total_size_bytes_with_indexes

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
            "measurement_quality_flag": measurement_quality_flag,
            "measurement_quality_details_json": measurement_quality_details,
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
            "tested_table_consumed_compressed_size_bytes_with_indexes_json": (
                baseline_tested_size_with_indexes_json
            ),
            "tested_table_primary_index_size_json": baseline_primary_index_size_json,
            # Backward-compatible internal aliases for older runs/tests.
            "tested_table_total_size_bytes_with_indexes": tested_total_size_bytes_with_indexes,
            "tested_table_total_size_bytes_with_indexes_readable": make_readable_bytes(
                tested_total_size_bytes_with_indexes
            ),
            "source_table_consumed_compressed_size_bytes_overall": source_total_size_bytes,
            "source_table_consumed_compressed_size_bytes_overall_readable": make_readable_bytes(
                source_total_size_bytes
            ),
            "source_table_consumed_compressed_size_bytes_overall_json": (
                baseline_source_size_overall_json
            ),
            "source_table_total_size_bytes_with_indexes": source_total_size_bytes_with_indexes,
            "source_table_total_size_bytes_with_indexes_readable": make_readable_bytes(
                source_total_size_bytes_with_indexes
            ),
            "source_table_bytes_on_disk_sum": baseline_bytes_on_disk_sum,
            "source_table_bytes_on_disk_sum_readable": make_readable_bytes(
                baseline_bytes_on_disk_sum
            ),
            "tested_table_bytes_on_disk_sum": baseline_bytes_on_disk_sum,
            "tested_table_bytes_on_disk_sum_readable": make_readable_bytes(
                baseline_bytes_on_disk_sum
            ),
            "tested_table_n_rows_in_size_test": tested_total_rows,
            "source_table_n_rows_in_size_test": source_total_rows,
            "total_n_rows_in_tested_table": tested_total_rows,
            "total_n_rows_in_source_table": source_total_rows,
        }

        _, baseline_geomean_details = _compute_variant_ratio_details(
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
        baseline_read_bytes_speedup_by_query = _extract_read_bytes_speedup_by_query(
            baseline_select_time_speedup_by_query
        )
        baseline_read_bytes_speedup_by_query_map = _map_per_query_entries_by_query_id(
            baseline_read_bytes_speedup_by_query
        )
        baseline_insert_time_speedup = compute_speedup_coefficients(
            insert_time_ms_percentiles,
            insert_time_ms_percentiles,
        )
        baseline_select_time_speedup = compute_speedup_coefficients(
            select_time_ms_percentiles,
            select_time_ms_percentiles,
        )
        baseline_per_query_context = _build_per_query_expression_context(
            source_per_query=source_select_per_query_metrics,
            tested_per_query=source_select_per_query_metrics,
            speedup_per_query=baseline_select_time_speedup_by_query,
        )
        baseline_context_medians = _build_score_context_medians(
            source_insert_time_ms=insert_time_ms_measurements,
            tested_insert_time_ms=insert_time_ms_measurements,
            source_select_time_ms=select_time_ms_measurements,
            tested_select_time_ms=select_time_ms_measurements,
            source_insert_rows_per_second=insert_stats["rows_per_second"],
            tested_insert_rows_per_second=insert_stats["rows_per_second"],
            source_select_rows_per_second=select_stats["rows_per_second"],
            tested_select_rows_per_second=select_stats["rows_per_second"],
            source_insert_bytes_per_second=insert_stats["bytes_per_second"],
            tested_insert_bytes_per_second=insert_stats["bytes_per_second"],
            source_select_bytes_per_second=select_stats["bytes_per_second"],
            tested_select_bytes_per_second=select_stats["bytes_per_second"],
            insert_time_speedup=baseline_insert_time_speedup,
            select_time_speedup=baseline_select_time_speedup,
            source_per_query=source_select_per_query_metrics,
            tested_per_query=source_select_per_query_metrics,
            speedup_per_query=baseline_select_time_speedup_by_query,
        )

        baseline_score, baseline_score_calculation_json = _resolve_score(
            scoring=payload.scoring,
            stage_name="source_baseline",
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
                        "time_ms_percentiles": baseline_insert_time_speedup,
                        "time_ms_by_percentile": build_percentile_lookup(
                            payload.measured_percentiles,
                            baseline_insert_time_speedup,
                        ),
                    },
                    "select": {
                        "time_ms_percentiles": baseline_select_time_speedup,
                        "time_ms_by_percentile": build_percentile_lookup(
                            payload.measured_percentiles,
                            baseline_select_time_speedup,
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
                "medians": baseline_context_medians,
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
                "tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json": (
                    baseline_read_bytes_speedup_by_query_map
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
    runtime_variant_params = _augment_variant_params_with_runtime_context(payload)
    insert_tested_cols: list[str] = []
    raw_index_choices = runtime_variant_params.get("index_choices")
    if isinstance(raw_index_choices, dict):
        for column_name, index_payload in raw_index_choices.items():
            if index_payload:
                insert_tested_cols.append(str(column_name))

    worker_started_at = datetime.now(timezone.utc)
    executed_variant_ddl = payload.variant_ddl
    try:
        client.create_database_if_not_exists(payload.variant_database)
        client.drop_table_if_exists(
            payload.variant_database,
            payload.variant_table,
            allowed_database=payload.variant_database,
        )
        try:
            client.execute(executed_variant_ddl)
        except Exception as create_exc:
            if not _is_nullable_sorting_key_error(create_exc):
                raise
            logger.warning(
                "run_variant_benchmark: retry CREATE TABLE with allow_nullable_key=1 "
                "(benchmark_run_id=%d, benchmark_id=%s, mode=%s, table=%s.%s, error=%s)",
                payload.benchmark_run_id,
                payload.benchmark_id,
                payload.variant_mode,
                payload.variant_database,
                payload.variant_table,
                str(create_exc),
            )
            executed_variant_ddl = _ensure_allow_nullable_key_in_ddl(executed_variant_ddl)
            client.execute(executed_variant_ddl)
        source_table_ddl_for_insert = None
        if payload.source_benchmark and isinstance(payload.source_benchmark, dict):
            source_table_ddl_for_insert = payload.source_benchmark.get("source_table_ddl")
        deterministic_insert_order_by = _resolve_deterministic_insert_order_by_expression(
            source_table_ddl_for_insert
        )

        insert_stats = _measure_insert(
            client,
            source_database=payload.source_database,
            source_table=payload.source_table,
            target_database=payload.variant_database,
            target_table=payload.variant_table,
            n_rows=payload.insert_rows_limit,
            n_measurements=payload.insert_operations_count,
            tested_cols=insert_tested_cols,
            deterministic_order_by=deterministic_insert_order_by,
        )

        tested_insert_time_ms = [
            value / 1_000_000.0 for value in insert_stats["elapsed_ns"]
        ]
        tested_insert_time_ms_percentiles = compute_percentiles(
            tested_insert_time_ms,
            measured_percentiles,
        )
        tested_insert_rows_per_second = list(insert_stats.get("rows_per_second", []) or [])
        tested_insert_rows_per_second_percentiles = compute_percentiles(
            tested_insert_rows_per_second,
            measured_percentiles,
        )
        tested_insert_bytes_per_second = list(insert_stats.get("bytes_per_second", []) or [])
        tested_insert_bytes_per_second_percentiles = compute_percentiles(
            tested_insert_bytes_per_second,
            measured_percentiles,
        )

        if _should_run_optimize_final():
            try:
                client.optimize_table_final(payload.variant_database, payload.variant_table)
                if not client.wait_for_no_active_merges(
                    payload.variant_database,
                    payload.variant_table,
                ):
                    logger.warning(
                        "run_variant_benchmark: timeout ожидания merges=0 после OPTIMIZE FINAL "
                        "для %s.%s",
                        payload.variant_database,
                        payload.variant_table,
                    )
            except Exception as exc:
                if _is_optimize_access_denied(exc):
                    global _OPTIMIZE_FINAL_PERMISSION_DENIED
                    _OPTIMIZE_FINAL_PERMISSION_DENIED = True
                    logger.warning(
                        "run_variant_benchmark: OPTIMIZE FINAL отключён для текущего worker "
                        "после ACCESS_DENIED (%s.%s)",
                        payload.variant_database,
                        payload.variant_table,
                    )
                else:
                    logger.exception(
                        "run_variant_benchmark: не удалось стабилизировать таблицу после INSERT "
                        "(%s.%s)",
                        payload.variant_database,
                        payload.variant_table,
                    )

        select_stats = _measure_select_queries(
            client,
            test_queries=payload.query_plan.test_queries,
            n_measurements=payload.insert_operations_count,
        )
        tested_select_per_query_metrics = _build_select_per_query_metrics(
            select_stats.get("per_query", []),
            measured_percentiles,
        )
        measurement_quality_flag = _resolve_measurement_quality_flag(
            tested_select_per_query_metrics
        )
        measurement_quality_details = _build_measurement_quality_details(
            tested_select_per_query_metrics
        )
        measurement_quality_details_json = _to_json_or_none(measurement_quality_details)
        source_select_per_query_metrics = _extract_source_select_per_query_metrics(source_metrics)
        tested_select_time_ms = [
            value / 1_000_000.0 for value in select_stats["elapsed_ns"]
        ]
        tested_select_time_ms_percentiles = compute_percentiles(
            tested_select_time_ms,
            measured_percentiles,
        )
        tested_select_rows_per_second = list(select_stats.get("rows_per_second", []) or [])
        tested_select_rows_per_second_percentiles = compute_percentiles(
            tested_select_rows_per_second,
            measured_percentiles,
        )
        tested_select_bytes_per_second = list(select_stats.get("bytes_per_second", []) or [])
        tested_select_bytes_per_second_percentiles = compute_percentiles(
            tested_select_bytes_per_second,
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
        tested_bytes_on_disk_sum = _to_positive_finite_float(
            tested_parts_metrics.get("bytes_on_disk")
        )
        if tested_bytes_on_disk_sum <= 0 and tested_total_size_bytes_with_indexes > 0:
            tested_bytes_on_disk_sum = tested_total_size_bytes_with_indexes
        tested_primary_index_size_bytes = _to_positive_finite_float(
            tested_parts_metrics.get("primary_key_bytes_in_memory")
        )
        tested_primary_index_size_json = _build_primary_index_size_json(
            size_bytes=tested_primary_index_size_bytes,
            total_size_bytes_with_indexes=tested_total_size_bytes_with_indexes,
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
        source_bytes_on_disk_sum = float(
            source_metrics.get("source_table_bytes_on_disk_sum", 0.0) or 0.0
        )
        if source_bytes_on_disk_sum <= 0 and source_total_size_bytes_with_indexes > 0:
            source_bytes_on_disk_sum = source_total_size_bytes_with_indexes

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
            live_source_bytes_on_disk_sum = _to_positive_finite_float(
                live_source_parts_metrics.get("bytes_on_disk")
            )
            if live_source_bytes_on_disk_sum > 0:
                source_bytes_on_disk_sum = live_source_bytes_on_disk_sum
        if source_total_size_bytes_with_indexes <= 0 and source_total_size_bytes > 0:
            source_total_size_bytes_with_indexes = source_total_size_bytes
        if source_bytes_on_disk_sum <= 0 and source_total_size_bytes_with_indexes > 0:
            source_bytes_on_disk_sum = source_total_size_bytes_with_indexes
        tested_size_with_indexes_json = _build_table_size_value_json(
            size_bytes=tested_total_size_bytes_with_indexes,
            size_bytes_readable=make_readable_bytes(tested_total_size_bytes_with_indexes),
            bytes_on_disk_sum=tested_bytes_on_disk_sum,
        )
        source_size_overall_json = _build_table_size_value_json(
            size_bytes=source_total_size_bytes,
            size_bytes_readable=make_readable_bytes(source_total_size_bytes),
            bytes_on_disk_sum=source_bytes_on_disk_sum,
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
        tested_select_read_bytes_speedup_by_query = _extract_read_bytes_speedup_by_query(
            tested_select_time_speedup_by_query
        )
        tested_select_read_bytes_speedup_by_query_map = _map_per_query_entries_by_query_id(
            tested_select_read_bytes_speedup_by_query
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
        source_insert_rows_per_second_for_score = list(
            source_metrics.get("source_table_insert_rows_per_second_measurements", []) or []
        )
        if not source_insert_rows_per_second_for_score:
            source_insert_rows_per_second_for_score = list(
                source_insert_bucket.get("rows_per_second_percentiles", []) or []
            )
        source_insert_bytes_per_second_for_score = list(
            source_metrics.get("source_table_insert_bytes_per_second_measurements", []) or []
        )
        if not source_insert_bytes_per_second_for_score:
            source_insert_bytes_per_second_for_score = list(
                source_insert_bucket.get("bytes_per_second_percentiles", []) or []
            )
        source_select_ms_for_score = list(
            source_metrics.get("source_table_select_time_ms_measurements", []) or []
        )
        if not source_select_ms_for_score:
            source_select_ms_for_score = list(source_select_time_ms_percentiles)
        source_select_rows_per_second_for_score = list(
            source_metrics.get("source_table_select_rows_per_second_measurements", []) or []
        )
        if not source_select_rows_per_second_for_score:
            source_select_rows_per_second_for_score = list(
                source_select_bucket.get("rows_per_second_percentiles", []) or []
            )
        source_select_bytes_per_second_for_score = list(
            source_metrics.get("source_table_select_bytes_per_second_measurements", []) or []
        )
        if not source_select_bytes_per_second_for_score:
            source_select_bytes_per_second_for_score = list(
                source_select_bucket.get("bytes_per_second_percentiles", []) or []
            )
        _, geomean_ratio_details = _compute_variant_ratio_details(
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
        variant_context_medians = _build_score_context_medians(
            source_insert_time_ms=source_insert_ms_for_score,
            tested_insert_time_ms=tested_insert_time_ms,
            source_select_time_ms=source_select_ms_for_score,
            tested_select_time_ms=tested_select_time_ms,
            source_insert_rows_per_second=source_insert_rows_per_second_for_score,
            tested_insert_rows_per_second=tested_insert_rows_per_second,
            source_select_rows_per_second=source_select_rows_per_second_for_score,
            tested_select_rows_per_second=tested_select_rows_per_second,
            source_insert_bytes_per_second=source_insert_bytes_per_second_for_score,
            tested_insert_bytes_per_second=tested_insert_bytes_per_second,
            source_select_bytes_per_second=source_select_bytes_per_second_for_score,
            tested_select_bytes_per_second=tested_select_bytes_per_second,
            insert_time_speedup=tested_insert_time_speedup,
            select_time_speedup=tested_select_time_speedup,
            source_per_query=source_select_per_query_metrics,
            tested_per_query=tested_select_per_query_metrics,
            speedup_per_query=tested_select_time_speedup_by_query,
        )
        score, score_calculation_json = _resolve_score(
            scoring=payload.scoring,
            stage_name=(payload.variant_mode or "").strip().lower() or None,
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
                    "insert": geomean_ratio_details.get("inputs", {}).get("insert_ratio"),
                    "select": geomean_ratio_details.get("inputs", {}).get("select_ratio"),
                    "compression": geomean_ratio_details.get("inputs", {}).get(
                        "compression_ratio"
                    ),
                },
                "medians": variant_context_medians,
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
                "tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json": (
                    tested_select_read_bytes_speedup_by_query_map
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

        execution_uuid = str(runtime_variant_params.get("execution_uuid") or "").strip()
        worker_finished_at = datetime.now(timezone.utc)
        result = BenchmarkVariantResult(
            benchmark_run_id=payload.benchmark_run_id,
            benchmark_started_at=payload.benchmark_started_at,
            benchmark_id=payload.benchmark_id,
            source_database=payload.source_database,
            source_table=payload.source_table,
            variant_table=payload.variant_table,
            variant_mode=payload.variant_mode,
            variant_params=runtime_variant_params,
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
            tested_table_ddl=executed_variant_ddl,
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
            tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json=(
                json.dumps(
                    tested_select_read_bytes_speedup_by_query,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                if tested_select_read_bytes_speedup_by_query
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
            tested_table_consumed_compressed_size_bytes_with_indexes_json=(
                tested_size_with_indexes_json
            ),
            tested_table_primary_index_size_json=tested_primary_index_size_json,
            source_table_consumed_compressed_size_bytes_overall=source_total_size_bytes,
            source_table_consumed_compressed_size_bytes_overall_readable=make_readable_bytes(
                source_total_size_bytes
            ),
            source_table_consumed_compressed_size_bytes_overall_json=source_size_overall_json,
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
            measurement_quality_flag=measurement_quality_flag,
            measurement_quality_details_json=measurement_quality_details_json,
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
            variant_params=runtime_variant_params,
            tested_table_ddl_fallback=executed_variant_ddl,
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


def _store_failed_variant_result(
    *,
    payload: VariantBenchmarkTaskPayload,
    error: Exception,
    celery_task_id: Optional[str] = None,
    celery_worker_hostname: Optional[str] = None,
    worker_started_at: Optional[datetime] = None,
) -> None:
    """
    Best-effort запись failed variant результата в result store.

    Это нужно, чтобы стратегия multi-phase не зависала в ожидании summary:
    даже упавший вариант должен оставить запись для своей `variant_table`.
    """
    runtime_variant_params = _augment_variant_params_with_runtime_context(payload)
    execution_uuid = str(runtime_variant_params.get("execution_uuid") or "").strip()
    worker_finished_at = datetime.now(timezone.utc)
    started_at = worker_started_at or worker_finished_at
    error_text = str(error or "unknown variant task error")
    score_details = _to_pretty_score_calculation_json(
        {
            "mode": "failed_variant",
            "status": "worker_exception",
            "error": error_text,
            "final_score": -1.0,
        }
    )
    quality_details = _to_json_or_none(
        {
            "quality_flag": "failed",
            "error": error_text,
            "failed_at": worker_finished_at.isoformat(),
        }
    )
    failed_result = BenchmarkVariantResult(
        benchmark_run_id=payload.benchmark_run_id,
        benchmark_started_at=payload.benchmark_started_at,
        benchmark_id=payload.benchmark_id,
        source_database=payload.source_database,
        source_table=payload.source_table,
        variant_table=payload.variant_table,
        variant_mode=payload.variant_mode,
        variant_params=runtime_variant_params,
        id=execution_uuid or None,
        celery_task_id=(str(celery_task_id).strip() if celery_task_id else None),
        celery_worker_hostname=(
            str(celery_worker_hostname).strip() if celery_worker_hostname else None
        ),
        worker_started_at=started_at,
        worker_finished_at=worker_finished_at,
        source_table_ddl=(
            payload.source_benchmark.get("source_table_ddl")
            if payload.source_benchmark
            else None
        ),
        tested_table_ddl=payload.variant_ddl,
        measured_percentiles=list(payload.measured_percentiles),
        measurement_quality_flag="failed",
        measurement_quality_details_json=quality_details,
        score_calculation_json=score_details,
        score=-1.0,
    )
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
    try:
        result_store.store_worker_result(
            benchmark_run_id=payload.benchmark_run_id,
            benchmark_started_at=payload.benchmark_started_at,
            benchmark_id=payload.benchmark_id,
            benchmark_strategy=payload.benchmark_strategy,
            source_database=payload.source_database,
            source_table=payload.source_table,
            variant_table=payload.variant_table,
            variant_mode=payload.variant_mode,
            variant_params=runtime_variant_params,
            tested_table_ddl_fallback=payload.variant_ddl,
            source_table_ddl_fallback=(
                payload.source_benchmark.get("source_table_ddl")
                if payload.source_benchmark
                else None
            ),
            result=failed_result,
        )
    finally:
        result_store.close()


def _build_default_celery_app():
    """Создаёт default Celery app для worker-процесса."""
    try:
        from celery import Celery
        from kombu import Queue
    except ImportError:
        logger.warning("Celery/Kombu не установлен: worker app не создан")
        return None

    settings = get_clickhouse_celery_worker_settings()
    app = Celery(
        "bench_clickhouse_worker",
        broker=settings.broker_url,
        backend=settings.backend_url,
    )
    broker_transport_options: Dict[str, Any] = {}
    broker_url_lower = settings.broker_url.lower()
    if broker_url_lower.startswith("redis://") or broker_url_lower.startswith("rediss://"):
        # Для Redis broker увеличиваем visibility timeout, чтобы long-running задачи
        # не возвращались в очередь как "потерянные" до фактического завершения.
        broker_transport_options["visibility_timeout"] = (
            settings.celery_broker_visibility_timeout_sec
        )
    queue_name = settings.celery_queue_name
    task_queues = (
        Queue(
            name=queue_name,
            exchange=queue_name,
            routing_key=queue_name,
            durable=True,
            auto_delete=False,
        ),
    )
    app.conf.update(
        worker_concurrency=settings.celery_worker_concurrency,
        # Важный guard: для ignore_result задач ошибки тоже не должны
        # накапливаться в backend (иначе снова растет потребление памяти).
        task_store_errors_even_if_ignored=False,
        # Сообщения задач должны быть persistent, чтобы не теряться при рестартах broker.
        task_default_delivery_mode="persistent",
        # Используем выделенную durable queue для benchmark-задач.
        task_default_queue=queue_name,
        task_default_exchange=queue_name,
        task_default_exchange_type="direct",
        task_default_routing_key=queue_name,
        task_queues=task_queues,
        task_routes={
            SOURCE_BENCHMARK_TASK_NAME: {"queue": queue_name, "routing_key": queue_name},
            VARIANT_BENCHMARK_TASK_NAME: {"queue": queue_name, "routing_key": queue_name},
        },
        # Явно отключаем queue-level TTL/expiry на стороне Celery, чтобы
        # RabbitMQ не удалял задачи из очереди по сроку жизни.
        task_queue_ttl=None,
        task_queue_expires=None,
        # Явно отключаем default task expiry (если не задано через env),
        # чтобы long-running/долго ожидающие задачи не протухали.
        task_default_expires=settings.celery_task_default_expires_sec,
        # TTL результатов настраивается через env; по умолчанию не ограничен.
        result_expires=settings.celery_result_expires_sec,
        # Тайм-лимиты задач опциональны и по умолчанию отключены.
        task_soft_time_limit=settings.celery_task_soft_time_limit_sec,
        task_time_limit=settings.celery_task_time_limit_sec,
        broker_transport_options=broker_transport_options,
    )
    logger.info(
        "Celery app инициализирован "
        "(broker=%s, concurrency=%d, task_default_expires=%s, result_expires=%s, "
        "task_soft_time_limit=%s, task_time_limit=%s, queue_ttl=%s, "
        "queue_expires=%s, delivery_mode=%s, queue_name=%s, visibility_timeout=%s)",
        settings.broker_url,
        settings.celery_worker_concurrency,
        settings.celery_task_default_expires_sec,
        settings.celery_result_expires_sec,
        settings.celery_task_soft_time_limit_sec,
        settings.celery_task_time_limit_sec,
        app.conf.task_queue_ttl,
        app.conf.task_queue_expires,
        app.conf.task_default_delivery_mode,
        queue_name,
        broker_transport_options.get("visibility_timeout"),
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

        celery_task_id: Optional[str] = None
        celery_worker_hostname: Optional[str] = None
        worker_started_at = datetime.now(timezone.utc)
        try:
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
            try:
                _store_failed_variant_result(
                    payload=typed_payload,
                    error=exc,
                    celery_task_id=celery_task_id,
                    celery_worker_hostname=celery_worker_hostname,
                    worker_started_at=worker_started_at,
                )
            except Exception:
                logger.exception(
                    "Celery worker: не удалось сохранить failed variant result "
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
