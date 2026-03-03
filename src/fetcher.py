"""
Fetcher — подключение к ClickHouse и все операции с ним:
  - получение списка БД и таблиц
  - парсинг DDL через SHOW CREATE TABLE
  - создание / удаление таблиц
  - копирование данных INSERT INTO ... SELECT
  - выполнение запросов с замером метрик

Зависимость: clickhouse-connect  (pip install clickhouse-connect)
Импорт clickhouse_connect отложен до момента connect() — чтобы модуль
грузился даже без установленного драйвера (полезно для тестов и импортов).
"""

from __future__ import annotations

import logging
import re
import time
from uuid import uuid4
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Sequence

from src.models import ConnectionConfig
from src.clickhouse_ddl import TableDDL
from src.naming import is_variant_table

logger = logging.getLogger(__name__)

# ─── системные БД, пропускаемые при databases="*" ────────────────────────────

_SYSTEM_DATABASES = frozenset({
    "system",
    "information_schema",
    "INFORMATION_SCHEMA",
    "_temporary_and_external_tables",
})
_BASELINE_TABLE_MARKER = "__source_baseline__"


# ─── вспомогательные датаклассы ───────────────────────────────────────────────

class TableMetrics(BaseModel):
    """Размерные метрики таблицы из system.parts."""
    database: str
    table: str
    total_rows: int = 0
    total_bytes: int = 0               # сжатый размер на диске
    total_bytes_uncompressed: int = 0

    @property
    def compression_ratio(self) -> Optional[float]:
        """Отношение `compressed/uncompressed` (меньше = лучше сжатие)."""
        if self.total_bytes_uncompressed > 0:
            return self.total_bytes / self.total_bytes_uncompressed
        return None


class QueryResult(BaseModel):
    """Результат выполнения одного SELECT-запроса."""
    rows: list
    duration_ms: float      # из clickhouse_connect .summary (или wall-time fallback)
    read_rows: int = 0
    read_bytes: int = 0
    result_rows: int = 0


# ─── исключения ──────────────────────────────────────────────────────────────

class FetcherError(Exception):
    """Любая ошибка при работе с ClickHouse."""


# ─── fetcher ─────────────────────────────────────────────────────────────────

