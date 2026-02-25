"""Celery-based execution adapter для ClickHouse benchmark runtime."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

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
    QueryPlanPayload,
    SourceBenchmarkTaskPayload,
    VariantBenchmarkTaskPayload,
    app as default_worker_app,
)

logger = logging.getLogger(__name__)


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
        result_table: str = "combined_benchmark_results",
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
        self._result_table = result_table
        self._source_task_name = source_task_name
        self._variant_task_name = variant_task_name
        self._source_result_timeout_sec = source_result_timeout_sec
        self._progress_monitor_enabled = progress_monitor_enabled
        self._progress_monitor: Optional[TaskMonitorCelery] = None
        self._measured_percentiles = (
            list(measured_percentiles)
            if measured_percentiles is not None
            else list(DEFAULT_MEASURED_PERCENTILES)
        )
        self._store: Optional[BenchmarkResultStore] = None

    def bind_result_store(self, result_store: Optional[BenchmarkResultStore]) -> None:
        """Сохраняет store для совместимости с lifecycle runner (не используется)."""
        self._store = result_store

    def execute_source_benchmark(self, job: SourceBenchmarkJob) -> SourceBenchmarkResult:
        """Отправляет baseline-задачу в Celery и ждёт `SourceBenchmarkResult`."""
        source_payload = self._build_source_payload(job)
        logger.info(
            "CeleryClickHouseExecutionAdapter: dispatch source benchmark "
            "(run_id=%d, benchmark=%s, table=%s.%s)",
            job.benchmark_run_id,
            job.benchmark_id,
            job.source_database,
            job.source_table,
        )
        async_result = self._celery_app.send_task(
            self._source_task_name,
            kwargs={"payload": source_payload.model_dump(mode="json")},
            task_id=f"source-{uuid.uuid4().hex}",
            ignore_result=False,
        )
        raw_result = async_result.get(timeout=self._source_result_timeout_sec)
        if isinstance(raw_result, str):
            try:
                raw_result = json.loads(raw_result)
            except Exception:
                logger.exception("execute_source_benchmark: source task вернула некорректную строку")
                raise
        return SourceBenchmarkResult.model_validate(raw_result)

    def execute_variant(self, job: VariantJob) -> BenchmarkVariantResult:
        """Отправляет variant-задачу в Celery (fire-and-forget)."""
        variant_payload = self._build_variant_payload(job)
        task_id = self._next_task_id(job)
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
        self._celery_app.send_task(
            self._variant_task_name,
            kwargs={"payload": variant_payload.model_dump(mode="json")},
            task_id=task_id,
            ignore_result=True,
        )
        if self._progress_monitor is not None:
            self._progress_monitor.register_task(task_id)

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

    def open_progress_scope(self, scope_name: str) -> None:
        """Открывает новый progress-monitor для batch отправки задач."""
        if not self._progress_monitor_enabled:
            return
        if self._progress_monitor is not None:
            self.finalize_progress_scope(wait=False)
        self._progress_monitor = TaskMonitorCelery(self._celery_app, benchmark_name=scope_name)
        self._progress_monitor.start_event_listener()

    def wait_for_dispatched_tasks(
        self,
        stage_label: str,
        timeout: Optional[float] = None,
    ) -> bool:
        """Ожидает завершения зарегистрированных задач текущего progress-scope."""
        monitor = self._progress_monitor
        if monitor is None:
            return True

        logger.info("Ожидание завершения Celery batch: stage=%s", stage_label)
        monitor.make_all_sent()
        completed = monitor.wait_for_completion(timeout=timeout)
        monitor.close()
        self._progress_monitor = None

        if not completed:
            raise TimeoutError(f"Не дождались завершения Celery batch (stage={stage_label})")
        return True

    def finalize_progress_scope(self, wait: bool = False, timeout: Optional[float] = None) -> None:
        """Закрывает текущий progress-scope (с ожиданием или без)."""
        monitor = self._progress_monitor
        if monitor is None:
            return

        if wait:
            monitor.make_all_sent()
            monitor.wait_for_completion(timeout=timeout)
        monitor.close()
        self._progress_monitor = None

    def _build_source_payload(self, job: SourceBenchmarkJob) -> SourceBenchmarkTaskPayload:
        connection = self._resolve_connection(job.connection_id)
        result_connection = self._resolve_result_connection(job.connection_id)
        return SourceBenchmarkTaskPayload(
            connection=self._to_connection_payload(connection),
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            test_database=job.test_database,
            source_table=job.source_table,
            source_table_ddl=job.source_table_ddl.to_ddl(),
            result_connection=self._to_connection_payload(result_connection),
            result_database=self._result_database,
            result_table=self._result_table,
            query_plan=QueryPlanPayload(
                warmup_queries=list(job.query_plan.warmup_queries),
                test_queries=[query.query for query in job.query_plan.test_queries],
            ),
            max_iterations=job.max_iterations,
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
            result_table=self._result_table,
            benchmark_run_id=job.benchmark_run_id,
            benchmark_started_at=job.benchmark_started_at,
            benchmark_id=job.benchmark_id,
            source_database=job.source_database,
            source_table=job.source_table,
            variant_database=job.variant_database,
            variant_table=job.variant_table,
            variant_mode=job.variant_meta.mode,
            variant_params=build_variant_params(job.variant_meta),
            variant_ddl=job.variant_ddl.to_ddl(),
            max_iterations=job.max_iterations,
            insert_rows_limit=job.insert_rows_limit,
            scoring=job.scoring,
            query_plan=QueryPlanPayload(
                warmup_queries=list(job.query_plan.warmup_queries),
                test_queries=[query.query for query in job.query_plan.test_queries],
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
        monitor = self._ensure_progress_monitor(job)
        if monitor is not None:
            return monitor.new_task_id()
        return f"variant-{uuid.uuid4().hex}"

    def _ensure_progress_monitor(self, job: VariantJob) -> Optional[TaskMonitorCelery]:
        if not self._progress_monitor_enabled:
            return None
        if self._progress_monitor is None:
            self._progress_monitor = TaskMonitorCelery(
                self._celery_app,
                benchmark_name=f"{job.benchmark_id}:{job.source_database}.{job.source_table}",
            )
            self._progress_monitor.start_event_listener()
        return self._progress_monitor
