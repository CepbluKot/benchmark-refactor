"""Мониторинг Celery-задач с прогрессом в логах."""

from __future__ import annotations

import logging
import random
import sys
import time
import uuid
from datetime import datetime
from threading import Condition, Lock, Thread
from typing import Any, Optional

logger = logging.getLogger(__name__)


class _NoopProgressBar:
    """Fallback-бар, если tqdm недоступен."""

    def __init__(self, desc: str) -> None:
        self.total = 0
        self._desc = desc

    def set_description(self, desc: str) -> None:
        self._desc = desc

    def set_postfix(self, postfix: dict[str, Any]) -> None:
        logger.info("%s %s", self._desc, postfix)

    def update(self, _: int) -> None:
        return

    def refresh(self) -> None:
        return

    def close(self) -> None:
        return


class TaskMonitorCelery:
    """
    Монитор Celery events (`task-succeeded` / `task-failed`) с progress-bar.

    Используется launcher-частью для ожидания завершения отправленного батча задач.
    Важно: Celery worker должен быть запущен с `-E` (`--events`), иначе события
    задач не будут приходить в monitor.
    """

    def __init__(self, app: Any, benchmark_name: str = "") -> None:
        self.app = app
        self.benchmark_name = benchmark_name

        try:
            # Используем тот же адаптер прогресс-бара, что и в legacy:
            # tqdm_loggable помогает корректно писать прогресс в проблемных log-output средах.
            from tqdm_loggable.auto import tqdm  # type: ignore
        except Exception:
            tqdm = None

        if tqdm is None:
            self.pbar = _NoopProgressBar(desc=f"{benchmark_name} tasks")
        else:
            self.pbar: Any = tqdm(
                total=0,
                desc=f"{benchmark_name} tasks",
                unit="task",
                dynamic_ncols=True,
                file=sys.stdout,
            )

        self.pbar_lock = Lock()
        self._cond = Condition(self.pbar_lock)
        self.total_n_tests = 0
        self.succeeded = 0
        self.failed = 0
        self._task_ids: set[str] = set()
        self._task_ids_lock = Lock()
        self.instance_id = uuid.uuid4().hex
        self.all_sent = False

        self.event_receiver_thr = Thread(target=self._event_receiver_loop, daemon=True)
        self.max_retries: Optional[int] = 30
        self.base_delay = 2.0
        self.max_delay = 10.0

    def start_event_listener(self) -> None:
        """Запускает фоновый поток подписки на Celery events."""
        if not self.event_receiver_thr.is_alive():
            logger.info(
                "TaskMonitorCelery: запускаем listener событий. "
                "Убедись, что worker стартовал с `-E` (`--events`)."
            )
            self.event_receiver_thr.start()

    def close(self) -> None:
        """Закрывает progress bar (idempotent)."""
        self.pbar.close()

    def new_task_id(self) -> str:
        """Генерирует уникальный task id в рамках монитор-инстанса."""
        return f"{self.instance_id}-{uuid.uuid4().hex}"

    def register_task(self, task_id: str, n_tests: int = 1) -> None:
        """Регистрирует отправленную задачу для отслеживания."""
        with self._task_ids_lock:
            self._task_ids.add(task_id)
        self._inc_n_tests_sent(n_tests)

    def make_all_sent(self) -> None:
        """Отмечает, что batch задач полностью отправлен."""
        with self._cond:
            self.all_sent = True
            self._cond.notify_all()

    def wait_for_completion(self, timeout: float | None = None) -> bool:
        """Блокируется до завершения всех зарегистрированных задач."""
        with self._cond:
            return self._cond.wait_for(self._all_done_pred, timeout=timeout)

    def _inc_n_tests_sent(self, n_tests: int = 1) -> None:
        with self._cond:
            self.total_n_tests += n_tests
            self.pbar.total = self.total_n_tests
            self.pbar.set_description(
                f"{datetime.now():%Y-%m-%d %H:%M:%S} {self.benchmark_name} tasks"
            )
            self.pbar.refresh()
            self._cond.notify_all()

    def _on_task_done(self, success: bool) -> None:
        with self._cond:
            if success:
                self.succeeded += 1
            else:
                self.failed += 1
            self.pbar.set_description(
                f"{datetime.now():%Y-%m-%d %H:%M:%S} {self.benchmark_name} tasks"
            )
            self.pbar.update(1)
            self.pbar.set_postfix(
                {
                    "sent": self.total_n_tests,
                    "succ": self.succeeded,
                    "fail": self.failed,
                }
            )
            self.pbar.refresh()
            self._cond.notify_all()

    def _all_done_pred(self) -> bool:
        return self.all_sent and ((self.succeeded + self.failed) >= self.total_n_tests)

    def _on_task_succeeded(self, event: dict[str, Any]) -> None:
        task_id = event.get("uuid") or event.get("task_id") or event.get("id")
        if not task_id:
            return
        with self._task_ids_lock:
            if task_id in self._task_ids:
                self._task_ids.remove(task_id)
                self._on_task_done(success=True)

    def _on_task_failed(self, event: dict[str, Any]) -> None:
        task_id = event.get("uuid") or event.get("task_id") or event.get("id")
        if not task_id:
            return
        with self._task_ids_lock:
            if task_id in self._task_ids:
                self._task_ids.remove(task_id)
                self._on_task_done(success=False)

    def _event_receiver_loop(self) -> None:
        attempt = 0
        while True:
            try:
                with self.app.connection() as conn:
                    attempt = 0
                    receiver = self.app.events.Receiver(
                        conn,
                        handlers={
                            "task-succeeded": self._on_task_succeeded,
                            "task-failed": self._on_task_failed,
                        },
                    )
                    receiver.capture(limit=None, timeout=None, wakeup=True)
            except KeyboardInterrupt:
                logger.info("TaskMonitorCelery: event loop остановлен KeyboardInterrupt")
                return
            except Exception as exc:
                attempt += 1
                if (self.max_retries is not None) and (attempt > self.max_retries):
                    logger.exception(
                        "TaskMonitorCelery: исчерпаны retry (%d). Последняя ошибка: %s",
                        self.max_retries,
                        exc,
                    )
                    raise RuntimeError("TaskMonitorCelery: exhausted retries") from exc
                backoff = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
                sleep_time = backoff + random.uniform(0, backoff * 0.1)
                logger.warning(
                    "TaskMonitorCelery: ошибка event receiver (attempt=%d), retry через %.1fs: %r",
                    attempt,
                    sleep_time,
                    exc,
                )
                time.sleep(sleep_time)
            else:
                logger.info("TaskMonitorCelery: receiver завершился штатно, перезапуск")
                time.sleep(1.0)
