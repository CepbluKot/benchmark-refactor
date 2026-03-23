"""
Автогенерация тестовых запросов по схеме таблицы (mode: "auto").

Цель — минимальный набор одно-колоночных запросов:
  1. String: `LIKE '%%'` + data-aware токены (hit/miss).
  2. Date/DateTime/числа: диапазоны `>` / `<` по min/max.

Все запросы параметризуются плейсхолдером {table} —
подстановка реального имени таблицы происходит в runner.

Запросы не претендуют на полноту — это разумный baseline.
Для точного бенчмарка всегда лучше задать запросы вручную (mode: "manual").
"""

from __future__ import annotations

import re
from pydantic import BaseModel
from typing import Dict, List, Literal, Optional, Sequence

from src.clickhouse_ddl import ColumnDef, TableDDL


# ─── типы колонок ────────────────────────────────────────────────────────────

def _base_type(col: ColumnDef) -> str:
    """Возвращает базовый тип без параметров и обёрток."""
    t = col.type
    # Снимаем вложенные LowCardinality()/Nullable().
    while True:
        unwrapped = t
        for wrapper in ("LowCardinality", "Nullable"):
            m = re.match(rf"^{wrapper}\((.+)\)$", unwrapped)
            if m:
                unwrapped = m.group(1)
        if unwrapped == t:
            break
        t = unwrapped
    # Убираем параметры: Decimal(18,4) → Decimal
    return t.split("(")[0]


def _unwrapped_type(col: ColumnDef) -> str:
    """Возвращает тип без обёрток Nullable/LowCardinality, но с параметрами."""
    t = col.type
    while True:
        unwrapped = t
        for wrapper in ("LowCardinality", "Nullable"):
            m = re.match(rf"^{wrapper}\((.+)\)$", unwrapped)
            if m:
                unwrapped = m.group(1)
        if unwrapped == t:
            break
        t = unwrapped
    return t


def _is_integer(col: ColumnDef) -> bool:
    """True для целочисленных типов ClickHouse."""
    base = _base_type(col)
    return base in {
        "UInt8", "UInt16", "UInt32", "UInt64", "UInt128", "UInt256",
        "Int8", "Int16", "Int32", "Int64", "Int128", "Int256",
    }


def _is_float(col: ColumnDef) -> bool:
    """True для Float32/Float64."""
    return _base_type(col) in {"Float32", "Float64"}


def _is_numeric(col: ColumnDef) -> bool:
    """True для всех числовых типов, используемых в агрегатах."""
    return _is_integer(col) or _is_float(col) or _base_type(col) in {"Decimal"}


def _is_datetime(col: ColumnDef) -> bool:
    """True для Date/DateTime-семейства."""
    return _base_type(col) in {"DateTime", "DateTime64", "Date", "Date32"}


def _is_string(col: ColumnDef) -> bool:
    """True для строковых типов."""
    return _base_type(col) in {"String", "FixedString"}


def _is_low_cardinality(col: ColumnDef) -> bool:
    """True, если колонка обёрнута в `LowCardinality(...)`."""
    return col.type.startswith("LowCardinality(")


def _is_nullable(col: ColumnDef) -> bool:
    """True, если колонка обёрнута в `Nullable(...)`."""
    return col.type.startswith("Nullable(")


def _quote_ident(value: str) -> str:
    """Квотирует имя колонки в ClickHouse SQL."""
    return f"`{str(value).replace('`', '``')}`"


def _sql_literal(value: object) -> str:
    """Преобразует Python-значение в SQL-литерал."""
    escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _datetime_filter_literal(col: ColumnDef, value: object) -> str:
    """
    Строит безопасный Date/DateTime-литерал для фильтров `>`/`<`.

    Важно: range-токены для datetime приходят строками и могут содержать timezone
    offset (`+03:00`). Прямое сравнение `DateTime > '...+03:00'` в ClickHouse может
    давать TYPE_MISMATCH, поэтому используем parseDateTime* + CAST к типу колонки.
    """
    cast_type = _unwrapped_type(col)
    base = _base_type(col)
    literal = _sql_literal(value)
    if base == "DateTime64":
        parsed = f"parseDateTime64BestEffort({literal})"
    else:
        parsed = f"parseDateTimeBestEffort({literal})"
    return f"CAST({parsed} AS {cast_type})"


