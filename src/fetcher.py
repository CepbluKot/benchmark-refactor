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
from pydantic import BaseModel, Field
from typing import Dict, List, Optional

from src.models import ConnectionConfig
from src.clickhouse_ddl import TableDDL

logger = logging.getLogger(__name__)

# ─── системные БД, пропускаемые при databases="*" ────────────────────────────

_SYSTEM_DATABASES = frozenset({
    "system",
    "information_schema",
    "INFORMATION_SCHEMA",
    "_temporary_and_external_tables",
})


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
    duration_ms: float      # из system.query_log (серверное время)
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

    def create_table(self, table_ddl: TableDDL) -> None:
        """Создаёт таблицу по TableDDL-объекту."""
        self._execute(table_ddl.to_ddl())
        logger.info("Created table %s", table_ddl.name)

    def drop_table(
        self, database: str, table: str, if_exists: bool = True
    ) -> None:
        """Удаляет таблицу-вариант после теста или перед пересозданием."""
        exists = "IF EXISTS " if if_exists else ""
        self._execute(f"DROP TABLE {exists}`{database}`.`{table}`")
        logger.info("Dropped %s.%s", database, table)

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
        Выполняет SELECT и собирает метрики из system.query_log.
        query_log записывается асинхронно, поэтому делаем небольшую паузу
        и ищем последний запрос текущего соединения по initial_query_id.
        """
        # Получаем query_id текущего подключения чтобы точно найти запрос в логе
        query_id = self._generate_query_id()

        wall_start = time.perf_counter()
        rows = self._execute(f"/* qid:{query_id} */ {query}")
        wall_ms = (time.perf_counter() - wall_start) * 1000

        # Ждём пока query_log запишется (обычно < 100 ms)
        time.sleep(0.15)

        log_rows = self._execute(
            """
            SELECT
                query_duration_ms,
                read_rows,
                read_bytes,
                result_rows
            FROM system.query_log
            WHERE type = 'QueryFinish'
              AND query LIKE %(pattern)s
            ORDER BY event_time DESC
            LIMIT 1
            """,
            {"pattern": f"%qid:{query_id}%"},
        )

        if log_rows:
            duration_ms, read_rows, read_bytes, result_rows = log_rows[0]
        else:
            logger.warning("query_log entry not found for qid=%s, using wall time", query_id)
            duration_ms = wall_ms
            read_rows = read_bytes = result_rows = 0

        return QueryResult(
            rows=rows,
            duration_ms=float(duration_ms),
            read_rows=int(read_rows or 0),
            read_bytes=int(read_bytes or 0),
            result_rows=int(result_rows or 0),
        )

    @staticmethod
    def _generate_query_id() -> str:
        """Генерирует короткий query id для поиска записи в `system.query_log`."""
        import uuid
        return uuid.uuid4().hex[:12]

    def warmup(self, query: str) -> None:
        """Прогревочный запрос — выполняется без сбора метрик."""
        self._execute(query)


# ─── фабрика ─────────────────────────────────────────────────────────────────

def make_fetcher(connection: ConnectionConfig) -> Fetcher:
    """Фабрика fetcher'а (удобна для DI и единообразия в коде)."""
    return Fetcher(connection)
