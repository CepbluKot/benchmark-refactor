"""Реализация многофазной top-N стратегии для ClickHouse."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import itertools
import logging
import re
from time import monotonic, sleep
from typing import TYPE_CHECKING, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

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
) -> VariantJob:
    """Строит VariantJob с нужным phase-mode."""
    variant_meta = VariantMeta(
        global_index=_next_global_index(global_index_counter),
        mode=variant_mode,
        parent_variant_table=parent_variant_table,
        phase_name=phase_name,
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


def _wait_for_stage_summaries(
    *,
    store: BenchmarkResultStore,
    benchmark_run_id: int,
    benchmark_id: str,
    source_database: str,
    source_table: str,
    variant_mode: str,
    expected_variant_tables: Sequence[str],
) -> Dict[str, StoredVariantSummary]:
    """Ждёт, пока result-store вернёт summary для всех переданных variant_table."""
    expected = {table for table in expected_variant_tables if table}
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

        by_table = {
            summary.variant_table: summary
            for summary in summaries
            if summary.variant_table in expected
        }
        if len(by_table) >= len(expected):
            return by_table

        if monotonic() >= deadline:
            missing = sorted(expected - set(by_table))
            raise TimeoutError(
                "Ожидание результатов фазы превысило timeout: "
                f"mode={variant_mode}, expected={len(expected)}, ready={len(by_table)}, "
                f"missing={missing[:10]}"
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
        top_n = max(1, int(table_plan.sequential_top_n))
        global_index_counter = [0]

        logger.info(
            "SequentialPhasedTopN: старт стратегии "
            "(run_id=%d, benchmark=%s, table=%s.%s, top_n=%d)",
            benchmark_run_id,
            table_plan.benchmark_id,
            table_plan.database,
            table_plan.table,
            top_n,
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
        )
        order_candidates: list[_PhaseCandidate] = []
        for variant_table, summary in order_summaries.items():
            candidate = _candidate_from_summary(
                summary,
                fallback_ddl=order_job_ddls_by_table.get(variant_table),
            )
            if candidate is not None:
                order_candidates.append(candidate)
        order_winners = _sorted_candidates(order_candidates)[:top_n]
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

        # ------------------------------------------------------------------
        # Фаза 2: TYPE
        # ------------------------------------------------------------------
        _log_stage_banner(
            stage_name="ТИПЫ ДАННЫХ (phase 2)",
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            database=table_plan.database,
            table=table_plan.table,
        )
        type_winners: list[_PhaseCandidate] = []
        for parent in order_winners:
            base_ddl = parent.variant_ddl.copy()
            jobs: list[VariantJob] = []
            context_by_variant_table: dict[str, _TypeJobContext] = {}

            for column in base_ddl.columns:
                type_candidates = _resolve_type_candidates_for_column(
                    table_plan=table_plan,
                    column_name=column.name,
                    current_type=column.type,
                )
                if len(type_candidates) <= 1:
                    continue
                for tested_type in type_candidates:
                    variant_ddl = base_ddl.copy()
                    tested_column = variant_ddl.column(column.name)
                    if tested_column is None:
                        continue
                    tested_column.type = tested_type
                    tested_column.codec = None
                    column_meta = ColumnVariantMeta(
                        index=0,
                        column_choices={
                            column.name: (tested_type, tested_column.codec)
                        },
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
                    )
                    jobs.append(job)
                    context_by_variant_table[job.variant_table] = _TypeJobContext(
                        parent_variant_table=parent.variant_table,
                        column_name=column.name,
                        tested_type=tested_type,
                    )

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
            )

            best_by_column: dict[str, tuple[float, str]] = {}
            for variant_table, summary in summaries.items():
                context = context_by_variant_table.get(variant_table)
                if context is None or summary.score is None:
                    continue
                existing = best_by_column.get(context.column_name)
                if existing is None or summary.score > existing[0]:
                    best_by_column[context.column_name] = (
                        float(summary.score),
                        context.tested_type,
                    )

            assembled_ddl = base_ddl.copy()
            for column_name, (_, best_type) in best_by_column.items():
                column = assembled_ddl.column(column_name)
                if column is None:
                    continue
                column.type = best_type
                column.codec = None

            validation_job = _build_job(
                runner=runner,
                table_plan=table_plan,
                raw_query_plan=raw_query_plan,
                variant_ddl=assembled_ddl,
                variant_mode="types_validation",
                phase_name="types_validation",
                total_variants=1,
                benchmark_run_id=benchmark_run_id,
                benchmark_started_at=benchmark_started_at,
                source_benchmark=source_benchmark,
                global_index_counter=global_index_counter,
                parent_variant_table=parent.variant_table,
            )
            validation_scope = (
                f"phase2 types validation: {table_plan.benchmark_id} "
                f"{table_plan.database}.{table_plan.table} parent={parent.variant_table}"
            )
            _dispatch_stage_jobs(
                runner=runner,
                jobs=[validation_job],
                stage_scope_name=validation_scope,
                stage_label=validation_scope,
            )
            validation_summaries = _wait_for_stage_summaries(
                store=store,
                benchmark_run_id=benchmark_run_id,
                benchmark_id=table_plan.benchmark_id,
                source_database=table_plan.database,
                source_table=table_plan.table,
                variant_mode="types_validation",
                expected_variant_tables=[validation_job.variant_table],
            )
            summary = validation_summaries.get(validation_job.variant_table)
            if summary is None:
                continue
            candidate = _candidate_from_summary(summary, fallback_ddl=assembled_ddl)
            if candidate is not None:
                type_winners.append(candidate)

        type_winners = _sorted_candidates(type_winners)[:top_n]
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

        # ------------------------------------------------------------------
        # Фаза 3: CODEC
        # ------------------------------------------------------------------
        _log_stage_banner(
            stage_name="КОДЕКИ (phase 3)",
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            database=table_plan.database,
            table=table_plan.table,
        )
        codec_winners: list[_PhaseCandidate] = []
        for parent in type_winners:
            base_ddl = parent.variant_ddl.copy()
            jobs: list[VariantJob] = []
            context_by_variant_table: dict[str, _CodecJobContext] = {}

            for column in base_ddl.columns:
                codec_candidates = _resolve_codec_candidates_for_column(
                    table_plan=table_plan,
                    column_name=column.name,
                    current_type=column.type,
                    current_codec=column.codec,
                )
                if len(codec_candidates) <= 1:
                    continue
                for tested_codec in codec_candidates:
                    variant_ddl = base_ddl.copy()
                    tested_column = variant_ddl.column(column.name)
                    if tested_column is None:
                        continue
                    tested_column.codec = tested_codec
                    column_meta = ColumnVariantMeta(
                        index=0,
                        column_choices={
                            column.name: (tested_column.type, tested_codec)
                        },
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
                    )
                    jobs.append(job)
                    context_by_variant_table[job.variant_table] = _CodecJobContext(
                        parent_variant_table=parent.variant_table,
                        column_name=column.name,
                        tested_codec=tested_codec,
                    )

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
            )

            best_by_column: dict[str, tuple[float, Optional[str]]] = {}
            for variant_table, summary in summaries.items():
                context = context_by_variant_table.get(variant_table)
                if context is None or summary.score is None:
                    continue
                existing = best_by_column.get(context.column_name)
                if existing is None or summary.score > existing[0]:
                    best_by_column[context.column_name] = (
                        float(summary.score),
                        context.tested_codec,
                    )

            assembled_ddl = base_ddl.copy()
            for column_name, (_, best_codec) in best_by_column.items():
                column = assembled_ddl.column(column_name)
                if column is None:
                    continue
                column.codec = best_codec

            validation_job = _build_job(
                runner=runner,
                table_plan=table_plan,
                raw_query_plan=raw_query_plan,
                variant_ddl=assembled_ddl,
                variant_mode="codecs_validation",
                phase_name="codecs_validation",
                total_variants=1,
                benchmark_run_id=benchmark_run_id,
                benchmark_started_at=benchmark_started_at,
                source_benchmark=source_benchmark,
                global_index_counter=global_index_counter,
                parent_variant_table=parent.variant_table,
            )
            validation_scope = (
                f"phase3 codecs validation: {table_plan.benchmark_id} "
                f"{table_plan.database}.{table_plan.table} parent={parent.variant_table}"
            )
            _dispatch_stage_jobs(
                runner=runner,
                jobs=[validation_job],
                stage_scope_name=validation_scope,
                stage_label=validation_scope,
            )
            validation_summaries = _wait_for_stage_summaries(
                store=store,
                benchmark_run_id=benchmark_run_id,
                benchmark_id=table_plan.benchmark_id,
                source_database=table_plan.database,
                source_table=table_plan.table,
                variant_mode="codecs_validation",
                expected_variant_tables=[validation_job.variant_table],
            )
            summary = validation_summaries.get(validation_job.variant_table)
            if summary is None:
                continue
            candidate = _candidate_from_summary(summary, fallback_ddl=assembled_ddl)
            if candidate is not None:
                codec_winners.append(candidate)

        codec_winners = _sorted_candidates(codec_winners)[:top_n]
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

        # ------------------------------------------------------------------
        # Фаза 4: INDEX
        # ------------------------------------------------------------------
        _log_stage_banner(
            stage_name="DATA SKIPPING ИНДЕКСЫ (phase 4)",
            benchmark_run_id=benchmark_run_id,
            benchmark_id=table_plan.benchmark_id,
            database=table_plan.database,
            table=table_plan.table,
        )
        index_winners: list[_PhaseCandidate] = []
        for parent in codec_winners:
            base_ddl = parent.variant_ddl.copy()
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
                options = _resolve_index_options_for_column(
                    table_plan=table_plan,
                    base_ddl=base_ddl,
                    column_name=column_name,
                )
                for option in options:
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
            )

            best_by_column: dict[
                str,
                tuple[float, Optional[IndexDef], Optional[int], Optional[List[int]]],
            ] = {}
            for variant_table, summary in summaries.items():
                context = context_by_variant_table.get(variant_table)
                if context is None or summary.score is None:
                    continue
                existing = best_by_column.get(context.column_name)
                if existing is None or summary.score > existing[0]:
                    best_by_column[context.column_name] = (
                        float(summary.score),
                        context.index_def.copy() if context.index_def is not None else None,
                        context.table_index_granularity,
                        (
                            list(context.allowed_table_index_granularity_values)
                            if context.allowed_table_index_granularity_values is not None
                            else None
                        ),
                    )

            assembled_ddl = base_ddl.copy()
            selected_granularities: list[tuple[float, int]] = []
            granularity_constraints: list[set[int]] = []
            for column_name, (
                column_score,
                index_def,
                table_index_granularity,
                allowed_table_index_granularity_values,
            ) in best_by_column.items():
                _remove_indexes_for_column(assembled_ddl, column_name)
                if index_def is not None:
                    assembled_ddl.indexes.append(index_def.copy())
                if table_index_granularity is not None:
                    selected_granularities.append((column_score, table_index_granularity))
                if allowed_table_index_granularity_values:
                    granularity_constraints.append(
                        {int(value) for value in allowed_table_index_granularity_values}
                    )

            table_granularity_candidates = list(table_plan.index_granularity_values or [])
            if not table_granularity_candidates and selected_granularities:
                table_granularity_candidates = [
                    int(granularity)
                    for _, granularity in sorted(
                        selected_granularities,
                        key=lambda item: item[0],
                        reverse=True,
                    )
                ]
            if table_granularity_candidates and granularity_constraints:
                allowed = set(table_granularity_candidates)
                for constraint in granularity_constraints:
                    allowed &= constraint
                table_granularity_candidates = [
                    value for value in table_granularity_candidates if value in allowed
                ]
            if not table_granularity_candidates:
                if selected_granularities:
                    selected_granularities.sort(key=lambda item: item[0], reverse=True)
                    table_granularity_candidates = [selected_granularities[0][1]]
                else:
                    table_granularity_candidates = [None]

            validation_jobs: list[VariantJob] = []
            for table_granularity in table_granularity_candidates:
                validation_ddl = assembled_ddl.copy()
                if table_granularity is not None:
                    validation_ddl.set_index_granularity(int(table_granularity))
                validation_job = _build_job(
                    runner=runner,
                    table_plan=table_plan,
                    raw_query_plan=raw_query_plan,
                    variant_ddl=validation_ddl,
                    variant_mode="indexes_validation",
                    phase_name="indexes_validation",
                    total_variants=max(1, len(table_granularity_candidates)),
                    benchmark_run_id=benchmark_run_id,
                    benchmark_started_at=benchmark_started_at,
                    source_benchmark=source_benchmark,
                    global_index_counter=global_index_counter,
                    parent_variant_table=parent.variant_table,
                )
                validation_jobs.append(validation_job)

            validation_scope = (
                f"phase4 indexes validation: {table_plan.benchmark_id} "
                f"{table_plan.database}.{table_plan.table} parent={parent.variant_table}"
            )
            _dispatch_stage_jobs(
                runner=runner,
                jobs=validation_jobs,
                stage_scope_name=validation_scope,
                stage_label=validation_scope,
            )
            validation_summaries = _wait_for_stage_summaries(
                store=store,
                benchmark_run_id=benchmark_run_id,
                benchmark_id=table_plan.benchmark_id,
                source_database=table_plan.database,
                source_table=table_plan.table,
                variant_mode="indexes_validation",
                expected_variant_tables=[job.variant_table for job in validation_jobs],
            )
            ranked_validation_candidates = _sorted_candidates(
                [
                    candidate
                    for candidate in (
                        _candidate_from_summary(
                            summary,
                            fallback_ddl=assembled_ddl,
                        )
                        for summary in validation_summaries.values()
                    )
                    if candidate is not None
                ]
            )
            if not ranked_validation_candidates:
                continue
            candidate = ranked_validation_candidates[0]
            if candidate is not None:
                index_winners.append(candidate)

        index_winners = _sorted_candidates(index_winners)[:top_n]
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
        for candidate in index_winners:
            job = _build_job(
                runner=runner,
                table_plan=table_plan,
                raw_query_plan=raw_query_plan,
                variant_ddl=candidate.variant_ddl.copy(),
                variant_mode="final_validation",
                phase_name="final_validation",
                total_variants=len(index_winners),
                benchmark_run_id=benchmark_run_id,
                benchmark_started_at=benchmark_started_at,
                source_benchmark=source_benchmark,
                global_index_counter=global_index_counter,
                parent_variant_table=candidate.variant_table,
            )
            final_jobs.append(job)
            fallback_ddls_by_table[job.variant_table] = candidate.variant_ddl.copy()

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