def _numeric_filter_literal(col: ColumnDef, value: object) -> str:
    """Строит типизированный numeric-литерал через CAST."""
    cast_type = _unwrapped_type(col)
    return f"CAST({_sql_literal(value)} AS {cast_type})"


# ─── датакласс результата ─────────────────────────────────────────────────────

class GeneratedQuery(BaseModel):
    """Один автогенерированный SQL-запрос с пояснением его назначения."""

    query: str
    description: str = ""
    query_type: Literal["hit", "miss", "generic"] = "generic"
    query_column: Optional[str] = None


# ─── генератор ───────────────────────────────────────────────────────────────

class QueryGenerator:
    """
    Генерирует набор тестовых запросов по схеме TableDDL.

    Использование:
        gen = QueryGenerator(table_ddl)
        queries = gen.generate()
        for q in queries:
            print(q.query)
    """

    def __init__(self, table: TableDDL, *, auto_select_limit: int = 10) -> None:
        """Инициализирует генератор для конкретной схемы таблицы."""
        self.table = table
        self._placeholder = "{table}"   # подставляется в runner
        self._auto_select_limit = max(1, int(auto_select_limit))

    @staticmethod
    def _is_select_query(sql: str) -> bool:
        """Проверяет, что SQL — SELECT-запрос."""
        return re.match(r"^\s*SELECT\b", sql, flags=re.IGNORECASE) is not None

    def _enforce_select_limit(self, sql: str) -> str:
        """
        Принудительно выставляет LIMIT для автосгенерированных SELECT.

        Правило:
          - если LIMIT уже есть, заменяем его значение;
          - если LIMIT нет, добавляем в конец (перед SETTINGS, если есть).
        """
        if not self._is_select_query(sql):
            return sql

        cleaned_sql = sql.rstrip().rstrip(";")
        limit_pattern = re.compile(
            r"(?is)\bLIMIT\s+\d+(?:\s*,\s*\d+)?(?:\s+OFFSET\s+\d+)?"
        )
        if limit_pattern.search(cleaned_sql):
            return limit_pattern.sub(
                f"LIMIT {self._auto_select_limit}",
                cleaned_sql,
                count=1,
            )

        settings_match = re.search(r"(?is)\bSETTINGS\b", cleaned_sql)
        if settings_match is not None:
            start = settings_match.start()
            prefix = cleaned_sql[:start].rstrip()
            suffix = cleaned_sql[start:].lstrip()
            return f"{prefix} LIMIT {self._auto_select_limit} {suffix}"

        return f"{cleaned_sql} LIMIT {self._auto_select_limit}"

    def _enforce_limit_for_generated(self, queries: List[GeneratedQuery]) -> List[GeneratedQuery]:
        """Применяет жесткий LIMIT к списку автосгенерированных SELECT запросов."""
        normalized: list[GeneratedQuery] = []
        for item in queries:
            normalized.append(
                GeneratedQuery(
                    query=self._enforce_select_limit(item.query),
                    description=item.description,
                    query_type=item.query_type,
                    query_column=item.query_column,
                )
            )
        return normalized

    def generate(self) -> List[GeneratedQuery]:
        """Legacy entrypoint: базовые автозапросы отключены."""
        return []

    def generate_data_aware_like_queries(
        self,
        like_tokens_by_column: Dict[str, Dict[str, str]],
    ) -> List[GeneratedQuery]:
        """
        Генерирует data-aware LIKE запросы по колонкам.

        Для каждой колонки строится пара:
          - hit query: токен гарантированно возвращает строки;
          - miss query: токен гарантированно не возвращает строки.
        """
        if not like_tokens_by_column:
            return []

        generated: List[GeneratedQuery] = []
        table_columns = {column.name for column in self.table.columns}
        t = self._placeholder
        for column_name, token_payload in like_tokens_by_column.items():
            if column_name not in table_columns:
                continue
            hit_token = str(token_payload.get("hit_token") or "").strip()
            miss_token = str(token_payload.get("miss_token") or "").strip()
            if not hit_token:
                continue
            column_ident = _quote_ident(column_name)
            generated.append(
                GeneratedQuery(
                    query=(
                        f"SELECT * FROM {t} "
                        f"WHERE {column_ident} LIKE '%%' "
                        f"AND {column_ident} LIKE concat('%', {_sql_literal(hit_token)}, '%') "
                        f"LIMIT 10000"
                    ),
                    description=f"data-aware like hit on {column_name}",
                    query_type="hit",
                    query_column=column_name,
                )
            )
            if miss_token:
                generated.append(
                    GeneratedQuery(
                        query=(
                            f"SELECT * FROM {t} "
                            f"WHERE {column_ident} LIKE '%%' "
                            f"AND {column_ident} LIKE concat('%', {_sql_literal(miss_token)}, '%') "
                            f"LIMIT 10000"
                        ),
                        description=f"data-aware like miss on {column_name}",
                        query_type="miss",
                        query_column=column_name,
                    )
                )
        return self._enforce_limit_for_generated(generated)

    def generate_measured_column_queries(
        self,
        measured_columns: Sequence[str],
        *,
        like_tokens_by_column: Optional[Dict[str, Dict[str, str]]] = None,
        range_tokens_by_column: Optional[Dict[str, Dict[str, str]]] = None,
        include_miss_queries: bool = False,
    ) -> List[GeneratedQuery]:
        """
        Генерирует one-column запросы для измеряемых колонок.

        Для строковых колонок всегда используется `LIKE '%...%'`.
        Для DateTime/чисел строятся диапазоны `>` / `<` по data-aware min/max.
        """
        table_columns = {column.name: column for column in self.table.columns}
        deduplicated: list[str] = []
        seen: set[str] = set()
        for raw_column_name in measured_columns:
            column_name = str(raw_column_name).strip()
            if not column_name or column_name in seen:
                continue
            if column_name not in table_columns:
                continue
            seen.add(column_name)
            deduplicated.append(column_name)

        if not deduplicated:
            return []

        tokens_by_column = like_tokens_by_column or {}
        range_tokens = range_tokens_by_column or {}
        generated: list[GeneratedQuery] = []
        t = self._placeholder

        for column_name in deduplicated:
            column = table_columns[column_name]
            column_ident = _quote_ident(column_name)

            if _is_string(column):
                token_payload = tokens_by_column.get(column_name, {})
                hit_token = str(token_payload.get("hit_token") or "").strip()
                miss_token = str(token_payload.get("miss_token") or "").strip()
                if hit_token:
                    hit_query = (
                        f"SELECT * FROM {t} "
                        f"WHERE {column_ident} LIKE '%%' "
                        f"AND {column_ident} LIKE concat('%', {_sql_literal(hit_token)}, '%')"
                    )
                else:
                    # Без токена всё равно держим LIKE-предикат, без NULL-веток.
                    hit_query = (
                        f"SELECT * FROM {t} "
                        f"WHERE {column_ident} LIKE '%%'"
                    )

                generated.append(
                    GeneratedQuery(
                        query=hit_query,
                        description=f"measured like hit on {column_name}",
                        query_type="hit",
                        query_column=column_name,
                    )
                )

                if include_miss_queries:
                    if miss_token:
                        miss_query = (
                            f"SELECT * FROM {t} "
                            f"WHERE {column_ident} LIKE '%%' "
                            f"AND {column_ident} LIKE concat('%', {_sql_literal(miss_token)}, '%')"
                        )
                    else:
                        miss_query = (
                            f"SELECT * FROM {t} "
                            f"WHERE {column_ident} LIKE '%%' AND {column_ident} NOT LIKE '%%'"
                        )
                    generated.append(
                        GeneratedQuery(
                            query=miss_query,
                            description=f"measured like miss on {column_name}",
                            query_type="miss",
                            query_column=column_name,
                        )
                    )
                continue

            # DateTime / numeric: range queries only (>, <).
            if _is_datetime(column) or _is_numeric(column):
                token_payload = range_tokens.get(column_name, {})
                min_value = str(token_payload.get("min_value") or token_payload.get("min") or "").strip()
                max_value = str(token_payload.get("max_value") or token_payload.get("max") or "").strip()

                if _is_datetime(column):
                    min_literal = (
                        _datetime_filter_literal(column, min_value) if min_value else ""
                    )
                    max_literal = (
                        _datetime_filter_literal(column, max_value) if max_value else ""
                    )
                else:
                    min_literal = _numeric_filter_literal(column, min_value) if min_value else ""
                    max_literal = _numeric_filter_literal(column, max_value) if max_value else ""

                if min_value:
                    hit_query = (
                        f"SELECT * FROM {t} "
                        f"WHERE {column_ident} > {min_literal}"
                    )
                    generated.append(
                        GeneratedQuery(
                            query=hit_query,
                            description=f"measured range hit on {column_name}",
                            query_type="hit",
                            query_column=column_name,
                        )
                    )
                    if include_miss_queries:
                        miss_query = (
                            f"SELECT * FROM {t} "
                            f"WHERE {column_ident} < {min_literal}"
                        )
                        generated.append(
                            GeneratedQuery(
                                query=miss_query,
                                description=f"measured range miss on {column_name}",
                                query_type="miss",
                                query_column=column_name,
                            )
                        )
                    continue

                if max_value:
                    hit_query = (
                        f"SELECT * FROM {t} "
                        f"WHERE {column_ident} < {max_literal}"
                    )
                    generated.append(
                        GeneratedQuery(
                            query=hit_query,
                            description=f"measured range hit on {column_name}",
                            query_type="hit",
                            query_column=column_name,
                        )
                    )
                    if include_miss_queries:
                        miss_query = (
                            f"SELECT * FROM {t} "
                            f"WHERE {column_ident} > {max_literal}"
                        )
                        generated.append(
                            GeneratedQuery(
                                query=miss_query,
                                description=f"measured range miss on {column_name}",
                                query_type="miss",
                                query_column=column_name,
                            )
                        )
                continue

        return self._enforce_limit_for_generated(generated)

    # ── генераторы по паттернам ──────────────────────────────────────────────

    def _full_scan_queries(self) -> List[GeneratedQuery]:
        """Полный скан с LIMIT — оценка скорости чтения с диска."""
        t = self._placeholder
        return [
            GeneratedQuery(
                query=f"SELECT count() FROM {t}",
                description="full scan count",
            ),
            GeneratedQuery(
                query=f"SELECT * FROM {t} LIMIT 10000",
                description="full scan with limit",
            ),
        ]

    def _datetime_range_queries(self) -> List[GeneratedQuery]:
        """Диапазонные фильтры по DateTime-колонкам."""
        dt_cols = [c for c in self.table.columns if _is_datetime(c)]
        if not dt_cols:
            return []

        t = self._placeholder
        queries = []
        for col in dt_cols[:2]:    # берём не более двух DateTime-колонок
            queries.append(GeneratedQuery(
                query=(
                    f"SELECT count() FROM {t} "
                    f"WHERE `{col.name}` >= now() - INTERVAL 1 DAY"
                ),
                description=f"datetime range 1d on {col.name}",
            ))
            queries.append(GeneratedQuery(
                query=(
                    f"SELECT count() FROM {t} "
                    f"WHERE `{col.name}` >= now() - INTERVAL 7 DAY"
                ),
                description=f"datetime range 7d on {col.name}",
            ))
            queries.append(GeneratedQuery(
                query=(
                    f"SELECT count() FROM {t} "
                    f"WHERE `{col.name}` >= now() - INTERVAL 30 DAY"
                ),
                description=f"datetime range 30d on {col.name}",
            ))
        return queries

    def _order_by_filter_queries(self) -> List[GeneratedQuery]:
        """
        Точечные фильтры по первой колонке ORDER BY.
        ORDER BY — лучший кандидат для фильтрации (используется primary index CH).
        """
        if not self.table.order_by:
            return []

        # Парсим ORDER BY: берём первую колонку
        order_cols_raw = re.sub(r"^\(|\)$", "", self.table.order_by.strip())
        first_order_col_name = order_cols_raw.split(",")[0].strip().strip("`")

        col = self.table.column(first_order_col_name)
        if col is None:
            return []

        t = self._placeholder
        queries = []

        if _is_integer(col):
            # Точечный поиск по целочисленной колонке
            queries.append(GeneratedQuery(
                query=(
                    f"SELECT count() FROM {t} "
                    f"WHERE `{col.name}` = 12345"
                ),
                description=f"point filter on order_by col {col.name}",
            ))
            queries.append(GeneratedQuery(
                query=(
                    f"SELECT * FROM {t} "
                    f"WHERE `{col.name}` BETWEEN 1000 AND 2000 "
                    f"LIMIT 1000"
                ),
                description=f"range filter on order_by col {col.name}",
            ))
        elif _is_string(col):
            queries.append(GeneratedQuery(
                query=(
                    f"SELECT count() FROM {t} "
                    f"WHERE `{col.name}` = 'example_value'"
                ),
                description=f"string filter on order_by col {col.name}",
            ))

        return queries

    def _aggregate_queries(self) -> List[GeneratedQuery]:
        """Агрегаты по числовым колонкам."""
        numeric_cols = [
            c for c in self.table.columns
            if _is_numeric(c) and not _is_nullable(c)
        ]
        if not numeric_cols:
            return []

        t = self._placeholder
        queries = []

        # Берём до 3 числовых колонок
        for col in numeric_cols[:3]:
            queries.append(GeneratedQuery(
                query=(
                    f"SELECT "
                    f"min(`{col.name}`), max(`{col.name}`), "
                    f"avg(`{col.name}`), sum(`{col.name}`) "
                    f"FROM {t}"
                ),
                description=f"aggregates on {col.name}",
            ))

        # Если есть DateTime — добавляем агрегат с временным фильтром
        dt_cols = [c for c in self.table.columns if _is_datetime(c)]
        if dt_cols and numeric_cols:
            dt_col = dt_cols[0]
            num_col = numeric_cols[0]
            queries.append(GeneratedQuery(
                query=(
                    f"SELECT sum(`{num_col.name}`) FROM {t} "
                    f"WHERE `{dt_col.name}` >= now() - INTERVAL 7 DAY"
                ),
                description=f"aggregate with datetime filter",
            ))

        return queries

# ─── публичный API ────────────────────────────────────────────────────────────

def generate_queries(
    table: TableDDL,
    *,
    like_tokens_by_column: Optional[Dict[str, Dict[str, str]]] = None,
    range_tokens_by_column: Optional[Dict[str, Dict[str, str]]] = None,
    measured_columns: Optional[Sequence[str]] = None,
    prefer_measured_columns: bool = False,
    auto_select_limit: int = 10,
    include_miss_queries: bool = False,
) -> List[GeneratedQuery]:
    """Удобная функция-обёртка над QueryGenerator."""
    generator = QueryGenerator(table, auto_select_limit=auto_select_limit)
    if prefer_measured_columns:
        effective_columns = list(measured_columns or [col.name for col in table.columns])
        return generator.generate_measured_column_queries(
            effective_columns,
            like_tokens_by_column=like_tokens_by_column,
            range_tokens_by_column=range_tokens_by_column,
            include_miss_queries=include_miss_queries,
        )

    return generator.generate()
