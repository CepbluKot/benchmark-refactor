"""Реализация многофазной top-N стратегии для ClickHouse."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import itertools
import logging
import re
from time import monotonic, sleep
from typing import TYPE_CHECKING, Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from src.clickhouse_ddl import IndexDef, TableDDL
from src.column_variants import ColumnVariantMeta
from src.index_variants import IndexVariantMeta
from src.variant_generation.types import VariantMeta

from ...contracts.result_store import BenchmarkResultStore
from ...contracts.table_strategy import TableExecutionStrategy
from ...types import (
    QueryPlan,
    SourceBenchmarkResult,
    StoredVariantSummary,
    TableBenchmarkPlan,
    VariantJob,
)

if TYPE_CHECKING:
    from src.benchmark_engine import BenchmarkRunner

_STAGE_WAIT_POLL_INTERVAL_SEC = 0.5
_STAGE_WAIT_TIMEOUT_SEC = 3600.0
_STAGE_BANNER_LINE = "=" * 92
_ORDER_BY_STAGE_HARD_LIMIT = 20
_ORDER_BY_MAX_COMBINATION_LEN = 3

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PhaseCandidate:
    """Кандидат между фазами оптимизации."""

    variant_table: str
    variant_ddl: TableDDL
    score: Optional[float]
    type_choices: Dict[str, str] = field(default_factory=dict)
    codec_choices: Dict[str, Optional[str]] = field(default_factory=dict)
    index_choices: Dict[str, _IndexColumnChoice] = field(default_factory=dict)


@dataclass(frozen=True)
class _TypeJobContext:
    """Контекст one-column type benchmark job."""

    parent_variant_table: str
    column_name: str
    tested_type: str


@dataclass(frozen=True)
class _CodecJobContext:
    """Контекст one-column codec benchmark job."""

    parent_variant_table: str
    column_name: str
    tested_codec: Optional[str]


@dataclass(frozen=True)
class _IndexJobContext:
    """Контекст one-column index benchmark job."""

    parent_variant_table: str
    column_name: str
    index_def: Optional[IndexDef]
    table_index_granularity: Optional[int]
    allowed_table_index_granularity_values: Optional[List[int]] = None


@dataclass(frozen=True)
class _IndexColumnChoice:
    """Выбор индекса для одной колонки (hashable payload для top-N merge)."""

    index_name: Optional[str]
    expr: Optional[str]
    index_type: Optional[str]
    granularity: Optional[str]
    preferred_table_index_granularity: Optional[int]
    allowed_table_index_granularity_values: Tuple[int, ...] = ()

    @classmethod
    def from_context(cls, context: _IndexJobContext) -> "_IndexColumnChoice":
        """Строит choice из контекста index-variant job."""
        index_def = context.index_def
        allowed_values = tuple(
            sorted(
                {
                    int(value)
                    for value in (context.allowed_table_index_granularity_values or [])
                    if value is not None
                }
            )
        )
        if index_def is None:
            return cls(
                index_name=None,
                expr=None,
                index_type=None,
                granularity=None,
                preferred_table_index_granularity=(
                    int(context.table_index_granularity)
                    if context.table_index_granularity is not None
                    else None
                ),
                allowed_table_index_granularity_values=allowed_values,
            )
        return cls(
            index_name=index_def.name,
            expr=index_def.expr,
            index_type=index_def.index_type,
            granularity=index_def.granularity,
            preferred_table_index_granularity=(
                int(context.table_index_granularity)
                if context.table_index_granularity is not None
                else None
            ),
            allowed_table_index_granularity_values=allowed_values,
        )

    def to_index_def(self) -> Optional[IndexDef]:
        """Восстанавливает IndexDef из hashable payload."""
        if self.index_type is None:
            return None
        return IndexDef(
            name=self.index_name or "idx_auto",
            expr=self.expr or "",
            index_type=self.index_type,
            granularity=self.granularity,
        )


def _log_stage_banner(
    *,
    stage_name: str,
    benchmark_run_id: int,
    benchmark_id: str,
    database: str,
    table: str,
) -> None:
    """Пишет заметный баннер старта стадии в логах."""
    logger.info(_STAGE_BANNER_LINE)
    logger.info(
        "СТАРТ СТАДИИ: %s | run_id=%d | benchmark=%s | table=%s.%s",
        stage_name,
        benchmark_run_id,
        benchmark_id,
        database,
        table,
    )
    logger.info(_STAGE_BANNER_LINE)


def _open_progress_scope_if_supported(
    runner: "BenchmarkRunner",
    scope_name: str,
) -> None:
    """Открывает progress-scope в adapter, если реализация поддерживает API."""
    open_hook = getattr(runner._execution_adapter, "open_progress_scope", None)
    if callable(open_hook):
        open_hook(scope_name)


def _wait_for_dispatched_tasks_if_supported(
    runner: "BenchmarkRunner",
    stage_label: str,
) -> None:
    """Ждёт завершения Celery-batch, если adapter поддерживает API ожидания."""
    wait_hook = getattr(runner._execution_adapter, "wait_for_dispatched_tasks", None)
    if callable(wait_hook):
        wait_hook(stage_label=stage_label)


def _prepare_table_context(
    runner: "BenchmarkRunner",
    table_plan: TableBenchmarkPlan,
) -> Tuple[TableDDL, QueryPlan, Dict[str, int]]:
    """Готовит исходный DDL, сырой query plan и эффективный порядок колонок."""
    source_ddl, raw_query_plan = runner._engine.prepare_table_context(table_plan)
    effective_column_order = runner._engine.resolve_column_order(
        table_plan=table_plan,
        source_ddl=source_ddl,
    )
    return source_ddl, raw_query_plan, effective_column_order


def _require_result_store(
    runner: "BenchmarkRunner",
    strategy_key: str,
) -> "BenchmarkResultStore":
    """Проверяет, что у runner есть result-store."""
    store = runner._result_store
    if store is None:
        raise ValueError(
            f"strategy={strategy_key!r} требует result_store "
            "(нужен top-N отбор между фазами)"
        )
    return store


def _normalize_identifier(value: str) -> str:
    """Нормализует SQL-идентификатор (снимает обрамляющие backticks)."""
    cleaned = value.strip()
    if cleaned.startswith("`") and cleaned.endswith("`") and len(cleaned) >= 2:
        return cleaned[1:-1]
    return cleaned


def _quote_identifier_if_plain(value: str) -> str:
    """Квотирует идентификатор, если он выглядит как простое имя колонки."""
    cleaned = _normalize_identifier(value)
    if re.fullmatch(r"[A-Za-z_]\w*", cleaned):
        return f"`{cleaned}`"
    return value.strip()


def _split_top_level_commas(text: str) -> List[str]:
    """Разбивает выражение по запятым верхнего уровня."""
    parts: list[str] = []
    depth = 0
    quote: Optional[str] = None
    buf: list[str] = []
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
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
        if ch == "," and depth == 0:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_order_by_components(order_by_expr: Optional[str]) -> List[str]:
    """Извлекает список компонентов из ORDER BY выражения."""
    if not order_by_expr:
        return []
    cleaned = order_by_expr.strip()
    if cleaned.upper() == "TUPLE()":
        return []
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = cleaned[1:-1].strip()
    if not cleaned:
        return []
    return [part.strip() for part in _split_top_level_commas(cleaned) if part.strip()]


def _default_first_order_by_column(source_ddl: TableDDL) -> Optional[str]:
    """Определяет fallback-колонку для первого элемента ORDER BY."""
    parsed = _parse_order_by_components(source_ddl.order_by)
    if parsed:
        return _normalize_identifier(parsed[0])
    for column in source_ddl.columns:
        normalized_type = column.type.strip().lower()
        if normalized_type.startswith("datetime") or normalized_type.startswith("date"):
            return column.name
    if source_ddl.columns:
        return source_ddl.columns[0].name
    return None


def _extract_filter_columns_from_query_plan(
    query_plan: QueryPlan,
    available_columns: Sequence[str],
) -> List[str]:
    """Пытается извлечь колонки из WHERE-фильтров пользовательских запросов."""
    candidates: list[str] = []
    available_set = set(available_columns)
    for query in query_plan.test_queries:
        sql = query.query
        # Убираем строковые литералы, чтобы не матчить имена колонок внутри строк.
        sql = re.sub(r"'(?:''|[^'])*'", " ", sql)
        sql = re.sub(r'"(?:\\"|[^"])*"', " ", sql)
        where_match = re.search(
            r"\bWHERE\b(?P<body>.*?)(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bLIMIT\b|\bSETTINGS\b|$)",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if where_match is None:
            continue
        where_body = where_match.group("body")
        for column_name in available_columns:
            if column_name not in available_set:
                continue
            token_pattern = rf"(?<![\w`])`?{re.escape(column_name)}`?(?![\w`])"
            if re.search(token_pattern, where_body):
                candidates.append(column_name)
    seen: set[str] = set()
    ordered_unique: list[str] = []
    for column_name in candidates:
        if column_name in seen:
            continue
        seen.add(column_name)
        ordered_unique.append(column_name)
    return ordered_unique


def _build_order_by_expression(columns: Sequence[str]) -> str:
    """Строит ORDER BY выражение из списка колонок."""
    normalized = [_quote_identifier_if_plain(column) for column in columns if column]
    if not normalized:
        return "tuple()"
    if len(normalized) == 1:
        return normalized[0]
    return f"({', '.join(normalized)})"


def _build_order_by_candidates(
    runner: "BenchmarkRunner",
    table_plan: TableBenchmarkPlan,
    source_ddl: TableDDL,
    raw_query_plan: QueryPlan,
) -> List[str]:
    """Генерирует кандидаты ORDER BY для первой фазы."""
    first_column = table_plan.order_by_first
    if first_column is None:
        first_column = _default_first_order_by_column(source_ddl)
    if not first_column:
        return []
    first_column = _normalize_identifier(first_column)

    parsed_order = _parse_order_by_components(source_ddl.order_by)
    parsed_tail = [
        _normalize_identifier(component)
        for component in parsed_order[1:]
        if _normalize_identifier(component) != first_column
    ]
    query_filter_columns = _extract_filter_columns_from_query_plan(
        raw_query_plan,
        [column.name for column in source_ddl.columns],
    )
    configured_candidates = [
        _normalize_identifier(value)
        for value in (table_plan.order_by_candidates or [])
        if _normalize_identifier(value)
    ]
    auto_generate_candidates = bool(table_plan.order_by_auto_generate_candidates)
    ordered_candidates: list[str] = []
    additional_candidates: list[str] = []
    if auto_generate_candidates:
        additional_candidates = [*parsed_tail, *query_filter_columns]
    for value in itertools.chain(configured_candidates, additional_candidates):
        if value == first_column:
            continue
        if value in ordered_candidates:
            continue
        if source_ddl.column(value) is None:
            continue
        ordered_candidates.append(value)

    combo_max_len = min(_ORDER_BY_MAX_COMBINATION_LEN, len(ordered_candidates))
    expressions: list[str] = []
    for size in range(0, combo_max_len + 1):
        for suffix in itertools.combinations(ordered_candidates, size):
            expressions.append(_build_order_by_expression([first_column, *suffix]))

    if not expressions:
        expressions = [_build_order_by_expression([first_column])]

    stage_limit = runner._engine.resolve_variant_generation_limit(
        table_plan=table_plan,
        variant_mode="order_by",
        job_mode="sequential",
    )
    hard_limit = _ORDER_BY_STAGE_HARD_LIMIT
    if stage_limit is not None:
        hard_limit = min(hard_limit, max(1, int(stage_limit)))
    return expressions[:hard_limit]


def _reset_all_codecs_to_default(ddl: TableDDL) -> None:
    """Сбрасывает явные CODEC у всех колонок (используется в ORDER BY фазе)."""
    for column in ddl.columns:
        column.codec = None


def _next_global_index(counter: List[int]) -> int:
    """Возвращает следующий global_index и увеличивает счётчик."""
    value = counter[0]
    counter[0] += 1
    return value


def _build_job(
    *,
    runner: "BenchmarkRunner",
    table_plan: TableBenchmarkPlan,
    raw_query_plan: QueryPlan,
    variant_ddl: TableDDL,
    variant_mode: str,
    total_variants: int,
    benchmark_run_id: int,
    benchmark_started_at: datetime,
    source_benchmark: SourceBenchmarkResult,
    global_index_counter: List[int],
    column_meta: Optional[ColumnVariantMeta] = None,
    index_meta: Optional[IndexVariantMeta] = None,
    table_index_granularity: Optional[int] = None,
    parent_variant_table: Optional[str] = None,
    phase_name: Optional[str] = None,
    stage_column_name: Optional[str] = None,
    merged_columns: Optional[Sequence[str]] = None,
) -> VariantJob:
    """Строит VariantJob с нужным phase-mode."""
    variant_meta = VariantMeta(
        global_index=_next_global_index(global_index_counter),
        mode=variant_mode,
        parent_variant_table=parent_variant_table,
        phase_name=phase_name,
        stage_column_name=stage_column_name,
        merged_columns=list(merged_columns or []),
        table_index_granularity=table_index_granularity,
        column_meta=column_meta,
        index_meta=index_meta,
    )
    return runner._engine.build_variant_job(
        table_plan=table_plan,
        raw_query_plan=raw_query_plan,
        variant_ddl=variant_ddl,
        variant_meta=variant_meta,
        total_variants=total_variants,
        benchmark_run_id=benchmark_run_id,
        benchmark_started_at=benchmark_started_at,
        job_mode="sequential",
        source_benchmark=source_benchmark,
    )


def _dispatch_stage_jobs(
    *,
    runner: "BenchmarkRunner",
    jobs: Sequence[VariantJob],
    stage_scope_name: str,
    stage_label: str,
) -> None:
    """Диспачит jobs одной фазы и дожидается завершения batch."""
    _open_progress_scope_if_supported(
        runner=runner,
        scope_name=stage_scope_name,
    )
    for job in jobs:
        runner._execute_and_store(job)
    _wait_for_dispatched_tasks_if_supported(
        runner=runner,
        stage_label=stage_label,
    )


def _expected_execution_uuid_by_table(jobs: Sequence[VariantJob]) -> Dict[str, str]:
    """Строит map `{variant_table: execution_uuid}` для валидации ответов воркеров."""
    expected: Dict[str, str] = {}
    for job in jobs:
        table_name = str(job.variant_table or "").strip()
        if not table_name:
            continue
        execution_uuid = str(job.variant_meta.execution_uuid or "").strip()
        if not execution_uuid:
            continue
        expected[table_name] = execution_uuid
    return expected


def _wait_for_stage_summaries(
    *,
    store: BenchmarkResultStore,
    benchmark_run_id: int,
    benchmark_id: str,
    source_database: str,
    source_table: str,
    variant_mode: str,
    expected_variant_tables: Sequence[str],
    expected_execution_uuid_by_table: Optional[Mapping[str, str]] = None,
) -> Dict[str, StoredVariantSummary]:
    """Ждёт summary для всех variant_table (при наличии — с проверкой execution_uuid)."""
    expected = {table for table in expected_variant_tables if table}
    expected_uuids = {
        str(table_name).strip(): str(execution_uuid).strip()
        for table_name, execution_uuid in (expected_execution_uuid_by_table or {}).items()
        if str(table_name).strip() and str(execution_uuid).strip()
    }
    if not expected:
        return {}

    deadline = monotonic() + _STAGE_WAIT_TIMEOUT_SEC
    while True:
        try:
            summaries = store.list_variant_summaries(
                benchmark_run_id=benchmark_run_id,
                benchmark_id=benchmark_id,
                source_database=source_database,
                source_table=source_table,
                variant_modes=[variant_mode],
            )
        except NotImplementedError as exc:
            raise ValueError(
                "result_store не поддерживает list_variant_summaries(), "
                "что необходимо для multi-phase стратегии"
            ) from exc

        by_table: Dict[str, StoredVariantSummary] = {}
        matched_uuid_counts: Dict[tuple[str, str], int] = {}
        for summary in summaries:
            variant_table = summary.variant_table
            if variant_table not in expected:
                continue
            expected_uuid = expected_uuids.get(variant_table)
            if expected_uuid:
                summary_uuid = ""
                if isinstance(summary.variant_params, dict):
                    summary_uuid = str(
                        summary.variant_params.get("execution_uuid") or ""
                    ).strip()
                if summary_uuid != expected_uuid:
                    continue
                uuid_key = (variant_table, expected_uuid)
                matched_uuid_counts[uuid_key] = matched_uuid_counts.get(uuid_key, 0) + 1
            by_table[variant_table] = summary
        duplicate_uuid_keys = sorted(
            key for key, count in matched_uuid_counts.items() if count > 1
        )
        if duplicate_uuid_keys:
            raise ValueError(
                "Нарушена целостность phase-result correlation: найдено более одного "
                "результата для execution_uuid. "
                f"mode={variant_mode}, duplicates={duplicate_uuid_keys[:10]}"
            )
        if expected_uuids:
            missing_uuid_keys = sorted(
                (table_name, expected_uuid)
                for table_name, expected_uuid in expected_uuids.items()
                if matched_uuid_counts.get((table_name, expected_uuid), 0) != 1
            )
            if not missing_uuid_keys and len(by_table) != len(expected):
                missing_tables = sorted(expected - set(by_table))
                raise ValueError(
                    "Нарушена целостность phase-result correlation: "
                    "количество сохранённых UUID совпало, но таблицы не сошлись. "
                    f"mode={variant_mode}, missing_tables={missing_tables[:10]}"
                )
            if missing_uuid_keys:
                # продолжим polling до timeout — возможно воркеры ещё дописывают результаты.
                pass
        if len(by_table) >= len(expected):
            if expected_uuids:
                missing_uuid_keys = [
                    (table_name, expected_uuid)
                    for table_name, expected_uuid in expected_uuids.items()
                    if matched_uuid_counts.get((table_name, expected_uuid), 0) != 1
                ]
                if missing_uuid_keys:
                    # Не возвращаем неполный snapshot по UUID, продолжаем ждать.
                    pass
                else:
                    return by_table
            else:
                return by_table

        if monotonic() >= deadline:
            missing = sorted(expected - set(by_table))
            missing_uuid_keys = []
            if expected_uuids:
                missing_uuid_keys = sorted(
                    (table_name, expected_uuid)
                    for table_name, expected_uuid in expected_uuids.items()
                    if matched_uuid_counts.get((table_name, expected_uuid), 0) != 1
                )
            raise TimeoutError(
                "Ожидание результатов фазы превысило timeout: "
                f"mode={variant_mode}, expected={len(expected)}, ready={len(by_table)}, "
                f"missing={missing[:10]}, matched_by_uuid={bool(expected_uuids)}, "
                f"missing_uuid_keys={missing_uuid_keys[:10]}"
            )
        sleep(_STAGE_WAIT_POLL_INTERVAL_SEC)


def _sorted_candidates(candidates: Sequence[_PhaseCandidate]) -> List[_PhaseCandidate]:
    """Сортирует кандидаты по score (DESC), None-score в конец."""
    return sorted(
        candidates,
        key=lambda item: (
            item.score is None,
            -(item.score if item.score is not None else 0.0),
            item.variant_table,
        ),
    )


def _build_top_choice_maps(
    options_by_column: Dict[str, List[Tuple[float, Any]]],
    *,
    limit: int,
) -> List[Tuple[float, Dict[str, Any]]]:
    """
    Собирает top-N merged-комбинаций по колонкам на основе score-суммы.

    Каждая колонка имеет собственный список вариантов `(score, value)`.
    На выходе получаем top-N комбинаций `{column_name: selected_value}`.
    """
    if limit <= 0 or not options_by_column:
        return []

    merged: List[Tuple[float, Dict[str, Any]]] = [(0.0, {})]
    for column_name, options in options_by_column.items():
        if not options:
            continue
        expanded: List[Tuple[float, Dict[str, Any]]] = []
        for base_score, base_map in merged:
            for option_score, option_value in options:
                choice_map = dict(base_map)
                choice_map[column_name] = option_value
                expanded.append((base_score + float(option_score), choice_map))
        if not expanded:
            continue
        deduped: List[Tuple[float, Dict[str, Any]]] = []
        seen_keys: set[str] = set()
        for score_value, choice_map in sorted(
            expanded,
            key=lambda item: item[0],
            reverse=True,
        ):
            map_key = repr(sorted(choice_map.items()))
            if map_key in seen_keys:
                continue
            seen_keys.add(map_key)
            deduped.append((score_value, choice_map))
            if len(deduped) >= limit:
                break
        merged = deduped
        if not merged:
            break
    return merged[:limit]


def _dedupe_stage_options(
    options: Sequence[Tuple[float, Any]],
    *,
    limit: int,
) -> List[Tuple[float, Any]]:
    """Дедуплицирует stage-options, оставляя max-score вариант для каждого payload."""
    ranked = sorted(options, key=lambda item: item[0], reverse=True)
    deduped: List[Tuple[float, Any]] = []
    seen_payloads: set[str] = set()
    for score_value, payload in ranked:
        payload_key = repr(payload)
        if payload_key in seen_payloads:
            continue
        seen_payloads.add(payload_key)
        deduped.append((score_value, payload))
        if len(deduped) >= limit:
            break
    return deduped


def _finalize_stage_ranking_if_supported(
    *,
    store: BenchmarkResultStore,
    benchmark_run_id: int,
    benchmark_id: str,
    source_database: str,
    source_table: str,
    phase: Optional[int],
    variant_mode: str,
    phase_name: Optional[str],
) -> None:
    """Явно пересчитывает rank/top-N после завершения dispatch стадии, если store умеет."""
    recalc_hook = getattr(store, "recalculate_phase_ranking", None)
    if callable(recalc_hook):
        recalc_hook(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            phase=phase,
            variant_mode=variant_mode,
            phase_name=phase_name,
        )


def _mark_stage_top_n_winners_if_supported(
    *,
    store: BenchmarkResultStore,
    benchmark_run_id: int,
    benchmark_id: str,
    source_database: str,
    source_table: str,
    phase: Optional[int],
    variant_mode: str,
    phase_name: Optional[str],
    winner_variant_tables: Sequence[str],
) -> None:
    """Явно помечает `is_top_n` у вариантов, прошедших в следующий этап."""
    mark_hook = getattr(store, "mark_top_n_variant_tables", None)
    if callable(mark_hook):
        mark_hook(
            benchmark_run_id=benchmark_run_id,
            benchmark_id=benchmark_id,
            source_database=source_database,
            source_table=source_table,
            phase=phase,
            variant_mode=variant_mode,
            phase_name=phase_name,
            winner_variant_tables=list(winner_variant_tables),
        )


def _resolve_stage_top_n(
    table_plan: TableBenchmarkPlan,
    stage_mode: str,
) -> int:
    """Возвращает top-N победителей для конкретной фазы с fallback на общий top-N."""
    limits = table_plan.sequential_top_n_limits
    if limits is not None:
        stage_limit = limits.for_mode(stage_mode)
        if stage_limit is not None:
            return max(1, int(stage_limit))
        sequential_limit = limits.for_mode("sequential")
        if sequential_limit is not None:
            return max(1, int(sequential_limit))
    return max(1, int(table_plan.sequential_top_n))


def _resolve_stage_max_winners_per_parent(
    table_plan: TableBenchmarkPlan,
    stage_mode: str,
) -> int:
    """
    Возвращает лимит числа победителей на одного parent для конкретной фазы.

    По умолчанию (если лимиты не заданы) поведение совместимо с прежним кодом: 1.
    """
    limits = table_plan.max_winners_per_parent_limits
    if limits is not None:
        stage_limit = limits.for_mode(stage_mode)
        if stage_limit is not None:
            return max(1, int(stage_limit))
        sequential_limit = limits.for_mode("sequential")
        if sequential_limit is not None:
            return max(1, int(sequential_limit))
    return 1


def _resolve_stage_generation_limit(
    table_plan: TableBenchmarkPlan,
    stage_mode: str,
) -> Optional[int]:
    """
    Возвращает cap числа benchmark jobs для конкретной phased-стадии.

    Использует `max_benchmarks_limits`:
      1) limit для `stage_mode`;
      2) fallback limit для `sequential`.
    Если лимит не задан, возвращает `None` (без cap для стадии).
    """
    limits = table_plan.max_benchmarks_limits
    if limits is None:
        return None
    stage_limit = limits.for_mode(stage_mode)
    if stage_limit is not None:
        return max(1, int(stage_limit))
    sequential_limit = limits.for_mode("sequential")
    if sequential_limit is not None:
        return max(1, int(sequential_limit))
    return None


def _candidate_from_summary(
    summary: StoredVariantSummary,
    fallback_ddl: Optional[TableDDL] = None,
) -> Optional[_PhaseCandidate]:
    """Конвертирует summary из store в _PhaseCandidate."""
    try:
        ddl = TableDDL.from_ddl(summary.tested_table_ddl)
    except Exception:
        if fallback_ddl is None:
            logger.exception(
                "MultiPhaseTopN: не удалось распарсить tested_table_ddl (variant=%s)",
                summary.variant_table,
            )
            return None
        ddl = fallback_ddl.copy()
    return _PhaseCandidate(
        variant_table=summary.variant_table,
        variant_ddl=ddl,
        score=summary.score,
    )


def _build_effective_candidate_ddl(candidate: _PhaseCandidate) -> TableDDL:
    """
    Возвращает DDL кандидата с применёнными per-column choices.

    Для phased-стратегии это позволяет тестировать изменения по одной колонке
    на фоне уже выбранных лучших параметров предыдущих фаз.
    """
    ddl = candidate.variant_ddl.copy()

    for column_name, selected_type in candidate.type_choices.items():
        column = ddl.column(column_name)
        if column is None:
            continue
        column.type = selected_type
        # При смене типа codec пересчитывается на следующих фазах отдельно.
        column.codec = None

    for column_name, selected_codec in candidate.codec_choices.items():
        column = ddl.column(column_name)
        if column is None:
            continue
        column.codec = selected_codec

    for column_name, selected_index in candidate.index_choices.items():
        _remove_indexes_for_column(ddl, column_name)
        restored_index = selected_index.to_index_def()
        if restored_index is not None:
            ddl.indexes.append(restored_index.copy())

    return ddl


def _resolve_type_candidates_for_column(
    table_plan: TableBenchmarkPlan,
    column_name: str,
    current_type: str,
) -> List[str]:
    """Возвращает кандидаты типов для одной колонки."""
    candidates = [current_type]
    for rule in table_plan.rules.column_rules:
        if rule.by_name is not None and rule.by_name != column_name:
            continue
        if rule.by_type is not None and rule.by_type != current_type:
            continue
        for candidate_type in rule.alternatives.types:
            if candidate_type is None:
                continue
            normalized = candidate_type.strip()
            if not normalized:
                continue
            if normalized in candidates:
                continue
            candidates.append(normalized)
        break
    return candidates


def _resolve_codec_candidates_for_column(
    table_plan: TableBenchmarkPlan,
    column_name: str,
    current_type: str,
    current_codec: Optional[str],
) -> List[Optional[str]]:
    """Возвращает кандидаты кодеков для одной колонки."""
    candidates: list[Optional[str]] = [current_codec]
    for rule in table_plan.rules.column_rules:
        if rule.by_name is not None and rule.by_name != column_name:
            continue
        if rule.by_type is not None:
            if rule.by_type != current_type and current_type not in {
                candidate_type
                for candidate_type in rule.alternatives.types
                if candidate_type is not None
            }:
                continue
        for codec in rule.alternatives.codecs:
            normalized = codec.strip() if isinstance(codec, str) else None
            if normalized == "":
                normalized = None
            if normalized in candidates:
                continue
            candidates.append(normalized)
        break
    return candidates


def _resolve_index_options_for_column(
    *,
    table_plan: TableBenchmarkPlan,
    base_ddl: TableDDL,
    column_name: str,
) -> List[_IndexJobContext]:
    """Возвращает варианты (index_def, table_index_granularity) для одной колонки."""
    column = base_ddl.column(column_name)
    if column is None:
        return []

    alternatives = None
    for rule in table_plan.rules.index_rules:
        if not rule.matches(column):
            continue
        alternatives = rule.alternatives
        break
    if alternatives is None:
        return []

    current_table_granularity = base_ddl.get_index_granularity()
    global_granularity_values = list(table_plan.index_granularity_values or [])
    options: list[_IndexJobContext] = []

    # Вариант без индекса для колонки (нужен для решения "оставить без индекса").
    options.append(
        _IndexJobContext(
            parent_variant_table="",
            column_name=column_name,
            index_def=None,
            table_index_granularity=current_table_granularity,
            allowed_table_index_granularity_values=(
                [current_table_granularity] if current_table_granularity is not None else None
            ),
        )
    )

    for idx_num, variant in enumerate(alternatives.variants):
        index_def = variant.to_index_def(column, idx_num)
        per_index_values = list(variant.table_index_granularity_values or [])

        if global_granularity_values and per_index_values:
            allowed = set(per_index_values)
            resolved_granularities = [
                value for value in global_granularity_values if value in allowed
            ]
        elif global_granularity_values:
            resolved_granularities = list(global_granularity_values)
        elif per_index_values:
            resolved_granularities = list(per_index_values)
        elif current_table_granularity is not None:
            resolved_granularities = [current_table_granularity]
        else:
            resolved_granularities = [None]

        allowed_values = [
            int(value)
            for value in resolved_granularities
            if value is not None
        ]
        for table_index_granularity in resolved_granularities:
            options.append(
                _IndexJobContext(
                    parent_variant_table="",
                    column_name=column_name,
                    index_def=index_def.copy(),
                    table_index_granularity=table_index_granularity,
                    allowed_table_index_granularity_values=(
                        allowed_values if allowed_values else None
                    ),
                )
            )
    return options


def _remove_indexes_for_column(ddl: TableDDL, column_name: str) -> None:
    """Удаляет skip-индексы, привязанные к конкретной колонке."""
    ddl.indexes = [index for index in ddl.indexes if index.expr != column_name]


class SequentialPhasedTopNTableExecutionStrategy(TableExecutionStrategy):
    """
    Многофазная стратегия:
    ORDER BY -> types -> codecs -> indexes -> final validation.
    """

    def execute_table(
        self,
        runner: "BenchmarkRunner",
        table_plan: TableBenchmarkPlan,
        benchmark_run_id: int,
        benchmark_started_at: datetime,
    ) -> None:
        store = _require_result_store(runner, strategy_key=table_plan.strategy)
        source_benchmark = runner._require_active_source_benchmark()
        source_ddl, raw_query_plan, _ = _prepare_table_context(
            runner=runner,
            table_plan=table_plan,
        )
        top_n_order_by = _resolve_stage_top_n(table_plan, "order_by")
        top_n_types = _resolve_stage_top_n(table_plan, "types")
        top_n_codecs = _resolve_stage_top_n(table_plan, "codecs")
        top_n_indexes = _resolve_stage_top_n(table_plan, "indexes")
        top_n_final_validation = _resolve_stage_top_n(table_plan, "final_validation")
        max_winners_per_parent_types = _resolve_stage_max_winners_per_parent(
            table_plan,
            "types",
        )
        max_winners_per_parent_codecs = _resolve_stage_max_winners_per_parent(
            table_plan,
            "codecs",
        )
        max_winners_per_parent_indexes = _resolve_stage_max_winners_per_parent(
            table_plan,
            "indexes",
        )
        stage_generation_limit_types = _resolve_stage_generation_limit(
            table_plan,
            "types",
        )
        stage_generation_limit_codecs = _resolve_stage_generation_limit(
            table_plan,
            "codecs",
        )
        stage_generation_limit_indexes = _resolve_stage_generation_limit(
            table_plan,
            "indexes",
        )
        stage_generation_limit_final_validation = _resolve_stage_generation_limit(
            table_plan,
            "final_validation",
        )
        global_index_counter = [0]

        logger.info(
            "SequentialPhasedTopN: старт стратегии "
            "(run_id=%d, benchmark=%s, table=%s.%s, "
            "top_n_order_by=%d, top_n_types=%d, top_n_codecs=%d, "
            "top_n_indexes=%d, top_n_final_validation=%d, "
            "max_winners_per_parent_types=%d, "
            "max_winners_per_parent_codecs=%d, "
            "max_winners_per_parent_indexes=%d, "
            "stage_generation_limit_types=%s, "
            "stage_generation_limit_codecs=%s, "
            "stage_generation_limit_indexes=%s, "
            "stage_generation_limit_final_validation=%s)",
            benchmark_run_id,
            table_plan.benchmark_id,
            table_plan.database,
            table_plan.table,
            top_n_order_by,
            top_n_types,
            top_n_codecs,
            top_n_indexes,
            top_n_final_validation,
            max_winners_per_parent_types,
            max_winners_per_parent_codecs,
            max_winners_per_parent_indexes,
            stage_generation_limit_types,
            stage_generation_limit_codecs,
            stage_generation_limit_indexes,
            stage_generation_limit_final_validation,
        )

        # ------------------------------------------------------------------
        # Фаза 1: ORDER BY
        # ------------------------------------------------------------------
        order_by_expressions = _build_order_by_candidates(
            runner=runner,
            table_plan=table_plan,
            source_ddl=source_ddl,
            raw_query_plan=raw_query_plan,
        )
        if not order_by_expressions:
            logger.warning(
                "SequentialPhasedTopN: фаза ORDER BY пропущена, кандидаты не найдены "
                "(run_id=%d, benchmark=%s, table=%s.%s)",
                benchmark_run_id,
                table_plan.benchmark_id,
                table_plan.database,
                table_plan.table,
            )
            return

        _log_stage_banner(
            stage_name="ORDER BY (phase 1)",
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            database=table_plan.database,
            table=table_plan.table,
        )
        order_jobs: list[VariantJob] = []
        order_job_ddls_by_table: dict[str, TableDDL] = {}
        for order_expression in order_by_expressions:
            variant_ddl = source_ddl.copy()
            _reset_all_codecs_to_default(variant_ddl)
            variant_ddl.order_by = order_expression
            job = _build_job(
                runner=runner,
                table_plan=table_plan,
                raw_query_plan=raw_query_plan,
                variant_ddl=variant_ddl,
                variant_mode="order_by",
                phase_name="ORDER BY",
                total_variants=len(order_by_expressions),
                benchmark_run_id=benchmark_run_id,
                benchmark_started_at=benchmark_started_at,
                source_benchmark=source_benchmark,
                global_index_counter=global_index_counter,
            )
            order_jobs.append(job)
            order_job_ddls_by_table[job.variant_table] = variant_ddl.copy()

        _dispatch_stage_jobs(
            runner=runner,
            jobs=order_jobs,
            stage_scope_name=(
                f"phase1 order_by: {table_plan.benchmark_id} "
                f"{table_plan.database}.{table_plan.table}"
            ),
            stage_label=(
                f"phase1 order_by: {table_plan.benchmark_id} "
                f"{table_plan.database}.{table_plan.table}"
            ),
        )
        order_summaries = _wait_for_stage_summaries(
            store=store,
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            source_database=table_plan.database,
            source_table=table_plan.table,
            variant_mode="order_by",
            expected_variant_tables=[job.variant_table for job in order_jobs],
            expected_execution_uuid_by_table=_expected_execution_uuid_by_table(
                order_jobs
            ),
        )
        _finalize_stage_ranking_if_supported(
            store=store,
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            source_database=table_plan.database,
            source_table=table_plan.table,
            phase=1,
            variant_mode="order_by",
            phase_name="ORDER BY",
        )
        order_candidates: list[_PhaseCandidate] = []
        for variant_table, summary in order_summaries.items():
            candidate = _candidate_from_summary(
                summary,
                fallback_ddl=order_job_ddls_by_table.get(variant_table),
            )
            if candidate is not None:
                order_candidates.append(candidate)
        order_winners = _sorted_candidates(order_candidates)[:top_n_order_by]
        if not order_winners:
            logger.warning(
                "SequentialPhasedTopN: фаза ORDER BY не вернула победителей "
                "(run_id=%d, benchmark=%s, table=%s.%s)",
                benchmark_run_id,
                table_plan.benchmark_id,
                table_plan.database,
                table_plan.table,
            )
            return
        _mark_stage_top_n_winners_if_supported(
            store=store,
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            source_database=table_plan.database,
            source_table=table_plan.table,
            phase=1,
            variant_mode="order_by",
            phase_name="ORDER BY",
            winner_variant_tables=[candidate.variant_table for candidate in order_winners],
        )

        # ------------------------------------------------------------------
        # Фаза 2: TYPE (one-column selection)
        # ------------------------------------------------------------------
        _log_stage_banner(
            stage_name="ТИПЫ ДАННЫХ (phase 2)",
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            database=table_plan.database,
            table=table_plan.table,
        )
        type_winners: list[_PhaseCandidate] = []
        remaining_type_stage_budget = stage_generation_limit_types
        for parent in order_winners:
            if remaining_type_stage_budget is not None and remaining_type_stage_budget <= 0:
                type_winners.append(parent)
                continue
            base_ddl = _build_effective_candidate_ddl(parent)
            jobs: list[VariantJob] = []
            context_by_variant_table: dict[str, _TypeJobContext] = {}

            for column in base_ddl.columns:
                if remaining_type_stage_budget is not None and remaining_type_stage_budget <= 0:
                    break
                type_candidates = _resolve_type_candidates_for_column(
                    table_plan=table_plan,
                    column_name=column.name,
                    current_type=column.type,
                )
                if len(type_candidates) <= 1:
                    continue
                for tested_type in type_candidates:
                    if (
                        remaining_type_stage_budget is not None
                        and remaining_type_stage_budget <= 0
                    ):
                        break
                    variant_ddl = base_ddl.copy()
                    tested_column = variant_ddl.column(column.name)
                    if tested_column is None:
                        continue
                    tested_column.type = tested_type
                    tested_column.codec = None
                    column_meta = ColumnVariantMeta(
                        index=0,
                        column_choices={column.name: (tested_type, tested_column.codec)},
                    )
                    job = _build_job(
                        runner=runner,
                        table_plan=table_plan,
                        raw_query_plan=raw_query_plan,
                        variant_ddl=variant_ddl,
                        variant_mode="types",
                        phase_name="types",
                        total_variants=max(1, len(type_candidates)),
                        benchmark_run_id=benchmark_run_id,
                        benchmark_started_at=benchmark_started_at,
                        source_benchmark=source_benchmark,
                        global_index_counter=global_index_counter,
                        column_meta=column_meta,
                        parent_variant_table=parent.variant_table,
                        stage_column_name=column.name,
                    )
                    jobs.append(job)
                    context_by_variant_table[job.variant_table] = _TypeJobContext(
                        parent_variant_table=parent.variant_table,
                        column_name=column.name,
                        tested_type=tested_type,
                    )
                    if remaining_type_stage_budget is not None:
                        remaining_type_stage_budget -= 1

            if not jobs:
                type_winners.append(parent)
                continue

            stage_scope = (
                f"phase2 types: {table_plan.benchmark_id} "
                f"{table_plan.database}.{table_plan.table} parent={parent.variant_table}"
            )
            _dispatch_stage_jobs(
                runner=runner,
                jobs=jobs,
                stage_scope_name=stage_scope,
                stage_label=stage_scope,
            )
            summaries = _wait_for_stage_summaries(
                store=store,
                benchmark_run_id=benchmark_run_id,
                benchmark_id=table_plan.benchmark_id,
                source_database=table_plan.database,
                source_table=table_plan.table,
                variant_mode="types",
                expected_variant_tables=[job.variant_table for job in jobs],
                expected_execution_uuid_by_table=_expected_execution_uuid_by_table(
                    jobs
                ),
            )
            _finalize_stage_ranking_if_supported(
                store=store,
                benchmark_run_id=benchmark_run_id,
                benchmark_id=table_plan.benchmark_id,
                source_database=table_plan.database,
                source_table=table_plan.table,
                phase=2,
                variant_mode="types",
                phase_name="types",
            )

            options_by_column: dict[str, list[tuple[float, tuple[str, str]]]] = {}
            for variant_table, summary in summaries.items():
                context = context_by_variant_table.get(variant_table)
                if context is None or summary.score is None:
                    continue
                score_value = float(summary.score)
                options_by_column.setdefault(context.column_name, []).append(
                    (score_value, (context.tested_type, variant_table))
                )

            if not options_by_column:
                type_winners.append(parent)
                continue

            limited_options_by_column: dict[
                str,
                list[tuple[float, tuple[str, str]]],
            ] = {}
            for column_name, options in options_by_column.items():
                deduped = _dedupe_stage_options(
                    options,
                    limit=max_winners_per_parent_types,
                )
                if not deduped:
                    continue
                limited_options_by_column[column_name] = deduped
            if not limited_options_by_column:
                type_winners.append(parent)
                continue

            merged_choice_candidates = _build_top_choice_maps(
                limited_options_by_column,
                limit=max_winners_per_parent_types,
            )
            if not merged_choice_candidates:
                type_winners.append(parent)
                continue

            for merged_score, choice_map in merged_choice_candidates:
                updated_type_choices = dict(parent.type_choices)
                updated_codec_choices = dict(parent.codec_choices)
                representative_variant_table = parent.variant_table
                for column_name, (selected_type, option_variant_table) in sorted(
                    choice_map.items()
                ):
                    updated_type_choices[column_name] = selected_type
                    updated_codec_choices.pop(column_name, None)
                    representative_variant_table = option_variant_table
                phase_score = (
                    float(merged_score) / float(max(1, len(choice_map)))
                    if choice_map
                    else parent.score
                )
                type_winners.append(
                    _PhaseCandidate(
                        variant_table=representative_variant_table,
                        variant_ddl=parent.variant_ddl.copy(),
                        score=phase_score,
                        type_choices=updated_type_choices,
                        codec_choices=updated_codec_choices,
                        index_choices=dict(parent.index_choices),
                    )
                )

        type_winners = _sorted_candidates(type_winners)[:top_n_types]
        if not type_winners:
            logger.warning(
                "SequentialPhasedTopN: фаза TYPE не вернула победителей "
                "(run_id=%d, benchmark=%s, table=%s.%s)",
                benchmark_run_id,
                table_plan.benchmark_id,
                table_plan.database,
                table_plan.table,
            )
            return
        _mark_stage_top_n_winners_if_supported(
            store=store,
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            source_database=table_plan.database,
            source_table=table_plan.table,
            phase=2,
            variant_mode="types",
            phase_name="types",
            winner_variant_tables=[candidate.variant_table for candidate in type_winners],
        )

        # ------------------------------------------------------------------
        # Фаза 3: CODEC (one-column selection)
        # ------------------------------------------------------------------
        _log_stage_banner(
            stage_name="КОДЕКИ (phase 3)",
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            database=table_plan.database,
            table=table_plan.table,
        )
        codec_winners: list[_PhaseCandidate] = []
        remaining_codec_stage_budget = stage_generation_limit_codecs
        for parent in type_winners:
            if remaining_codec_stage_budget is not None and remaining_codec_stage_budget <= 0:
                codec_winners.append(parent)
                continue
            base_ddl = _build_effective_candidate_ddl(parent)
            jobs: list[VariantJob] = []
            context_by_variant_table: dict[str, _CodecJobContext] = {}

            for column in base_ddl.columns:
                if remaining_codec_stage_budget is not None and remaining_codec_stage_budget <= 0:
                    break
                codec_candidates = _resolve_codec_candidates_for_column(
                    table_plan=table_plan,
                    column_name=column.name,
                    current_type=column.type,
                    current_codec=column.codec,
                )
                if len(codec_candidates) <= 1:
                    continue
                for tested_codec in codec_candidates:
                    if (
                        remaining_codec_stage_budget is not None
                        and remaining_codec_stage_budget <= 0
                    ):
                        break
                    variant_ddl = base_ddl.copy()
                    tested_column = variant_ddl.column(column.name)
                    if tested_column is None:
                        continue
                    tested_column.codec = tested_codec
                    column_meta = ColumnVariantMeta(
                        index=0,
                        column_choices={column.name: (tested_column.type, tested_codec)},
                    )
                    job = _build_job(
                        runner=runner,
                        table_plan=table_plan,
                        raw_query_plan=raw_query_plan,
                        variant_ddl=variant_ddl,
                        variant_mode="codecs",
                        phase_name="codecs",
                        total_variants=max(1, len(codec_candidates)),
                        benchmark_run_id=benchmark_run_id,
                        benchmark_started_at=benchmark_started_at,
                        source_benchmark=source_benchmark,
                        global_index_counter=global_index_counter,
                        column_meta=column_meta,
                        parent_variant_table=parent.variant_table,
                        stage_column_name=column.name,
                    )
                    jobs.append(job)
                    context_by_variant_table[job.variant_table] = _CodecJobContext(
                        parent_variant_table=parent.variant_table,
                        column_name=column.name,
                        tested_codec=tested_codec,
                    )
                    if remaining_codec_stage_budget is not None:
                        remaining_codec_stage_budget -= 1

            if not jobs:
                codec_winners.append(parent)
                continue

            stage_scope = (
                f"phase3 codecs: {table_plan.benchmark_id} "
                f"{table_plan.database}.{table_plan.table} parent={parent.variant_table}"
            )
            _dispatch_stage_jobs(
                runner=runner,
                jobs=jobs,
                stage_scope_name=stage_scope,
                stage_label=stage_scope,
            )
            summaries = _wait_for_stage_summaries(
                store=store,
                benchmark_run_id=benchmark_run_id,
                benchmark_id=table_plan.benchmark_id,
                source_database=table_plan.database,
                source_table=table_plan.table,
                variant_mode="codecs",
                expected_variant_tables=[job.variant_table for job in jobs],
                expected_execution_uuid_by_table=_expected_execution_uuid_by_table(
                    jobs
                ),
            )
            _finalize_stage_ranking_if_supported(
                store=store,
                benchmark_run_id=benchmark_run_id,
                benchmark_id=table_plan.benchmark_id,
                source_database=table_plan.database,
                source_table=table_plan.table,
                phase=3,
                variant_mode="codecs",
                phase_name="codecs",
            )

            options_by_column: dict[str, list[tuple[float, tuple[Optional[str], str]]]] = {}
            for variant_table, summary in summaries.items():
                context = context_by_variant_table.get(variant_table)
                if context is None or summary.score is None:
                    continue
                score_value = float(summary.score)
                options_by_column.setdefault(context.column_name, []).append(
                    (score_value, (context.tested_codec, variant_table))
                )
            if not options_by_column:
                codec_winners.append(parent)
                continue

            limited_options_by_column: dict[
                str,
                list[tuple[float, tuple[Optional[str], str]]],
            ] = {}
            for column_name, options in options_by_column.items():
                deduped = _dedupe_stage_options(
                    options,
                    limit=max_winners_per_parent_codecs,
                )
                if not deduped:
                    continue
                limited_options_by_column[column_name] = deduped
            if not limited_options_by_column:
                codec_winners.append(parent)
                continue

            merged_choice_candidates = _build_top_choice_maps(
                limited_options_by_column,
                limit=max_winners_per_parent_codecs,
            )
            if not merged_choice_candidates:
                codec_winners.append(parent)
                continue

            for merged_score, choice_map in merged_choice_candidates:
                updated_codec_choices = dict(parent.codec_choices)
                representative_variant_table = parent.variant_table
                for column_name, (selected_codec, option_variant_table) in sorted(
                    choice_map.items()
                ):
                    updated_codec_choices[column_name] = selected_codec
                    representative_variant_table = option_variant_table
                phase_score = (
                    float(merged_score) / float(max(1, len(choice_map)))
                    if choice_map
                    else parent.score
                )
                codec_winners.append(
                    _PhaseCandidate(
                        variant_table=representative_variant_table,
                        variant_ddl=parent.variant_ddl.copy(),
                        score=phase_score,
                        type_choices=dict(parent.type_choices),
                        codec_choices=updated_codec_choices,
                        index_choices=dict(parent.index_choices),
                    )
                )

        codec_winners = _sorted_candidates(codec_winners)[:top_n_codecs]
        if not codec_winners:
            logger.warning(
                "SequentialPhasedTopN: фаза CODEC не вернула победителей "
                "(run_id=%d, benchmark=%s, table=%s.%s)",
                benchmark_run_id,
                table_plan.benchmark_id,
                table_plan.database,
                table_plan.table,
            )
            return
        _mark_stage_top_n_winners_if_supported(
            store=store,
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            source_database=table_plan.database,
            source_table=table_plan.table,
            phase=3,
            variant_mode="codecs",
            phase_name="codecs",
            winner_variant_tables=[candidate.variant_table for candidate in codec_winners],
        )

        # ------------------------------------------------------------------
        # Фаза 4: INDEX (one-column selection)
        # ------------------------------------------------------------------
        _log_stage_banner(
            stage_name="DATA SKIPPING ИНДЕКСЫ (phase 4)",
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            database=table_plan.database,
            table=table_plan.table,
        )
        index_winners: list[_PhaseCandidate] = []
        remaining_index_stage_budget = stage_generation_limit_indexes
        for parent in codec_winners:
            if remaining_index_stage_budget is not None and remaining_index_stage_budget <= 0:
                index_winners.append(parent)
                continue
            base_ddl = _build_effective_candidate_ddl(parent)
            order_by_components = {
                _normalize_identifier(component)
                for component in _parse_order_by_components(base_ddl.order_by)
            }
            query_filter_columns = _extract_filter_columns_from_query_plan(
                raw_query_plan,
                [column.name for column in base_ddl.columns],
            )
            candidate_columns = [
                column_name
                for column_name in query_filter_columns
                if column_name not in order_by_components
            ]
            if not candidate_columns:
                candidate_columns = [
                    column.name
                    for column in base_ddl.columns
                    if column.name not in order_by_components
                ]

            jobs: list[VariantJob] = []
            context_by_variant_table: dict[str, _IndexJobContext] = {}
            for column_name in candidate_columns:
                if remaining_index_stage_budget is not None and remaining_index_stage_budget <= 0:
                    break
                options = _resolve_index_options_for_column(
                    table_plan=table_plan,
                    base_ddl=base_ddl,
                    column_name=column_name,
                )
                for option in options:
                    if (
                        remaining_index_stage_budget is not None
                        and remaining_index_stage_budget <= 0
                    ):
                        break
                    index_def = option.index_def.copy() if option.index_def is not None else None
                    table_index_granularity = option.table_index_granularity
                    variant_ddl = base_ddl.copy()
                    _remove_indexes_for_column(variant_ddl, column_name)
                    if index_def is not None:
                        variant_ddl.indexes.append(index_def.copy())
                    if table_index_granularity is not None:
                        variant_ddl.set_index_granularity(table_index_granularity)
                    index_choices = {
                        column_name: index_def.copy() if index_def is not None else None
                    }
                    index_meta = IndexVariantMeta(
                        index=0,
                        index_choices=index_choices,
                        table_index_granularity=table_index_granularity,
                    )
                    job = _build_job(
                        runner=runner,
                        table_plan=table_plan,
                        raw_query_plan=raw_query_plan,
                        variant_ddl=variant_ddl,
                        variant_mode="indexes",
                        phase_name="indexes",
                        total_variants=max(1, len(options)),
                        benchmark_run_id=benchmark_run_id,
                        benchmark_started_at=benchmark_started_at,
                        source_benchmark=source_benchmark,
                        global_index_counter=global_index_counter,
                        index_meta=index_meta,
                        table_index_granularity=table_index_granularity,
                        parent_variant_table=parent.variant_table,
                        stage_column_name=column_name,
                    )
                    jobs.append(job)
                    context_by_variant_table[job.variant_table] = _IndexJobContext(
                        parent_variant_table=parent.variant_table,
                        column_name=column_name,
                        index_def=index_def.copy() if index_def is not None else None,
                        table_index_granularity=table_index_granularity,
                        allowed_table_index_granularity_values=(
                            list(option.allowed_table_index_granularity_values)
                            if option.allowed_table_index_granularity_values is not None
                            else None
                        ),
                    )
                    if remaining_index_stage_budget is not None:
                        remaining_index_stage_budget -= 1

            if not jobs:
                index_winners.append(parent)
                continue

            stage_scope = (
                f"phase4 indexes: {table_plan.benchmark_id} "
                f"{table_plan.database}.{table_plan.table} parent={parent.variant_table}"
            )
            _dispatch_stage_jobs(
                runner=runner,
                jobs=jobs,
                stage_scope_name=stage_scope,
                stage_label=stage_scope,
            )
            summaries = _wait_for_stage_summaries(
                store=store,
                benchmark_run_id=benchmark_run_id,
                benchmark_id=table_plan.benchmark_id,
                source_database=table_plan.database,
                source_table=table_plan.table,
                variant_mode="indexes",
                expected_variant_tables=[job.variant_table for job in jobs],
                expected_execution_uuid_by_table=_expected_execution_uuid_by_table(
                    jobs
                ),
            )
            _finalize_stage_ranking_if_supported(
                store=store,
                benchmark_run_id=benchmark_run_id,
                benchmark_id=table_plan.benchmark_id,
                source_database=table_plan.database,
                source_table=table_plan.table,
                phase=4,
                variant_mode="indexes",
                phase_name="indexes",
            )

            options_by_column: dict[str, list[tuple[float, tuple[_IndexColumnChoice, str]]]] = {}
            for variant_table, summary in summaries.items():
                context = context_by_variant_table.get(variant_table)
                if context is None or summary.score is None:
                    continue
                score_value = float(summary.score)
                column_choice = _IndexColumnChoice.from_context(context)
                options_by_column.setdefault(context.column_name, []).append(
                    (score_value, (column_choice, variant_table))
                )
            if not options_by_column:
                index_winners.append(parent)
                continue

            limited_options_by_column: dict[
                str,
                list[tuple[float, tuple[_IndexColumnChoice, str]]],
            ] = {}
            for column_name, options in options_by_column.items():
                deduped = _dedupe_stage_options(
                    options,
                    limit=max_winners_per_parent_indexes,
                )
                if not deduped:
                    continue
                limited_options_by_column[column_name] = deduped
            if not limited_options_by_column:
                index_winners.append(parent)
                continue

            merged_choice_candidates = _build_top_choice_maps(
                limited_options_by_column,
                limit=max_winners_per_parent_indexes,
            )
            if not merged_choice_candidates:
                index_winners.append(parent)
                continue

            for merged_score, choice_map in merged_choice_candidates:
                updated_index_choices = dict(parent.index_choices)
                representative_variant_table = parent.variant_table
                for column_name, (selected_index_choice, option_variant_table) in sorted(
                    choice_map.items()
                ):
                    updated_index_choices[column_name] = selected_index_choice
                    representative_variant_table = option_variant_table
                phase_score = (
                    float(merged_score) / float(max(1, len(choice_map)))
                    if choice_map
                    else parent.score
                )
                index_winners.append(
                    _PhaseCandidate(
                        variant_table=representative_variant_table,
                        variant_ddl=parent.variant_ddl.copy(),
                        score=phase_score,
                        type_choices=dict(parent.type_choices),
                        codec_choices=dict(parent.codec_choices),
                        index_choices=updated_index_choices,
                    )
                )

        index_winners = _sorted_candidates(index_winners)[:top_n_indexes]
        if not index_winners:
            logger.warning(
                "SequentialPhasedTopN: фаза INDEX не вернула победителей "
                "(run_id=%d, benchmark=%s, table=%s.%s)",
                benchmark_run_id,
                table_plan.benchmark_id,
                table_plan.database,
                table_plan.table,
            )
            return
        _mark_stage_top_n_winners_if_supported(
            store=store,
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            source_database=table_plan.database,
            source_table=table_plan.table,
            phase=4,
            variant_mode="indexes",
            phase_name="indexes",
            winner_variant_tables=[candidate.variant_table for candidate in index_winners],
        )

        # ------------------------------------------------------------------
        # Фаза 5: финальная валидация
        # ------------------------------------------------------------------
        _log_stage_banner(
            stage_name="ФИНАЛЬНАЯ ВАЛИДАЦИЯ (phase 5)",
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            database=table_plan.database,
            table=table_plan.table,
        )
        final_jobs: list[VariantJob] = []
        fallback_ddls_by_table: dict[str, TableDDL] = {}
        final_candidates_source = index_winners[:top_n_final_validation]
        remaining_final_stage_budget = stage_generation_limit_final_validation
        for candidate in final_candidates_source:
            if remaining_final_stage_budget is not None and remaining_final_stage_budget <= 0:
                break
            assembled_ddl = _build_effective_candidate_ddl(candidate)
            preferred_granularity_candidates: list[int] = []
            granularity_constraints: list[set[int]] = []
            for index_choice in candidate.index_choices.values():
                if index_choice.preferred_table_index_granularity is not None:
                    preferred_granularity_candidates.append(
                        int(index_choice.preferred_table_index_granularity)
                    )
                if index_choice.allowed_table_index_granularity_values:
                    granularity_constraints.append(
                        {
                            int(value)
                            for value in index_choice.allowed_table_index_granularity_values
                        }
                    )

            table_granularity_candidates = list(table_plan.index_granularity_values or [])
            if table_granularity_candidates and granularity_constraints:
                allowed = set(table_granularity_candidates)
                for constraint in granularity_constraints:
                    allowed &= constraint
                table_granularity_candidates = [
                    value for value in table_granularity_candidates if value in allowed
                ]

            if not table_granularity_candidates and granularity_constraints:
                intersection = set.intersection(*granularity_constraints)
                table_granularity_candidates = sorted(intersection) if intersection else []

            if not table_granularity_candidates:
                deduped_preferred: list[int] = []
                seen_preferred: set[int] = set()
                for value in preferred_granularity_candidates:
                    if value in seen_preferred:
                        continue
                    seen_preferred.add(value)
                    deduped_preferred.append(value)
                table_granularity_candidates = deduped_preferred

            if not table_granularity_candidates:
                table_granularity_candidates = [None]

            for table_granularity in table_granularity_candidates:
                if (
                    remaining_final_stage_budget is not None
                    and remaining_final_stage_budget <= 0
                ):
                    break
                final_ddl = assembled_ddl.copy()
                if table_granularity is not None:
                    final_ddl.set_index_granularity(int(table_granularity))
                job = _build_job(
                    runner=runner,
                    table_plan=table_plan,
                    raw_query_plan=raw_query_plan,
                    variant_ddl=final_ddl,
                    variant_mode="final_validation",
                    phase_name="final_validation",
                    total_variants=max(1, len(table_granularity_candidates)),
                    benchmark_run_id=benchmark_run_id,
                    benchmark_started_at=benchmark_started_at,
                    source_benchmark=source_benchmark,
                    global_index_counter=global_index_counter,
                    parent_variant_table=candidate.variant_table,
                    merged_columns=sorted(
                        {
                            *candidate.type_choices.keys(),
                            *candidate.codec_choices.keys(),
                            *candidate.index_choices.keys(),
                        }
                    ),
                )
                final_jobs.append(job)
                fallback_ddls_by_table[job.variant_table] = final_ddl.copy()
                if remaining_final_stage_budget is not None:
                    remaining_final_stage_budget -= 1

        final_scope = (
            f"phase5 final: {table_plan.benchmark_id} "
            f"{table_plan.database}.{table_plan.table}"
        )
        _dispatch_stage_jobs(
            runner=runner,
            jobs=final_jobs,
            stage_scope_name=final_scope,
            stage_label=final_scope,
        )
        final_summaries = _wait_for_stage_summaries(
            store=store,
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            source_database=table_plan.database,
            source_table=table_plan.table,
            variant_mode="final_validation",
            expected_variant_tables=[job.variant_table for job in final_jobs],
            expected_execution_uuid_by_table=_expected_execution_uuid_by_table(
                final_jobs
            ),
        )
        _finalize_stage_ranking_if_supported(
            store=store,
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            source_database=table_plan.database,
            source_table=table_plan.table,
            phase=5,
            variant_mode="final_validation",
            phase_name="final_validation",
        )
        final_candidates: list[_PhaseCandidate] = []
        for variant_table, summary in final_summaries.items():
            candidate = _candidate_from_summary(
                summary,
                fallback_ddl=fallback_ddls_by_table.get(variant_table),
            )
            if candidate is not None:
                final_candidates.append(candidate)
        final_ranked = _sorted_candidates(final_candidates)
        if not final_ranked:
            logger.warning(
                "SequentialPhasedTopN: финальная валидация не вернула результатов "
                "(run_id=%d, benchmark=%s, table=%s.%s)",
                benchmark_run_id,
                table_plan.benchmark_id,
                table_plan.database,
                table_plan.table,
            )
            return
        _mark_stage_top_n_winners_if_supported(
            store=store,
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            source_database=table_plan.database,
            source_table=table_plan.table,
            phase=5,
            variant_mode="final_validation",
            phase_name="final_validation",
            winner_variant_tables=[
                candidate.variant_table
                for candidate in final_ranked[:max(1, top_n_final_validation)]
            ],
        )
        winner = final_ranked[0]
        logger.info(
            "SequentialPhasedTopN: победитель найден "
            "(run_id=%d, benchmark=%s, table=%s.%s, variant=%s, score=%s)",
            benchmark_run_id,
            table_plan.benchmark_id,
            table_plan.database,
            table_plan.table,
            winner.variant_table,
            winner.score,
        )
