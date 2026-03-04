"""Celery-based execution adapter для ClickHouse benchmark runtime."""

from __future__ import annotations

import json
import logging
import os
import random
import time
import uuid
from typing import Any, Dict, List, Literal, Optional

from src.models import ConnectionConfig

from ...contracts.execution import BenchmarkExecutionAdapter
from ...contracts.result_store import BenchmarkResultStore
from ...types import (
    BenchmarkVariantResult,
    SourceBenchmarkJob,
    SourceBenchmarkResult,
    VariantJob,
    build_variant_params,
)
from .common import DEFAULT_MEASURED_PERCENTILES
from .progress import TaskMonitorCelery
from .tasks import (
    SOURCE_BENCHMARK_TASK_NAME,
    VARIANT_BENCHMARK_TASK_NAME,
    ConnectionPayload,
    QueryPayload,
    QueryPlanPayload,
    SourceBenchmarkTaskPayload,
    TaskPayloadRefPayload,
    VariantBenchmarkTaskPayload,
    app as default_worker_app,
)

logger = logging.getLogger(__name__)

_CELERY_RECONNECT_MAX_ATTEMPTS = int(
    os.getenv("BENCH_CELERY_RECONNECT_MAX_ATTEMPTS", "-1")
)
_CELERY_RECONNECT_INITIAL_SLEEP_SEC = max(
    0.0,
    float(os.getenv("BENCH_CELERY_RECONNECT_INITIAL_SLEEP_SEC", "1.0")),
)
_CELERY_RECONNECT_MAX_SLEEP_SEC = max(
    _CELERY_RECONNECT_INITIAL_SLEEP_SEC,
    float(os.getenv("BENCH_CELERY_RECONNECT_MAX_SLEEP_SEC", "15.0")),
)
_SOURCE_RESULT_POLL_SEC = max(
    0.1,
    float(os.getenv("BENCH_SOURCE_RESULT_POLL_SEC", "15.0")),
)
_CELERY_MAX_IN_FLIGHT_TASKS = max(
    0,
    int(os.getenv("BENCH_CELERY_MAX_IN_FLIGHT_TASKS", "0")),
)
_CELERY_IN_FLIGHT_WAIT_POLL_SEC = max(
    0.05,
    float(os.getenv("BENCH_CELERY_IN_FLIGHT_WAIT_POLL_SEC", "0.2")),
)
_CELERY_IN_FLIGHT_WAIT_TIMEOUT_SEC = max(
    0.0,
    float(os.getenv("BENCH_CELERY_IN_FLIGHT_WAIT_TIMEOUT_SEC", "0")),
)
_CELERY_REJECT_PUBLISH_MAX_ATTEMPTS = int(
    os.getenv("BENCH_CELERY_REJECT_PUBLISH_MAX_ATTEMPTS", "-1")
)
_CELERY_REJECT_PUBLISH_RETRY_SLEEP_SEC = max(
    0.05,
    float(os.getenv("BENCH_CELERY_REJECT_PUBLISH_RETRY_SLEEP_SEC", "1.0")),
)
_CELERY_PAYLOAD_STORE_ENABLED = str(
    os.getenv("BENCH_CELERY_PAYLOAD_STORE_ENABLED", "0")
).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_CELERY_PAYLOAD_STORE_STRICT = str(
    os.getenv("BENCH_CELERY_PAYLOAD_STORE_STRICT", "0")
).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_CELERY_PAYLOAD_STORE_TABLE = (
    str(os.getenv("BENCH_CELERY_PAYLOAD_STORE_TABLE", "benchmark_task_payloads")).strip()
    or "benchmark_task_payloads"
)
_CELERY_PAYLOAD_STORE_TTL_HOURS = max(
    1,
    int(os.getenv("BENCH_CELERY_PAYLOAD_STORE_TTL_HOURS", "168")),
)


