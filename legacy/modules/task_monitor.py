import logging
import random
import sys
import time
import uuid
from datetime import datetime
from threading import Condition, Lock, Thread

from tqdm_loggable.auto import tqdm
from settings import settings

logger = logging.getLogger(__name__)


class TaskMonitorCelery:
    def __init__(self, app, benchmark_name: str = "") -> None:
        self.app = app
        self.benchmark_name = benchmark_name
        self.pbar = tqdm(
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
        self._task_ids = set()
        self._task_ids_lock = Lock()
        self.instance_id = uuid.uuid4().hex
        self.all_sent = False
        self.event_receiver_thr = Thread(target=self.event_receiver, daemon=True)
        self.max_retries = 30
        self.base_delay = 5
        self.max_delay = 15

    def start_event_listener(self) -> None:
        self.event_receiver_thr.start()

    def new_task_id(self) -> str:
        return f"{self.instance_id}-{uuid.uuid4().hex}"

    def register_task(self, task_id: str, n_tests: int = 1) -> None:
        with self._task_ids_lock:
            self._task_ids.add(task_id)
        self.inc_n_tests_sent(n_tests)

    def inc_n_tests_sent(self, n_tests: int = 1) -> None:
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
                {"sent": self.total_n_tests, "succ": self.succeeded, "fail": self.failed}
            )
            self.pbar.refresh()
            self._cond.notify_all()

    def _all_done_pred(self) -> bool:
        return self.all_sent and ((self.succeeded + self.failed) >= self.total_n_tests)

    def make_all_sent(self):
        with self._cond:
            self.all_sent = True
            self._cond.notify_all()

    def wait_for_completion(self, timeout: float | None = None) -> bool:
        with self._cond:
            return self._cond.wait_for(self._all_done_pred, timeout=timeout)

    def on_task_succeeded(self, event: dict) -> None:
        task_id = event.get("uuid") or event.get("task_id") or event.get("id")
        if not task_id:
            return
        with self._task_ids_lock:
            if task_id in self._task_ids:
                self._task_ids.remove(task_id)
                self._on_task_done(success=True)

    def on_task_failed(self, event: dict) -> None:
        task_id = event.get("uuid") or event.get("task_id") or event.get("id")
        if not task_id:
            return
        with self._task_ids_lock:
            if task_id in self._task_ids:
                self._task_ids.remove(task_id)
                self._on_task_done(success=False)

    def event_receiver(self) -> None:
        attempt = 0
        while True:
            try:
                with self.app.connection() as conn:
                    attempt = 0
                    recv = self.app.events.Receiver(
                        conn,
                        handlers={
                            "task-succeeded": self.on_task_succeeded,
                            "task-failed": self.on_task_failed,
                        },
                    )
                    recv.capture(limit=None, timeout=None, wakeup=True)
            except KeyboardInterrupt:
                logger.info("Event receiver stopped by KeyboardInterrupt")
                raise
            except Exception as e:
                attempt += 1
                if (self.max_retries is not None) and (attempt > self.max_retries):
                    logger.exception(
                        f"Event receiver: exhausted {self.max_retries} retries. Last error: {e}"
                    )
                    raise RuntimeError("Error, Event receiver achieved max retries, exiting...")
                backoff = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
                sleep_time = backoff + random.uniform(0, backoff * 0.1)
                logger.error(
                    f"Error occurred in event receiver "
                    f"(connecting to: {settings.RABBITMQ_HOSTNAME}:{settings.RABBITMQ_PORT}) "
                    f"(attempt #{attempt}): {e!r}. Retrying in {sleep_time:.1f}s..."
                )
                time.sleep(sleep_time)
            else:
                logger.info("Receiver finished normally — restarting receiver loop.")
                time.sleep(1.0)