class Fetcher:
    """
    Тонкая обёртка над clickhouse_connect client.
    Один экземпляр = одно соединение с одним хостом.

    Использование:
        with Fetcher(conn_cfg) as f:
            ddl = f.fetch_ddl("analytics", "events")

        # или вручную:
        f = Fetcher(conn_cfg)
        f.connect()
        ...
        f.disconnect()
    """

    def __init__(self, connection: ConnectionConfig) -> None:
        """Создаёт fetcher для одного `ConnectionConfig` (без подключения)."""
        self._conn = connection
        self._client = None     # type: ignore[assignment]  # инициализируется в connect()

    # ── lifecycle ────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Открывает соединение с ClickHouse, если оно ещё не открыто."""
        if self._client is not None:
            return
        try:
            import clickhouse_connect
        except ImportError as e:
            raise FetcherError(
                "clickhouse-connect не установлен. "
                "Выполни: pip install clickhouse-connect"
            ) from e

        logger.debug(
            "Connecting to %s:%d as %s",
            self._conn.host, self._conn.port, self._conn.login,
        )
        self._client = clickhouse_connect.get_client(
            host=self._conn.host,
            port=self._conn.port,
            username=self._conn.login,
            password=self._conn.password,
        )

    def disconnect(self) -> None:
        """Закрывает текущее соединение (идемпотентно)."""
        if self._client is not None:
            close_method = getattr(self._client, "close", None)
            if callable(close_method):
                close_method()
            self._client = None
            logger.debug("Disconnected from %s", self._conn.host)

    def __enter__(self) -> "Fetcher":
        """Вход в контекстный менеджер: автоматически подключается."""
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        """Выход из контекстного менеджера: автоматически отключается."""
        self.disconnect()

    # ── execute ──────────────────────────────────────────────────────────────

    def _execute(self, query: str, params: Optional[dict] = None) -> list:
        """Выполняет запрос, оборачивает ошибки в FetcherError."""
        if self._client is None:
            raise FetcherError(
                "Нет подключения — вызови connect() или используй контекстный менеджер"
            )

        try:
            rendered_query = self._bind_query_params(query, params)
            logger.debug("SQL: %s", rendered_query[:300].strip())
            if self._is_read_query(rendered_query):
                result = self._client.query(rendered_query)
                return list(result.result_rows or [])
            self._client.command(rendered_query)
            return []
        except Exception as e:
            raise FetcherError(f"ClickHouse error: {e}") from e

    @classmethod
    def _bind_query_params(cls, query: str, params: Optional[dict]) -> str:
        """
        Подставляет `%(name)s` параметры в SQL как литералы.

        Сохраняет обратную совместимость со старым форматом запросов.
        """
        if not params:
            return query

        pattern = re.compile(r"%\((?P<key>[A-Za-z_][A-Za-z0-9_]*)\)s")

        def _replace(match: re.Match[str]) -> str:
            key = match.group("key")
            if key not in params:
                raise FetcherError(f"Не найден SQL-параметр: {key}")
            return cls._sql_literal(params[key])

        return pattern.sub(_replace, query)

    @staticmethod
    def _sql_literal(value: object) -> str:
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
    def _quote_ident(value: str) -> str:
        """Безопасно квотирует SQL-идентификатор для ClickHouse."""
        return f"`{str(value).replace('`', '``')}`"

    @staticmethod
    def _extract_like_token_from_value(
        value: object,
        *,
        min_token_length: int,
        max_token_length: int,
    ) -> Optional[str]:
        """
        Извлекает токен для LIKE-поиска из значения строки.

        Токен нормализуется так, чтобы не содержать wildcard-символы `%`/`_`.
        """
        raw_value = str(value or "")
        normalized = re.sub(r"\s+", " ", raw_value).strip()
        if not normalized:
            return None

        chunks = re.findall(r"[0-9A-Za-zА-Яа-я./:-]+", normalized)
        for chunk in chunks:
            candidate = chunk[:max_token_length]
            if len(candidate) >= min_token_length:
                return candidate

        fallback = normalized[:max_token_length]
        if len(fallback) >= min_token_length:
            return fallback
        return None

    @staticmethod
    def _strip_leading_sql_comments(query: str) -> str:
        """Удаляет ведущие block comments и пробелы."""
        stripped = query.lstrip()
        while stripped.startswith("/*"):
            end_pos = stripped.find("*/")
            if end_pos == -1:
                break
            stripped = stripped[end_pos + 2 :].lstrip()
        return stripped

    @classmethod
    def _is_read_query(cls, query: str) -> bool:
        """Определяет, что запрос возвращает строки."""
        normalized = cls._strip_leading_sql_comments(query).lower()
        return normalized.startswith(
            ("select", "with", "show", "describe", "desc", "explain")
        )

    # ── обнаружение БД и таблиц ──────────────────────────────────────────────

    def list_databases(self, exclude_system: bool = True) -> List[str]:
        """Список всех баз данных на сервере (кроме системных по умолчанию)."""
        rows = self._execute("SELECT name FROM system.databases ORDER BY name")
        dbs = [r[0] for r in rows]
        if exclude_system:
            dbs = [db for db in dbs if db not in _SYSTEM_DATABASES]
        logger.info("Found %d databases on %s", len(dbs), self._conn.host)
        return dbs

    def list_tables(self, database: str) -> List[str]:
        """Список таблиц MergeTree-семейства в базе данных."""
        rows = self._execute(
            """
            SELECT name
            FROM system.tables
            WHERE database = %(database)s
              AND engine LIKE '%MergeTree%'
            ORDER BY name
            """,
            {"database": database},
        )
        tables = [r[0] for r in rows]
        logger.info("Found %d MergeTree tables in %s", len(tables), database)
        return tables

    def table_exists(self, database: str, table: str) -> bool:
        """Проверяет существование таблицы в `system.tables`."""
        rows = self._execute(
            "SELECT count() FROM system.tables "
            "WHERE database = %(db)s AND name = %(tbl)s",
            {"db": database, "tbl": table},
        )
        return bool(rows and rows[0][0] > 0)

    # ── DDL ──────────────────────────────────────────────────────────────────

    def fetch_ddl(self, database: str, table: str) -> TableDDL:
        """Получает DDL таблицы и парсит его в TableDDL."""
        rows = self._execute(
            f"SHOW CREATE TABLE `{database}`.`{table}`"
        )
        if not rows:
            raise FetcherError(f"Таблица {database}.{table} не найдена")

        raw_ddl: str = rows[0][0]
        logger.debug("Fetched DDL for %s.%s (%d chars)", database, table, len(raw_ddl))
        try:
            return TableDDL.from_ddl(raw_ddl)
        except Exception as e:
            raise FetcherError(
                f"Не удалось распарсить DDL {database}.{table}: {e}"
            ) from e

    def fetch_table_ddl(self, database: str, table: str) -> TableDDL:
        """Alias для нового интерфейса MetadataProvider."""
        return self.fetch_ddl(database, table)

    def fetch_column_sizes(self, database: str, table: str) -> Dict[str, int]:
        """
        Возвращает размерность колонок таблицы по сжатым байтам.

        Используется для авто-вычисления `column_order`:
        больше `data_compressed_bytes` -> выше приоритет перебора.
        """
        rows = self._execute(
            """
            SELECT
                column,
                sum(data_compressed_bytes) AS compressed_bytes
            FROM system.parts_columns
            WHERE database = %(db)s
              AND table = %(tbl)s
              AND active = 1
            GROUP BY column
            """,
            {"db": database, "tbl": table},
        )
        return {str(column): int(size or 0) for column, size in rows}

    def fetch_like_tokens(
        self,
        database: str,
        table: str,
        columns: Sequence[str],
        *,
        sample_rows_per_column: int = 20,
        min_token_length: int = 3,
        max_token_length: int = 24,
    ) -> Dict[str, Dict[str, str]]:
        """
        Возвращает data-aware LIKE токены (`hit`/`miss`) для колонок.

        `hit_token` выбирается из реальных данных таблицы и гарантированно матчится.
        `miss_token` подбирается как строка, отсутствующая в колонке.
        """
        if not columns:
            return {}

        unique_columns: List[str] = []
        seen: set[str] = set()
        for raw_column in columns:
            column_name = str(raw_column).strip()
            if not column_name or column_name in seen:
                continue
            seen.add(column_name)
            unique_columns.append(column_name)

        if not unique_columns:
            return {}

        database_ident = self._quote_ident(database)
        table_ident = self._quote_ident(table)
        result: Dict[str, Dict[str, str]] = {}

        for column_name in unique_columns:
            column_ident = self._quote_ident(column_name)
            try:
                rows = self._execute(
                    f"""
                    SELECT {column_ident}
                    FROM {database_ident}.{table_ident}
                    WHERE {column_ident} IS NOT NULL
                      AND notEmpty(toString({column_ident}))
                    LIMIT %(sample_rows)s
                    """,
                    {"sample_rows": int(sample_rows_per_column)},
                )
            except Exception:
                logger.exception(
                    "Не удалось получить sample rows для data-aware LIKE токенов: %s.%s.%s",
                    database,
                    table,
                    column_name,
                )
                continue

            hit_token: Optional[str] = None
            for row in rows:
                if not row:
                    continue
                hit_token = self._extract_like_token_from_value(
                    row[0],
                    min_token_length=min_token_length,
                    max_token_length=max_token_length,
                )
                if hit_token:
                    break

            if not hit_token:
                continue

            miss_token: Optional[str] = None
            column_marker = re.sub(r"[^0-9A-Za-z]+", "", column_name)[:24] or "col"
            for attempt in range(1, 10):
                candidate = f"bench_nomatch_{column_marker}_{uuid4().hex[:10]}_{attempt}"
                has_match_rows = self._execute(
                    f"""
                    SELECT 1
                    FROM {database_ident}.{table_ident}
                    WHERE {column_ident} LIKE %(pattern)s
                    LIMIT 1
                    """,
                    {"pattern": f"%{candidate}%"},
                )
                if not has_match_rows:
                    miss_token = candidate
                    break
            if not miss_token:
                miss_token = f"bench_nomatch_{column_marker}_{uuid4().hex[:16]}"

            result[column_name] = {
                "hit_token": hit_token,
                "miss_token": miss_token,
            }

        return result

    def create_table(self, table_ddl: TableDDL) -> None:
        """Создаёт таблицу по TableDDL-объекту."""
        self._execute(table_ddl.to_ddl())
        logger.info("Created table %s", table_ddl.name)

    def drop_table(
        self,
        database: str,
        table: str,
        if_exists: bool = True,
        *,
        allowed_database: Optional[str] = None,
        only_benchmark_tables: bool = True,
    ) -> None:
        """
        Удаляет таблицу-вариант после теста или перед пересозданием.

        Защита:
        - если задан `allowed_database`, удаление разрешено только внутри этой БД;
        - если `only_benchmark_tables=True`, удаляются только benchmark-таблицы:
          variant (`__bench__...__NNNN`) и baseline (`__source_baseline__`).
        """
        normalized_database = str(database).strip()
        normalized_table = str(table).strip()
        if not normalized_database:
            raise FetcherError("DROP TABLE: database не должен быть пустым")
        if not normalized_table:
            raise FetcherError("DROP TABLE: table не должен быть пустым")

        if allowed_database is not None:
            normalized_allowed = str(allowed_database).strip()
            if not normalized_allowed:
                raise FetcherError("DROP TABLE: allowed_database не должен быть пустым")
            if normalized_database != normalized_allowed:
                raise FetcherError(
                    "DROP TABLE разрешён только в тестовой БД, где создаются benchmark-таблицы"
                )

        if only_benchmark_tables:
            is_baseline = _BASELINE_TABLE_MARKER in normalized_table
            is_variant = is_variant_table(normalized_table)
            if not is_baseline and not is_variant:
                raise FetcherError(
                    "DROP TABLE разрешён только для benchmark-таблиц "
                    "(variant `__bench__...__NNNN` или `__source_baseline__`)"
                )

        exists = "IF EXISTS " if if_exists else ""
        self._execute(f"DROP TABLE {exists}`{normalized_database}`.`{normalized_table}`")
        logger.info("Dropped %s.%s", normalized_database, normalized_table)

    # ── данные ───────────────────────────────────────────────────────────────

    def insert_from(
        self,
        source_database: str,
        source_table: str,
        target_database: str,
        target_table: str,
        limit: Optional[int] = None,
    ) -> int:
        """
        Копирует данные: INSERT INTO target SELECT * FROM source.
        Возвращает количество вставленных строк (из system.parts — без лишнего SELECT).
        """
        limit_clause = f"LIMIT {limit}" if limit else ""
        self._execute(
            f"""
            INSERT INTO `{target_database}`.`{target_table}`
            SELECT * FROM `{source_database}`.`{source_table}`
            {limit_clause}
            """
        )
        # Берём count из system.parts — надёжнее чем отдельный SELECT count()
        rows = self._execute(
            """
            SELECT sum(rows)
            FROM system.parts
            WHERE database = %(db)s AND table = %(tbl)s AND active = 1
            """,
            {"db": target_database, "tbl": target_table},
        )
        count = int(rows[0][0] or 0) if rows else 0
        logger.info(
            "Inserted %d rows → %s.%s (from %s.%s)",
            count, target_database, target_table,
            source_database, source_table,
        )
        return count

    # ── метрики ──────────────────────────────────────────────────────────────

    def fetch_metrics(self, database: str, table: str) -> TableMetrics:
        """Размерные метрики таблицы из system.parts."""
        rows = self._execute(
            """
            SELECT
                sum(rows)                    AS total_rows,
                sum(bytes_on_disk)           AS total_bytes,
                sum(data_uncompressed_bytes) AS total_bytes_uncompressed
            FROM system.parts
            WHERE database = %(database)s
              AND table    = %(table)s
              AND active   = 1
            """,
            {"database": database, "table": table},
        )
        if not rows or rows[0][0] is None:
            return TableMetrics(database=database, table=table)

        total_rows, total_bytes, total_bytes_uncompressed = rows[0]
        return TableMetrics(
            database=database,
            table=table,
            total_rows=int(total_rows or 0),
            total_bytes=int(total_bytes or 0),
            total_bytes_uncompressed=int(total_bytes_uncompressed or 0),
        )

    # ── выполнение запросов ───────────────────────────────────────────────────

    def run_query(self, query: str) -> QueryResult:
        """
        Выполняет SELECT и собирает метрики из `clickhouse_connect` `.summary`.

        Если `summary` не вернулась, использует wall-time как fallback только для duration.
        """
        if self._client is None:
            raise FetcherError(
                "Нет подключения — вызови connect() или используй контекстный менеджер"
            )
        if not self._is_read_query(query):
            raise FetcherError("run_query поддерживает только read-only SQL")

        wall_start = time.perf_counter()
        try:
            result = self._client.query(query)
        except Exception as e:
            raise FetcherError(f"ClickHouse error: {e}") from e
        wall_ms = (time.perf_counter() - wall_start) * 1000

        rows = list(result.result_rows or [])
        summary = getattr(result, "summary", None)

        duration_ms = float(wall_ms)
        read_rows = 0
        read_bytes = 0
        result_rows = len(rows)

        def _safe_float(value: object, default: float) -> float:
            try:
                return float(value)
            except Exception:
                return default

        def _safe_int(value: object, default: int) -> int:
            try:
                return int(value)
            except Exception:
                try:
                    return int(float(value))
                except Exception:
                    return default

        if isinstance(summary, dict):
            elapsed_ns = _safe_float(summary.get("elapsed_ns"), -1.0)
            elapsed_sec = _safe_float(summary.get("elapsed"), -1.0)
            duration_ms_raw = _safe_float(summary.get("query_duration_ms"), -1.0)

            if elapsed_ns >= 0:
                duration_ms = elapsed_ns / 1_000_000.0
            elif elapsed_sec >= 0:
                duration_ms = elapsed_sec * 1000.0
            elif duration_ms_raw >= 0:
                duration_ms = duration_ms_raw

            read_rows = _safe_int(summary.get("read_rows", 0) or 0, 0)
            read_bytes = _safe_int(summary.get("read_bytes", 0) or 0, 0)
            result_rows = _safe_int(summary.get("result_rows", result_rows) or result_rows, result_rows)
        else:
            logger.warning("clickhouse_connect summary недоступен, используется wall-time fallback")

        return QueryResult(
            rows=rows,
            duration_ms=float(duration_ms),
            read_rows=int(read_rows or 0),
            read_bytes=int(read_bytes or 0),
            result_rows=int(result_rows or 0),
        )

    def warmup(self, query: str) -> None:
        """Прогревочный запрос — выполняется без сбора метрик."""
        self._execute(query)


# ─── фабрика ─────────────────────────────────────────────────────────────────

def make_fetcher(connection: ConnectionConfig) -> Fetcher:
    """Фабрика fetcher'а (удобна для DI и единообразия в коде)."""
    return Fetcher(connection)