class _ClickHouseTaskPayloadStore:
    """ClickHouse store для offload Celery task payload из broker message."""

    def __init__(
        self,
        *,
        connection: ConnectionConfig,
        database: str,
        table: str,
        ttl_hours: int,
    ) -> None:
        try:
            import clickhouse_connect
        except ImportError as exc:
            raise RuntimeError(
                "clickhouse-connect не установлен: payload store недоступен"
            ) from exc
        self._client = clickhouse_connect.get_client(
            host=connection.host,
            port=connection.port,
            username=connection.login,
            password=connection.password,
        )
        self._connection = connection
        self._database = str(database).strip()
        self._table = str(table).strip()
        self._ttl_hours = max(1, int(ttl_hours))
        self._ready = False

    def _escape_identifier(self, value: str) -> str:
        return str(value).replace("`", "``")

    def _qualified_table(self) -> str:
        return f"`{self._escape_identifier(self._database)}`.`{self._escape_identifier(self._table)}`"

    def _ensure_table(self) -> None:
        if self._ready:
            return
        self._client.command(
            f"CREATE DATABASE IF NOT EXISTS `{self._escape_identifier(self._database)}`"
        )
        self._client.command(
            (
                f"CREATE TABLE IF NOT EXISTS {self._qualified_table()} ("
                "payload_id String, "
                "payload_kind LowCardinality(String), "
                "created_at DateTime64(3, 'UTC') DEFAULT now64(3), "
                "payload_json String"
                ") "
                "ENGINE = MergeTree "
                "ORDER BY (payload_kind, payload_id, created_at) "
                f"TTL created_at + INTERVAL {self._ttl_hours} HOUR DELETE"
            )
        )
        self._ready = True

    def put_payload(
        self,
        *,
        payload_kind: str,
        payload_data: Dict[str, Any],
    ) -> TaskPayloadRefPayload:
        self._ensure_table()
        payload_id = uuid.uuid4().hex
        payload_json = json.dumps(
            payload_data,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=False,
            default=str,
        )
        self._client.insert(
            self._qualified_table(),
            [[payload_id, payload_kind, payload_json]],
            column_names=["payload_id", "payload_kind", "payload_json"],
        )
        return TaskPayloadRefPayload(
            payload_id=payload_id,
            payload_kind=payload_kind,
            storage_connection=ConnectionPayload(
                host=self._connection.host,
                port=self._connection.port,
                login=self._connection.login,
                password=self._connection.password,
            ),
            storage_database=self._database,
            storage_table=self._table,
        )


def _is_reject_publish_error(exc: Exception) -> bool:
    """
    Определяет ошибки publish reject из RabbitMQ (overflow=reject-publish).

    Такие ошибки не означают "битую" инфраструктуру; это backpressure и
    их нужно ретраить с паузой до освобождения очереди.
    """
    message = str(exc or "").lower()
    markers = (
        "reject-publish",
        "basic.nack",
        "overflow",
        "max-length",
        "max length",
        "queue length limit",
        "x-max-length-bytes",
        "resource-locked",
    )
    return any(marker in message for marker in markers)


def _is_retryable_broker_error(exc: Exception) -> bool:
    """Определяет временные ошибки брокера/транспорта Celery/Kombu."""
    try:
        from kombu.exceptions import OperationalError as KombuOperationalError  # type: ignore
    except Exception:  # pragma: no cover
        KombuOperationalError = tuple()  # type: ignore
    try:
        from amqp.exceptions import (  # type: ignore
            AccessRefused as AmqpAccessRefused,
            ConnectionError as AmqpConnectionError,
            RecoverableConnectionError as AmqpRecoverableConnectionError,
        )
    except Exception:  # pragma: no cover
        AmqpAccessRefused = tuple()  # type: ignore
        AmqpConnectionError = tuple()  # type: ignore
        AmqpRecoverableConnectionError = tuple()  # type: ignore
    try:
        from celery.exceptions import TimeoutError as CeleryTimeoutError  # type: ignore
    except Exception:  # pragma: no cover
        CeleryTimeoutError = tuple()  # type: ignore

    if CeleryTimeoutError and isinstance(exc, CeleryTimeoutError):
        return False

    # AUTH ошибки не ретраим: это не восстановится само.
    if AmqpAccessRefused and isinstance(exc, AmqpAccessRefused):
        return False
    if _is_reject_publish_error(exc):
        return True

    retryable_types: tuple[type[BaseException], ...] = tuple(
        t
        for t in (
            KombuOperationalError,  # type: ignore[arg-type]
            AmqpConnectionError,  # type: ignore[arg-type]
            AmqpRecoverableConnectionError,  # type: ignore[arg-type]
            ConnectionError,
            OSError,
            TimeoutError,
        )
        if isinstance(t, type)
    )
    if retryable_types and isinstance(exc, retryable_types):
        return True

    message = str(exc or "").lower()
    transient_markers = (
        "connection refused",
        "connection reset",
        "connection aborted",
        "connection closed",
        "server unexpectedly closed",
        "timed out",
        "timeout",
        "temporary failure",
        "broker connection error",
        "broken pipe",
        "network is unreachable",
        "transport endpoint",
    )
    if any(marker in message for marker in transient_markers):
        return True
    if "access_refused" in message or "login was refused" in message:
        return False
    return False


