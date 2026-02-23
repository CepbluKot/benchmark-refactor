"""
Автогенерация тестовых запросов по схеме таблицы (mode: "auto").

Цель — покрыть типичные паттерны нагрузки на аналитических таблицах:
  1. Точечные фильтры по колонкам из ORDER BY / PRIMARY KEY
  2. Диапазонные фильтры по DateTime-колонкам
  3. Агрегаты по числовым колонкам
  4. GROUP BY по низкокардинальным колонкам
  5. Полный скан с LIMIT (оценка скорости чтения)

Все запросы параметризуются плейсхолдером {table} —
подстановка реального имени таблицы происходит в runner.

Запросы не претендуют на полноту — это разумный baseline.
Для точного бенчмарка всегда лучше задать запросы вручную (mode: "manual").
"""

from __future__ import annotations

import re
from pydantic import BaseModel
from typing import List, Optional

from clickhouse_ddl import ColumnDef, TableDDL


# ─── типы колонок ────────────────────────────────────────────────────────────

def _base_type(col: ColumnDef) -> str:
    """Возвращает базовый тип без параметров и обёрток."""
    t = col.type
    # Снимаем LowCardinality(), Nullable()
    for wrapper in ("LowCardinality", "Nullable"):
        m = re.match(rf"^{wrapper}\((.+)\)$", t)
        if m:
            t = m.group(1)
    # Убираем параметры: Decimal(18,4) → Decimal
    return t.split("(")[0]


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


# ─── датакласс результата ─────────────────────────────────────────────────────

class GeneratedQuery(BaseModel):
    """Один автогенерированный SQL-запрос с пояснением его назначения."""

    query: str
    description: str = ""


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

    def __init__(self, table: TableDDL) -> None:
        """Инициализирует генератор для конкретной схемы таблицы."""
        self.table = table
        self._placeholder = "{table}"   # подставляется в runner

    def generate(self) -> List[GeneratedQuery]:
        """Возвращает список запросов, покрывающих основные паттерны."""
        queries: List[GeneratedQuery] = []

        queries += self._full_scan_queries()
        queries += self._datetime_range_queries()
        queries += self._order_by_filter_queries()
        queries += self._aggregate_queries()
        queries += self._group_by_queries()

        # weights removed — return list as-is

        return queries

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

    def _group_by_queries(self) -> List[GeneratedQuery]:
        """GROUP BY по низкокардинальным колонкам."""
        lc_cols = [
            c for c in self.table.columns
            if _is_low_cardinality(c) or _is_integer(c)
        ]
        numeric_cols = [c for c in self.table.columns if _is_numeric(c)]

        if not lc_cols:
            return []

        t = self._placeholder
        queries = []

        group_col = lc_cols[0]

        if numeric_cols:
            num_col = numeric_cols[0]
            queries.append(GeneratedQuery(
                query=(
                    f"SELECT `{group_col.name}`, count(), sum(`{num_col.name}`) "
                    f"FROM {t} "
                    f"GROUP BY `{group_col.name}` "
                    f"ORDER BY count() DESC "
                    f"LIMIT 100"
                ),
                description=f"group by {group_col.name} with aggregate",
            ))
        else:
            queries.append(GeneratedQuery(
                query=(
                    f"SELECT `{group_col.name}`, count() "
                    f"FROM {t} "
                    f"GROUP BY `{group_col.name}` "
                    f"ORDER BY count() DESC "
                    f"LIMIT 100"
                ),
                description=f"group by {group_col.name}",
            ))

        # Если есть DateTime + низкокардинальная — двойная группировка
        dt_cols = [c for c in self.table.columns if _is_datetime(c)]
        if dt_cols and len(lc_cols) >= 1:
            dt_col = dt_cols[0]
            queries.append(GeneratedQuery(
                query=(
                    f"SELECT "
                    f"toYYYYMM(`{dt_col.name}`) AS month, "
                    f"`{group_col.name}`, "
                    f"count() "
                    f"FROM {t} "
                    f"WHERE `{dt_col.name}` >= now() - INTERVAL 90 DAY "
                    f"GROUP BY month, `{group_col.name}` "
                    f"ORDER BY month DESC, count() DESC "
                    f"LIMIT 200"
                ),
                description=f"group by month + {group_col.name}",
            ))

        return queries


# ─── публичный API ────────────────────────────────────────────────────────────

def generate_queries(table: TableDDL) -> List[GeneratedQuery]:
    """Удобная функция-обёртка над QueryGenerator."""
    return QueryGenerator(table).generate()
