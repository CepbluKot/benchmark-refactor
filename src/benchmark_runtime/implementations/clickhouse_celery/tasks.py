"""Celery worker-side задачи для ClickHouse benchmark execution."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from src.clickhouse_ddl import TableDDL

from ...types import BenchmarkVariantResult, SourceBenchmarkResult
from .common import (
    DEFAULT_MEASURED_PERCENTILES,
    compute_percentiles,
    compute_speedup_coefficients,
    json_dumps,
    make_readable_bytes,
)
from .result_store import ClickHouseBenchmarkResultStore, ClickHouseConnectionParams
from .settings import get_clickhouse_celery_worker_settings

logger = logging.getLogger(__name__)

SOURCE_BENCHMARK_TASK_NAME = "bench.source_benchmark"
VARIANT_BENCHMARK_TASK_NAME = "bench.variant_benchmark"


def _error_query_metrics() -> Dict[str, float]:
    """Стандартный набор метрик для случая ошибки."""
    return {
        "elapsed_ns": -1.0,
        "read_rows": -1.0,
        "read_bytes": -1.0,
        "written_rows": -1.0,
        "written_bytes": -1.0,
    }


def _to_metric_or_error(value: Any) -> float:
    """Безопасно приводит значение метрики к float, иначе возвращает `-1`."""
    if value is None:
        return -1.0
    try:
        return float(value)
    except Exception:
        return -1.0


def _is_error_query_metrics(metrics: Dict[str, float]) -> bool:
    """Определяет, что метрики помечены как ошибочные."""
    return float(metrics.get("elapsed_ns", -1.0)) < 0


class QueryPlanPayload(BaseModel):
    """Сериализуемый query-plan для Celery payload."""

    model_config = ConfigDict(extra="forbid")

    warmup_queries: List[str] = Field(default_factory=list)
    test_queries: List[str] = Field(default_factory=list)


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
    source_database: str
    test_database: Optional[str] = None
    source_table: str
    source_table_ddl: str
    query_plan: QueryPlanPayload
    max_iterations: int
    insert_rows_limit: Optional[int] = None
    measured_percentiles: List[int] = Field(default_factory=lambda: list(DEFAULT_MEASURED_PERCENTILES))


class VariantBenchmarkTaskPayload(BaseModel):
    """Payload variant benchmark задачи."""

    model_config = ConfigDict(extra="forbid")

    connection: ConnectionPayload
    result_connection: ConnectionPayload
    result_database: str
    result_table: str

    benchmark_run_id: int
    benchmark_started_at: datetime
    benchmark_id: str

    source_database: str
    source_table: str
    variant_database: str
    variant_table: str

    variant_mode: str
    variant_params: Dict[str, Any] = Field(default_factory=dict)
    variant_ddl: str

    max_iterations: int
    insert_rows_limit: Optional[int] = None
    query_plan: QueryPlanPayload

    source_benchmark: Optional[Dict[str, Any]] = None
    measured_percentiles: List[int] = Field(default_factory=lambda: list(DEFAULT_MEASURED_PERCENTILES))


class _ClickHouseRuntimeClient:
    """Минимальный клиент для benchmark worker-задач."""

    _stream_slots_lock = threading.Lock()
    _stream_slots: dict[tuple[str, int, str], threading.BoundedSemaphore] = {}

    def __init__(self, connection: ConnectionPayload) -> None:
        try:
            import clickhouse_connect
        except ImportError as exc:
            raise RuntimeError(
                "clickhouse-connect не установлен. Установи зависимости из requirements.txt"
            ) from exc

        self._client = clickhouse_connect.get_client(
            host=connection.host,
            port=connection.port,
            username=connection.login,
            password=connection.password,
        )
        worker_settings = get_clickhouse_celery_worker_settings()
        self._stream_connection = connection
        self._stream_client: Any = None
        self._stream_client_checked = False
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

    def create_database_if_not_exists(self, database: str) -> None:
        """Создаёт БД при отсутствии."""
        self.execute(f"CREATE DATABASE IF NOT EXISTS `{database}`")

    def drop_table_if_exists(self, database: str, table: str) -> None:
        """Удаляет таблицу если существует."""
        self.execute(f"DROP TABLE IF EXISTS `{database}`.`{table}`")

    def count_rows(self, database: str, table: str) -> int:
        """Количество строк в таблице."""
        rows = self.execute(
            f"SELECT count() FROM `{database}`.`{table}`"
        )
        if not rows:
            return 0
        return int(rows[0][0] or 0)

    def get_total_compressed_size_bytes(self, database: str, table: str) -> float:
        """Суммарный compressed size таблицы."""
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
        if not rows or rows[0][0] is None:
            return 0.0
        return float(rows[0][0])

    def get_column_sizes(self, database: str, table: str) -> Dict[str, Dict[str, Any]]:
        """Размеры колонок (compressed bytes) + type."""
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
        result: dict[str, dict[str, Any]] = {}
        for name, data_type, compressed_bytes in rows:
            bytes_value = int(compressed_bytes or 0)
            result[str(name)] = {
                "name": str(name),
                "datatype": str(data_type),
                "size_compressed_bytes": bytes_value,
                "size_compressed_bytes_readable": make_readable_bytes(bytes_value),
            }
        return result

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

    def execute_with_query_log_metrics(
        self,
        query: str,
        *,
        query_tag: str,
        poll_attempts: int = 25,
        poll_sleep_sec: float = 0.1,
    ) -> Dict[str, float]:
        """Выполняет запрос и возвращает метрики из `system.query_log`."""
        tag = f"bench_qid:{query_tag}"
        self.execute(f"/* {tag} */ {query}")
        metrics = self._poll_query_log_metrics(
            tag=tag,
            poll_attempts=poll_attempts,
            poll_sleep_sec=poll_sleep_sec,
        )
        if metrics is not None:
            return metrics

        return _error_query_metrics()

    def execute_select_with_metrics(
        self,
        query: str,
        *,
        query_tag: str,
        poll_attempts: int = 25,
        poll_sleep_sec: float = 0.1,
    ) -> Dict[str, float]:
        """
        Выполняет SELECT и возвращает метрики максимально быстрым способом.

        Приоритет:
        1) `clickhouse-connect.command` с `QuerySummary` (без похода в system.query_log);
        2) если summary недоступен — читаем query_log по уже выполненному tagged запросу;
        3) если запрос через stream-клиент не удался — fallback на стандартный путь.
        """
        tag = f"bench_qid:{query_tag}"
        tagged_query = f"/* {tag} */ {query}"

        stream_client = self._get_stream_client()
        if stream_client is not None:
            try:
                command_result = stream_client.command(tagged_query)
                summary_metrics = self._extract_stream_query_summary(command_result)
                if summary_metrics is not None:
                    return summary_metrics

                query_log_metrics = self._poll_query_log_metrics(
                    tag=tag,
                    poll_attempts=poll_attempts,
                    poll_sleep_sec=poll_sleep_sec,
                )
                if query_log_metrics is not None:
                    return query_log_metrics

                logger.warning("Нет summary/query_log метрик для select tag=%s после stream command", tag)
                return _error_query_metrics()
            except Exception:
                logger.exception("Stream command для select не удался: fallback на query_log путь")

        return self.execute_with_query_log_metrics(
            query,
            query_tag=query_tag,
            poll_attempts=poll_attempts,
            poll_sleep_sec=poll_sleep_sec,
        )

    def _poll_query_log_metrics(
        self,
        *,
        tag: str,
        poll_attempts: int,
        poll_sleep_sec: float,
    ) -> Optional[Dict[str, float]]:
        """Ищет метрики запроса в `system.query_log` по tag."""
        pattern = f"%{tag}%"
        for _ in range(max(1, poll_attempts)):
            rows = self.execute(
                """
                SELECT
                    query_duration_ms,
                    read_rows,
                    read_bytes,
                    written_rows,
                    written_bytes
                FROM system.query_log
                WHERE type = 'QueryFinish'
                  AND query LIKE %(pattern)s
                ORDER BY event_time DESC
                LIMIT 1
                """,
                {"pattern": pattern},
            )
            if rows:
                duration_ms, read_rows, read_bytes, written_rows, written_bytes = rows[0]
                duration_ms_value = _to_metric_or_error(duration_ms)
                elapsed_ns = (
                    duration_ms_value * 1_000_000.0 if duration_ms_value >= 0 else -1.0
                )
                return {
                    "elapsed_ns": elapsed_ns,
                    "read_rows": _to_metric_or_error(read_rows),
                    "read_bytes": _to_metric_or_error(read_bytes),
                    "written_rows": _to_metric_or_error(written_rows),
                    "written_bytes": _to_metric_or_error(written_bytes),
                }
            time.sleep(poll_sleep_sec)
        logger.warning("Query log не найден для tag=%s", tag)
        return None

    def _get_stream_client(self) -> Any:
        """
        Возвращает clickhouse-connect client для streaming copy.

        Возвращает `None`, если библиотека/подключение недоступны.
        """
        if self._stream_client_checked:
            return self._stream_client

        self._stream_client_checked = True
        try:
            import clickhouse_connect
        except ImportError:
            logger.debug("clickhouse-connect не установлен: используем fallback insert через query_log")
            self._stream_client = None
            return None

        try:
            self._stream_client = clickhouse_connect.get_client(
                host=self._stream_connection.host,
                port=self._stream_connection.port,
                username=self._stream_connection.login,
                password=self._stream_connection.password,
            )
        except Exception:
            logger.exception("Не удалось создать clickhouse-connect client: используем fallback insert")
            self._stream_client = None
        return self._stream_client

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
            return False

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
        2) fallback через `INSERT INTO ... SELECT ...` + query_log.
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
                query_summary = stream_client.raw_insert(
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
        return self.execute_with_query_log_metrics(insert_query, query_tag=query_tag)


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
    read_rows_per_second_entries: list[float] = []
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
        read_rows = float(query_metrics["read_rows"])
        read_bytes = float(query_metrics["read_bytes"])
        written_rows = float(query_metrics["written_rows"])

        elapsed_ns_entries.append(elapsed_ns)
        read_rows_per_second_entries.append(_rows_per_second(read_rows, elapsed_ns))
        read_bytes_per_second_entries.append(_bytes_per_second(read_bytes, elapsed_ns))
        written_rows_entries.append(written_rows)

    return {
        "elapsed_ns": elapsed_ns_entries,
        "rows_per_second": read_rows_per_second_entries,
        "bytes_per_second": read_bytes_per_second_entries,
        "written_rows": written_rows_entries,
    }


def _measure_select_queries(
    client: _ClickHouseRuntimeClient,
    *,
    test_queries: Sequence[str],
    n_measurements: int,
) -> Dict[str, Any]:
    """Собирает замеры SELECT-запросов."""
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

    for query_index, query in enumerate(test_queries):
        query_elapsed_ns_entries: list[float] = []
        query_rows_per_second_entries: list[float] = []
        query_bytes_per_second_entries: list[float] = []
        for measurement_id in range(max(1, n_measurements)):
            attempt_n = 0
            sleep_sec = initial_sleep_sec
            query_metrics: Dict[str, float] = _error_query_metrics()
            while True:
                query_metrics = client.execute_select_with_metrics(
                    query,
                    query_tag=f"select-{uuid.uuid4().hex}",
                )
                if not _is_error_query_metrics(query_metrics):
                    break

                if max_retries != -1 and attempt_n >= max_retries:
                    logger.error(
                        "Не удалось получить корректные select-метрики (query=%s, measurement=%d): "
                        "достигнут лимит retries=%d",
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

            elapsed_ns_entries.append(elapsed_ns)
            read_rows_per_second_entries.append(query_rows_per_second)
            read_bytes_per_second_entries.append(query_bytes_per_second)

            query_elapsed_ns_entries.append(elapsed_ns)
            query_rows_per_second_entries.append(query_rows_per_second)
            query_bytes_per_second_entries.append(query_bytes_per_second)

        per_query_entries.append(
            {
                "query_index": query_index,
                "query": query,
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

        elapsed_ns_measurements = list(
            float(value) for value in (raw_entry.get("elapsed_ns_measurements", []) or [])
        )
        rows_per_second_measurements = list(
            float(value) for value in (raw_entry.get("rows_per_second_measurements", []) or [])
        )
        bytes_per_second_measurements = list(
            float(value) for value in (raw_entry.get("bytes_per_second_measurements", []) or [])
        )

        elapsed_ms_measurements = [
            value / 1_000_000.0 for value in elapsed_ns_measurements
        ]

        result.append(
            {
                "query_index": query_index,
                "query": query,
                "elapsed_ms_measurements": elapsed_ms_measurements,
                "elapsed_ms_percentiles": compute_percentiles(
                    elapsed_ms_measurements,
                    measured_percentiles,
                ),
                "rows_per_second_measurements": rows_per_second_measurements,
                "rows_per_second_percentiles": compute_percentiles(
                    rows_per_second_measurements,
                    measured_percentiles,
                ),
                "bytes_per_second_measurements": bytes_per_second_measurements,
                "bytes_per_second_percentiles": compute_percentiles(
                    bytes_per_second_measurements,
                    measured_percentiles,
                ),
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
        return [entry for entry in direct_value if isinstance(entry, dict)]

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
            "query": str(legacy_query or ""),
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
    for fallback_index, entry in enumerate(source_per_query):
        source_by_index[int(entry.get("query_index", fallback_index))] = entry

    result: list[dict[str, Any]] = []
    for fallback_index, tested_entry in enumerate(tested_per_query):
        query_index = int(tested_entry.get("query_index", fallback_index))
        source_entry = source_by_index.get(query_index)
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
                "query": tested_entry.get("query"),
                "source_query": source_entry.get("query") if source_entry is not None else None,
                "elapsed_ms_percentiles_speed_up_coefs": speed_up_coefs,
            }
        )
    return result


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
    try:
        parsed = TableDDL.from_ddl(source_table_ddl)
        parsed.name = f"{target_database}.{target_table}"
        return parsed.to_ddl()
    except Exception:
        # Fallback для synthetic/legacy DDL из тестов (например, с `(...)`),
        # когда строгий парсер не может разобрать список колонок.
        target_ref = f"`{target_database}`.`{target_table}`"
        create_table_pattern = re.compile(
            r"(?is)^\s*(CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?)\s+"
            r"((?:`[^`]+`|\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)(?:\s*\.\s*(?:`[^`]+`|\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*))?)"
        )
        rewritten_ddl, replaced = create_table_pattern.subn(
            rf"\1 {target_ref}",
            source_table_ddl,
            count=1,
        )
        if replaced == 0:
            raise
        return rewritten_ddl


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
        client.create_database_if_not_exists(baseline_database)
        client.drop_table_if_exists(baseline_database, baseline_table)
        baseline_ddl = _build_baseline_copy_ddl(
            payload.source_table_ddl,
            target_database=baseline_database,
            target_table=baseline_table,
        )
        client.execute(baseline_ddl)

        baseline_warmup_queries = _rewrite_queries_to_baseline_copy(
            payload.query_plan.warmup_queries,
            source_database=payload.source_database,
            source_table=payload.source_table,
            baseline_database=baseline_database,
            baseline_table=baseline_table,
        )
        baseline_test_queries = _rewrite_queries_to_baseline_copy(
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

        for warmup_query in baseline_warmup_queries:
            client.execute(warmup_query)

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
        source_columns_sizes = client.get_column_sizes(payload.source_database, payload.source_table)
        source_total_size_bytes = client.get_total_compressed_size_bytes(
            payload.source_database,
            payload.source_table,
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
                baseline_test_queries[0] if baseline_test_queries else ""
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
            "source_table_consumed_compressed_size_bytes_by_each_column": source_columns_sizes,
            "source_table_consumed_compressed_size_bytes_overall": source_total_size_bytes,
            "source_table_consumed_compressed_size_bytes_overall_readable": make_readable_bytes(
                source_total_size_bytes
            ),
            "source_table_n_rows_in_size_test": source_total_rows,
            "total_n_rows_in_source_table": source_total_rows,
        }

        baseline_score: Optional[float]
        if select_time_ms_percentiles and select_time_ms_percentiles[-1] > 0:
            baseline_score = 1.0 / float(select_time_ms_percentiles[-1])
        else:
            baseline_score = None

        return SourceBenchmarkResult(
            benchmark_run_id=payload.benchmark_run_id,
            benchmark_started_at=payload.benchmark_started_at,
            benchmark_id=payload.benchmark_id,
            source_database=payload.source_database,
            source_table=payload.source_table,
            source_table_ddl=payload.source_table_ddl,
            score=baseline_score,
            metrics=metrics,
        )
    finally:
        try:
            client.drop_table_if_exists(baseline_database, baseline_table)
        except Exception:
            logger.exception(
                "run_source_benchmark: ошибка drop table %s.%s",
                baseline_database,
                baseline_table,
            )
        client.close()


def run_variant_benchmark(payload: VariantBenchmarkTaskPayload) -> BenchmarkVariantResult:
    """Реальное выполнение variant benchmark с сохранением результата в ClickHouse."""
    client = _ClickHouseRuntimeClient(payload.connection)
    result_store = ClickHouseBenchmarkResultStore(
        connection=payload.result_connection.to_result_store_params(),
        database=payload.result_database,
        table=payload.result_table,
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

    try:
        client.create_database_if_not_exists(payload.variant_database)
        client.drop_table_if_exists(payload.variant_database, payload.variant_table)
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

        for warmup_query in payload.query_plan.warmup_queries:
            client.execute(warmup_query)

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
        source_total_size_bytes = float(
            source_metrics.get("source_table_consumed_compressed_size_bytes_overall", 0.0) or 0.0
        )

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

        score_parts: list[float] = []
        if tested_insert_time_speedup:
            score_parts.append(float(tested_insert_time_speedup[-1]))
        if tested_select_time_speedup:
            score_parts.append(float(tested_select_time_speedup[-1]))
        if compression_overall_coef and compression_overall_coef > 0:
            score_parts.append(float(compression_overall_coef))
        if not score_parts and tested_select_time_ms_percentiles and tested_select_time_ms_percentiles[-1] > 0:
            score_parts.append(1.0 / float(tested_select_time_ms_percentiles[-1]))
        score = sum(score_parts) / len(score_parts) if score_parts else None

        result = BenchmarkVariantResult(
            benchmark_run_id=payload.benchmark_run_id,
            benchmark_started_at=payload.benchmark_started_at,
            benchmark_id=payload.benchmark_id,
            source_database=payload.source_database,
            source_table=payload.source_table,
            variant_table=payload.variant_table,
            variant_mode=payload.variant_mode,
            variant_params=dict(payload.variant_params),
            source_table_ddl=(
                payload.source_benchmark.get("source_table_ddl")
                if payload.source_benchmark
                else None
            ),
            tested_table_ddl=payload.variant_ddl,
            is_source_table_copy=False,
            index_params=(
                json_dumps(payload.variant_params.get("index_choices"))
                if payload.variant_params.get("index_choices") is not None
                else None
            ),
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
                payload.query_plan.test_queries[0] if payload.query_plan.test_queries else None
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
                json_dumps(tested_select_per_query_metrics)
                if tested_select_per_query_metrics
                else None
            ),
            source_table_select_metrics_by_query_json=(
                json_dumps(source_select_per_query_metrics)
                if source_select_per_query_metrics
                else None
            ),
            tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json=(
                json_dumps(tested_select_time_speedup_by_query)
                if tested_select_time_speedup_by_query
                else None
            ),
            tested_table_consumed_compressed_size_bytes_by_each_column=json_dumps(tested_columns_sizes),
            source_table_consumed_compressed_size_bytes_by_each_column=(
                json_dumps(source_columns_size_map) if source_columns_size_map else None
            ),
            tested_table_consumed_compressed_size_bytes_overall=tested_total_size_bytes,
            tested_table_consumed_compressed_size_bytes_overall_readable=make_readable_bytes(
                tested_total_size_bytes
            ),
            source_table_consumed_compressed_size_bytes_overall=source_total_size_bytes,
            source_table_consumed_compressed_size_bytes_overall_readable=make_readable_bytes(
                source_total_size_bytes
            ),
            tested_table_compression_overall_coef=compression_overall_coef,
            tested_table_compression_by_each_column_coef=json_dumps(compression_by_column_coef),
            source_table_n_rows_in_size_test=int(
                source_metrics.get("source_table_n_rows_in_size_test", 0) or 0
            ),
            tested_table_n_rows_in_size_test=tested_rows_count,
            tested_table_cols_sizes=json_dumps(tested_columns_sizes),
            tested_table_indexes_sizes=json_dumps(tested_indexes_sizes),
            tested_table_indexes_sizes_percent_from_col_size=json_dumps(
                tested_table_indexes_sizes_percent_from_col_size
            ),
            score=score,
        )

        result_store.store_worker_result(
            benchmark_run_id=payload.benchmark_run_id,
            benchmark_started_at=payload.benchmark_started_at,
            benchmark_id=payload.benchmark_id,
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
            client.drop_table_if_exists(payload.variant_database, payload.variant_table)
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

    @app.task(name=SOURCE_BENCHMARK_TASK_NAME, ignore_result=False)
    def source_benchmark_task(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Celery task: baseline benchmark исходной таблицы."""
        typed_payload = SourceBenchmarkTaskPayload.model_validate(payload)
        result = run_source_benchmark(typed_payload)
        return result.model_dump(mode="json")


    @app.task(name=VARIANT_BENCHMARK_TASK_NAME, ignore_result=True)
    def variant_benchmark_task(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Celery task: benchmark варианта таблицы + сохранение результата."""
        typed_payload = VariantBenchmarkTaskPayload.model_validate(payload)
        result = run_variant_benchmark(typed_payload)
        return result.model_dump(mode="json")