class CeleryClickHouseExecutionAdapter(BenchmarkExecutionAdapter):
    """
    Реализация execution adapter, в которой benchmark выполняется Celery-воркерами.

    - `execute_source_benchmark` отправляет baseline-задачу и ждёт результат.
    - `execute_variant` отправляет variant-задачу fire-and-forget.
    - сохранение variant-результатов выполняется в воркере.
    - для progress-monitor/ожидания batch worker должен быть запущен с `-E` (`--events`).
    """

    def __init__(
        self,
        *,
        connections_by_id: Dict[str, ConnectionConfig],
        result_connections_by_id: Optional[Dict[str, ConnectionConfig]] = None,
        result_database: str = "benchmark_results",
        result_table: str = "benchmark_results",
        legacy_result_table: Optional[str] = None,
        phased_result_table: Optional[str] = None,
        phased_runs_table: str = "benchmark_runs",
        celery_app: Any = None,
        source_task_name: str = SOURCE_BENCHMARK_TASK_NAME,
        variant_task_name: str = VARIANT_BENCHMARK_TASK_NAME,
        source_result_timeout_sec: float = 3600.0,
        progress_monitor_enabled: bool = True,
        measured_percentiles: Optional[List[int]] = None,
    ) -> None:
        if celery_app is None:
            celery_app = default_worker_app
        if celery_app is None:
            raise RuntimeError(
                "Celery app не инициализирован. "
                "Передай `celery_app` явно или установи BENCH_CELERY_BROKER_URL/BENCH_CELERY_BACKEND_URL."
            )

        self._celery_app = celery_app
        self._connections_by_id = dict(connections_by_id)
        self._result_connections_by_id = (
            dict(result_connections_by_id)
            if result_connections_by_id is not None
            else {}
        )
        self._result_database = result_database
        self._legacy_result_table = legacy_result_table or result_table
        self._phased_result_table = phased_result_table or result_table
        self._phased_runs_table = phased_runs_table
        self._source_task_name = source_task_name
        self._variant_task_name = variant_task_name
        self._source_result_timeout_sec = source_result_timeout_sec
        self._progress_monitor_enabled = progress_monitor_enabled
        self._stage_progress_monitor: Optional[TaskMonitorCelery] = None
        self._global_progress_monitor: Optional[TaskMonitorCelery] = None
        self._measured_percentiles = (
            list(measured_percentiles)
            if measured_percentiles is not None
            else list(DEFAULT_MEASURED_PERCENTILES)
        )
        self._store: Optional[BenchmarkResultStore] = None
        self._payload_store_enabled = _CELERY_PAYLOAD_STORE_ENABLED
        self._payload_store_strict = _CELERY_PAYLOAD_STORE_STRICT
        self._payload_store_table = _CELERY_PAYLOAD_STORE_TABLE
        self._payload_store_ttl_hours = _CELERY_PAYLOAD_STORE_TTL_HOURS
        self._payload_store_by_connection_key: Dict[
            tuple[str, int, str, str, str],
            _ClickHouseTaskPayloadStore,
        ] = {}

    @staticmethod
    def _compute_retry_delay_sec(attempt_no: int) -> float:
        """Экспоненциальный backoff с небольшим jitter."""
        if _CELERY_RECONNECT_INITIAL_SLEEP_SEC <= 0:
            return 0.0
        backoff = min(
            _CELERY_RECONNECT_INITIAL_SLEEP_SEC * (2 ** max(0, attempt_no - 1)),
            _CELERY_RECONNECT_MAX_SLEEP_SEC,
        )
        jitter = random.uniform(0.0, min(1.0, backoff * 0.1))
        return backoff + jitter

    @staticmethod
    def _safe_async_state(async_result: Any) -> str:
        """Безопасно извлекает состояние AsyncResult без падения runner-а."""
        try:
            state = getattr(async_result, "state", None)
            state_text = str(state or "").strip()
            return state_text or "UNKNOWN"
        except Exception:
            return "UNKNOWN"

    def _run_broker_retry(
        self,
        *,
        action_name: str,
        operation: Any,
        deadline_ts: Optional[float] = None,
    ) -> Any:
        """
        Выполняет Celery/Kombu вызов с reconnect-retry при временных ошибках брокера.
        """
        attempt_no = 0
        while True:
            try:
                return operation()
            except Exception as exc:
                if not _is_retryable_broker_error(exc):
                    raise
                attempt_no += 1
                is_reject_publish = _is_reject_publish_error(exc)
                max_attempts = (
                    _CELERY_REJECT_PUBLISH_MAX_ATTEMPTS
                    if is_reject_publish
                    else _CELERY_RECONNECT_MAX_ATTEMPTS
                )
                if max_attempts != -1 and attempt_no > max_attempts:
                    raise RuntimeError(
                        f"{action_name}: исчерпаны retry "
                        f"({max_attempts}) для reconnect к RabbitMQ"
                    ) from exc
                if deadline_ts is not None:
                    remaining_sec = deadline_ts - time.monotonic()
                    if remaining_sec <= 0:
                        raise TimeoutError(
                            f"{action_name}: timeout ожидания reconnect к RabbitMQ"
                        ) from exc
                else:
                    remaining_sec = None
                if is_reject_publish:
                    sleep_sec = _CELERY_REJECT_PUBLISH_RETRY_SLEEP_SEC
                else:
                    sleep_sec = self._compute_retry_delay_sec(attempt_no)
                if remaining_sec is not None:
                    sleep_sec = min(max(0.0, remaining_sec), sleep_sec)
                if is_reject_publish:
                    logger.warning(
                        "%s: queue full/reject-publish, retry attempt=%d через %.2fs: %s",
                        action_name,
                        attempt_no,
                        sleep_sec,
                        exc,
                    )
                else:
                    logger.warning(
                        "%s: временная ошибка RabbitMQ, retry attempt=%d через %.2fs: %s",
                        action_name,
                        attempt_no,
                        sleep_sec,
                        exc,
                    )
                if sleep_sec > 0:
                    time.sleep(sleep_sec)

    def _payload_store_key(
        self,
        *,
        connection: ConnectionConfig,
    ) -> tuple[str, int, str, str, str]:
        return (
            str(connection.host),
            int(connection.port),
            str(connection.login),
            str(self._result_database),
            str(self._payload_store_table),
        )

    def _get_payload_store(self, *, connection: ConnectionConfig) -> _ClickHouseTaskPayloadStore:
        key = self._payload_store_key(connection=connection)
        store = self._payload_store_by_connection_key.get(key)
        if store is not None:
            return store
        store = _ClickHouseTaskPayloadStore(
            connection=connection,
            database=self._result_database,
            table=self._payload_store_table,
            ttl_hours=self._payload_store_ttl_hours,
        )
        self._payload_store_by_connection_key[key] = store
        return store

    def _store_payload_in_db(
        self,
        *,
        payload_kind: str,
        payload_data: Dict[str, Any],
        storage_connection: ConnectionConfig,
    ) -> TaskPayloadRefPayload:
        store = self._get_payload_store(connection=storage_connection)
        return store.put_payload(
            payload_kind=payload_kind,
            payload_data=payload_data,
        )

    def _build_task_send_kwargs(
        self,
        *,
        payload_kind: Literal["source", "variant"],
        payload_data: Dict[str, Any],
        storage_connection: ConnectionConfig,
    ) -> Dict[str, Any]:
        """
        Формирует kwargs для send_task.

        Если включён payload offload, в broker отправляется только `payload_ref`,
        а полный payload хранится в ClickHouse.
        """
        if not self._payload_store_enabled:
            return {"payload": payload_data}
        try:
            payload_ref = self._store_payload_in_db(
                payload_kind=payload_kind,
                payload_data=payload_data,
                storage_connection=storage_connection,
            )
            return {"payload_ref": payload_ref.model_dump(mode="json")}
        except Exception:
            logger.exception(
                "CeleryClickHouseExecutionAdapter: payload offload в ClickHouse не удался "
                "(kind=%s, run_id=%s, benchmark=%s), fallback inline payload=%s",
                payload_kind,
                payload_data.get("benchmark_run_id"),
                payload_data.get("benchmark_id"),
                "disabled" if not self._payload_store_strict else "forbidden",
            )
            if self._payload_store_strict:
                raise
            return {"payload": payload_data}

    def bind_result_store(self, result_store: Optional[BenchmarkResultStore]) -> None:
        """Сохраняет store для совместимости с lifecycle runner (не используется)."""
        self._store = result_store

    def execute_source_benchmark(self, job: SourceBenchmarkJob) -> SourceBenchmarkResult:
        """Отправляет baseline-задачу в Celery и ждёт `SourceBenchmarkResult`."""
        result_connection = self._resolve_result_connection(job.connection_id)
        source_payload = self._build_source_payload(job)
        source_payload_json = source_payload.model_dump(mode="json")
        source_task_kwargs = self._build_task_send_kwargs(
            payload_kind="source",
            payload_data=source_payload_json,
            storage_connection=result_connection,
        )
        logger.info(
            "CeleryClickHouseExecutionAdapter: dispatch source benchmark "
            "(run_id=%d, benchmark=%s, table=%s.%s)",
            job.benchmark_run_id,
            job.benchmark_id,
            job.source_database,
            job.source_table,
        )
        source_task_id = f"source-{uuid.uuid4().hex}"
        deadline_ts = time.monotonic() + float(max(1.0, self._source_result_timeout_sec))
        async_result = self._run_broker_retry(
            action_name="dispatch source task",
            deadline_ts=deadline_ts,
            operation=lambda: self._celery_app.send_task(
                self._source_task_name,
                kwargs=source_task_kwargs,
                task_id=source_task_id,
                expires=None,
                ignore_result=False,
            ),
        )

        while True:
            remaining_sec = deadline_ts - time.monotonic()
            if remaining_sec <= 0:
                raise TimeoutError(
                    f"Не дождались source task: task_id={source_task_id}, state={self._safe_async_state(async_result)}"
                )
            poll_timeout = min(_SOURCE_RESULT_POLL_SEC, max(0.1, remaining_sec))
            try:
                raw_result = self._run_broker_retry(
                    action_name="get source task result",
                    deadline_ts=deadline_ts,
                    operation=lambda: async_result.get(timeout=poll_timeout),
                )
                break
            except Exception as exc:
                try:
                    from celery.exceptions import TimeoutError as CeleryTimeoutError  # type: ignore
                except Exception:  # pragma: no cover
                    CeleryTimeoutError = TimeoutError  # type: ignore
                if isinstance(exc, CeleryTimeoutError):
                    logger.info(
                        "Ожидание source task: task_id=%s, state=%s, remaining_sec=%.1f",
                        source_task_id,
                        self._safe_async_state(async_result),
                        remaining_sec,
                    )
                    continue
                raise
        try:
            if isinstance(raw_result, str):
                try:
                    raw_result = json.loads(raw_result)
                except Exception:
                    logger.exception("execute_source_benchmark: source task вернула некорректную строку")
                    raise
            return SourceBenchmarkResult.model_validate(raw_result)
        finally:
            self._forget_async_result(async_result, source_task_id)

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        """Отправляет variant-задачу в Celery (fire-and-forget)."""
        self._wait_for_dispatch_slot(job)
        result_connection = self._resolve_result_connection(job.connection_id)
        variant_payload = self._build_variant_payload(job)
        task_id = self._next_task_id(job)
        if "celery_task_id" not in variant_payload.variant_params:
            variant_payload.variant_params["celery_task_id"] = task_id
        variant_payload_json = variant_payload.model_dump(mode="json")
        variant_task_kwargs = self._build_task_send_kwargs(
            payload_kind="variant",
            payload_data=variant_payload_json,
            storage_connection=result_connection,
        )
        logger.debug(
            "CeleryClickHouseExecutionAdapter: dispatch variant "
            "(run_id=%d, benchmark=%s, table=%s.%s, variant=%s, mode=%s, task_id=%s)",
            job.benchmark_run_id,
            job.benchmark_id,
            job.source_database,
            job.source_table,
            job.variant_table,
            job.variant_meta.mode,
            task_id,
        )
        self._run_broker_retry(
            action_name="dispatch variant task",
            operation=lambda: self._celery_app.send_task(
                self._variant_task_name,
                kwargs=variant_task_kwargs,
                task_id=task_id,
                expires=None,
                ignore_result=True,
            ),
        )
        self._register_dispatched_task(task_id=task_id)

        return BenchmarkVariantResult(
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_table=job.variant_table,
            variant_mode=job.variant_meta.mode,
            score=None,
            extra_json=json.dumps({"status": "dispatched", "task_id": task_id}),
        )

    def _wait_for_dispatch_slot(self, job: VariantJob) -> None:
        """
        Ограничивает число in-flight задач, чтобы не раздувать backlog RabbitMQ.

        Контроль выполняется только если включён `BENCH_CELERY_MAX_IN_FLIGHT_TASKS > 0`
        и доступен progress-monitor, который получает Celery events.
        """
        if _CELERY_MAX_IN_FLIGHT_TASKS <= 0:
            return
        monitor = self._global_progress_monitor or self._ensure_stage_progress_monitor(job)
        if monitor is None:
            return

        start_ts = time.monotonic()
        last_log_ts = 0.0
        while True:
            in_flight = monitor.in_flight_tasks()
            if in_flight < _CELERY_MAX_IN_FLIGHT_TASKS:
                return

            now_ts = time.monotonic()
            if (now_ts - last_log_ts) >= 5.0:
                logger.info(
                    "CeleryClickHouseExecutionAdapter: in-flight limit reached "
                    "(in_flight=%d, limit=%d, benchmark=%s, table=%s.%s), ждём слот",
                    in_flight,
                    _CELERY_MAX_IN_FLIGHT_TASKS,
                    job.benchmark_id,
                    job.source_database,
                    job.source_table,
                )
                last_log_ts = now_ts

            if _CELERY_IN_FLIGHT_WAIT_TIMEOUT_SEC > 0:
                waited_sec = now_ts - start_ts
                if waited_sec >= _CELERY_IN_FLIGHT_WAIT_TIMEOUT_SEC:
                    logger.warning(
                        "CeleryClickHouseExecutionAdapter: in-flight wait timeout "
                        "(waited=%.2fs, limit=%d), продолжаем dispatch чтобы не зависнуть",
                        waited_sec,
                        _CELERY_MAX_IN_FLIGHT_TASKS,
                    )
                    return
            time.sleep(_CELERY_IN_FLIGHT_WAIT_POLL_SEC)

    def open_progress_scope(self, scope_name: str) -> None:
        """Открывает новый progress-monitor для batch отправки задач."""
        if not self._progress_monitor_enabled:
            return
        if self._stage_progress_monitor is not None:
            self.finalize_progress_scope(wait=False)
        self._stage_progress_monitor = TaskMonitorCelery(
            self._celery_app,
            benchmark_name=scope_name,
            progress_position=1,
            progress_leave=False,
        )
        self._stage_progress_monitor.start_event_listener()

    def open_global_progress_scope(
        self,
        scope_name: str,
        total_tasks: Optional[int] = None,
    ) -> None:
        """Открывает глобальный progress-monitor на весь lifecycle текущего runner.run()."""
        if not self._progress_monitor_enabled:
            return
        if self._global_progress_monitor is not None:
            self.finalize_global_progress_scope(wait=False)
        self._global_progress_monitor = TaskMonitorCelery(
            self._celery_app,
            benchmark_name=scope_name,
            progress_position=0,
            progress_leave=False,
            fixed_total=total_tasks,
        )
        self._global_progress_monitor.start_event_listener()

    def wait_for_dispatched_tasks(
        self,
        stage_label: str,
        timeout: Optional[float] = None,
    ) -> bool:
        """Ожидает завершения зарегистрированных задач текущего progress-scope."""
        monitor = self._stage_progress_monitor
        if monitor is None:
            return True

        logger.info("Ожидание завершения Celery batch: stage=%s", stage_label)
        monitor.make_all_sent()
        completed = monitor.wait_for_completion(timeout=timeout)
        monitor.close()
        self._stage_progress_monitor = None

        if not completed:
            raise TimeoutError(f"Не дождались завершения Celery batch (stage={stage_label})")
        return True

    def finalize_progress_scope(self, wait: bool = False, timeout: Optional[float] = None) -> None:
        """Закрывает текущий progress-scope (с ожиданием или без)."""
        monitor = self._stage_progress_monitor
        if monitor is None:
            return

        if wait:
            monitor.make_all_sent()
            monitor.wait_for_completion(timeout=timeout)
        monitor.close()
        self._stage_progress_monitor = None

    def finalize_global_progress_scope(
        self,
        wait: bool = False,
        timeout: Optional[float] = None,
    ) -> None:
        """Закрывает глобальный progress-scope (с ожиданием или без)."""
        monitor = self._global_progress_monitor
        if monitor is None:
            return

        if wait:
            monitor.make_all_sent()
            monitor.wait_for_completion(timeout=timeout)
        monitor.close()
        self._global_progress_monitor = None

    def _build_source_payload(self, job: SourceBenchmarkJob) -> SourceBenchmarkTaskPayload:
        connection = self._resolve_connection(job.connection_id)
        result_connection = self._resolve_result_connection(job.connection_id)
        return SourceBenchmarkTaskPayload(
            connection=self._to_connection_payload(connection),
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            benchmark_strategy=job.benchmark_strategy,
            source_database=job.source_database,
            test_database=job.test_database,
            source_table=job.source_table,
            source_table_ddl=job.source_table_ddl.to_ddl(),
            result_connection=self._to_connection_payload(result_connection),
            result_database=self._result_database,
            result_table=self._legacy_result_table,
            result_table_legacy=self._legacy_result_table,
            result_table_phased=self._phased_result_table,
            result_runs_table_phased=self._phased_runs_table,
            query_plan=QueryPlanPayload(
                test_queries=[
                    QueryPayload(
                        query_id=query.query_id,
                        query=query.query,
                        query_type=query.query_type,
                        cache_mode=query.cache_mode,
                        select_operations_count=query.select_operations_count,
                        warmup_queries=list(query.warmup_queries),
                    )
                    for query in job.query_plan.test_queries
                ],
            ),
            insert_operations_count=job.insert_operations_count,
            insert_rows_limit=job.insert_rows_limit,
            scoring=job.scoring,
            measured_percentiles=list(self._measured_percentiles),
        )

    def _build_variant_payload(self, job: VariantJob) -> VariantBenchmarkTaskPayload:
        connection = self._resolve_connection(job.connection_id)
        result_connection = self._resolve_result_connection(job.connection_id)
        return VariantBenchmarkTaskPayload(
            connection=self._to_connection_payload(connection),
            result_connection=self._to_connection_payload(result_connection),
            result_database=self._result_database,
            result_table=self._legacy_result_table,
            result_table_legacy=self._legacy_result_table,
            result_table_phased=self._phased_result_table,
            result_runs_table_phased=self._phased_runs_table,
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            benchmark_strategy=job.benchmark_strategy,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_database=job.variant_database,
            variant_table=job.variant_table,
            variant_mode=job.variant_meta.mode,
            variant_params=build_variant_params(job.variant_meta),
            variant_ddl=job.variant_ddl.to_ddl(),
            insert_operations_count=job.insert_operations_count,
            insert_rows_limit=job.insert_rows_limit,
            scoring=job.scoring,
            query_plan=QueryPlanPayload(
                test_queries=[
                    QueryPayload(
                        query_id=query.query_id,
                        query=query.query,
                        query_type=query.query_type,
                        cache_mode=query.cache_mode,
                        select_operations_count=query.select_operations_count,
                        warmup_queries=list(query.warmup_queries),
                    )
                    for query in job.query_plan.test_queries
                ],
            ),
            source_benchmark=(
                job.source_benchmark.model_dump(mode="json")
                if job.source_benchmark is not None
                else None
            ),
            measured_percentiles=list(self._measured_percentiles),
        )

    def _resolve_connection(self, connection_id: str) -> ConnectionConfig:
        if connection_id not in self._connections_by_id:
            raise ValueError(f"connection_id={connection_id!r} не найден в adapter.connections_by_id")
        return self._connections_by_id[connection_id]

    def _resolve_result_connection(self, connection_id: str) -> ConnectionConfig:
        return self._result_connections_by_id.get(
            connection_id,
            self._resolve_connection(connection_id),
        )

    @staticmethod
    def _to_connection_payload(connection: ConnectionConfig) -> ConnectionPayload:
        return ConnectionPayload(
            host=connection.host,
            port=connection.port,
            login=connection.login,
            password=connection.password,
        )

    def _next_task_id(self, job: VariantJob) -> str:
        monitor = self._global_progress_monitor or self._ensure_stage_progress_monitor(job)
        if monitor is not None:
            return monitor.new_task_id()
        return f"variant-{uuid.uuid4().hex}"

    @staticmethod
    def _forget_async_result(async_result: Any, task_id: str) -> None:
        """Пытается удалить task-result из backend после чтения (если backend это поддерживает)."""
        try:
            forget_fn = getattr(async_result, "forget", None)
            if callable(forget_fn):
                try:
                    forget_fn()
                except NotImplementedError:
                    # Нормальный кейс для backend-ов без explicit forget support.
                    logger.debug(
                        "CeleryClickHouseExecutionAdapter: backend не поддерживает forget "
                        "(task_id=%s)",
                        task_id,
                    )
                    return
        except Exception:
            logger.warning(
                "CeleryClickHouseExecutionAdapter: не удалось forget source result "
                "(task_id=%s)",
                task_id,
                exc_info=True,
            )

    def _register_dispatched_task(self, *, task_id: str) -> None:
        """Регистрирует dispatched task во всех активных progress-мониторах."""
        monitors: list[TaskMonitorCelery] = []
        if self._stage_progress_monitor is not None:
            monitors.append(self._stage_progress_monitor)
        if self._global_progress_monitor is not None and self._global_progress_monitor is not self._stage_progress_monitor:
            monitors.append(self._global_progress_monitor)

        for monitor in monitors:
            monitor.register_task(task_id)

    def _ensure_stage_progress_monitor(self, job: VariantJob) -> Optional[TaskMonitorCelery]:
        if not self._progress_monitor_enabled:
            return None
        if self._stage_progress_monitor is None:
            self._stage_progress_monitor = TaskMonitorCelery(
                self._celery_app,
                benchmark_name=f"{job.benchmark_id}:{job.source_database}.{job.source_table}",
                progress_position=1,
                progress_leave=False,
            )
            self._stage_progress_monitor.start_event_listener()
        return self._stage_progress_monitor
