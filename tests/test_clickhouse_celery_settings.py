import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from src.benchmark_runtime.implementations.clickhouse_celery.settings import (
    ClickHouseCeleryWorkerSettings,
    get_clickhouse_celery_worker_settings,
)


class ClickHouseCelerySettingsTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_clickhouse_celery_worker_settings.cache_clear()

    def test_reads_broker_and_backend_from_bench_urls(self) -> None:
        env = {
            "BENCH_CELERY_BROKER_URL": "pyamqp://bench_user:bench_pass@rmq.local:5679//",
            "BENCH_CELERY_BACKEND_URL": "redis://localhost:6379/0",
            "BENCH_CELERY_QUEUE_NAME": "bench.jobs",
            "CELERY_WORKER_CONCURRENCY": "8",
            "BENCH_CELERY_WORKER_PREFETCH_MULTIPLIER": "2",
            "BENCH_CELERY_TASK_ACKS_LATE": "false",
            "BENCH_CELERY_TASK_REJECT_ON_WORKER_LOST": "false",
            "BENCH_CELERY_BROKER_POOL_LIMIT": "20",
            "BENCH_CELERY_BROKER_HEARTBEAT_SEC": "45",
            "BENCH_CELERY_TASK_COMPRESSION": "zstd",
            "BENCH_CELERY_RESULT_COMPRESSION": "zstd",
            "CLICKHOUSE_MANAGER_MAX_CONCURRENT_STREAMS_PER_PROCESS": "3",
            "CLICKHOUSE_STREAM_SLOT_ACQUIRE_TIMEOUT_SEC": "1.5",
            "MAX_COPY_N_RETRIES": "5",
            "MAX_COPY_RETRY_SLEEP_SEC": "0.5",
            "MAX_COPY_RETRY_SLEEP_SEC_INCREMENT": "0.25",
            "BENCH_CELERY_TASK_DEFAULT_EXPIRES_SEC": "0",
            "BENCH_CELERY_RESULT_EXPIRES_SEC": "7200",
            "BENCH_CELERY_TASK_SOFT_TIME_LIMIT_SEC": "",
            "BENCH_CELERY_TASK_TIME_LIMIT_SEC": "3600",
            "BENCH_CELERY_BROKER_VISIBILITY_TIMEOUT_SEC": "43200",
        }
        with patch.dict(os.environ, env, clear=True):
            get_clickhouse_celery_worker_settings.cache_clear()
            settings = get_clickhouse_celery_worker_settings()

        self.assertEqual(
            settings.broker_url,
            "pyamqp://bench_user:bench_pass@rmq.local:5679//",
        )
        self.assertEqual(settings.backend_url, "redis://localhost:6379/0")
        self.assertEqual(settings.celery_queue_name, "bench.jobs")
        self.assertEqual(settings.celery_worker_concurrency, 8)
        self.assertEqual(settings.celery_worker_prefetch_multiplier, 2)
        self.assertFalse(settings.celery_task_acks_late)
        self.assertFalse(settings.celery_task_reject_on_worker_lost)
        self.assertEqual(settings.celery_broker_pool_limit, 20)
        self.assertEqual(settings.celery_broker_heartbeat_sec, 45)
        self.assertEqual(settings.celery_task_compression, "zstd")
        self.assertEqual(settings.celery_result_compression, "zstd")
        self.assertEqual(settings.clickhouse_manager_max_concurrent_streams_per_process, 3)
        self.assertEqual(settings.clickhouse_stream_slot_acquire_timeout_sec, 1.5)
        self.assertEqual(settings.max_copy_n_retries, 5)
        self.assertEqual(settings.max_copy_retry_sleep_sec, 0.5)
        self.assertEqual(settings.max_copy_retry_sleep_sec_increment, 0.25)
        self.assertIsNone(settings.celery_task_default_expires_sec)
        self.assertEqual(settings.celery_result_expires_sec, 7200.0)
        self.assertIsNone(settings.celery_task_soft_time_limit_sec)
        self.assertEqual(settings.celery_task_time_limit_sec, 3600.0)
        self.assertEqual(settings.celery_broker_visibility_timeout_sec, 43200)

    def test_broker_and_backend_urls_are_stripped(self) -> None:
        env = {
            "BENCH_CELERY_BROKER_URL": "  pyamqp://x:y@custom-rmq:5672//  ",
            "BENCH_CELERY_BACKEND_URL": "  redis://localhost:6379/0  ",
        }
        with patch.dict(os.environ, env, clear=True):
            get_clickhouse_celery_worker_settings.cache_clear()
            settings = get_clickhouse_celery_worker_settings()

        self.assertEqual(settings.broker_url, "pyamqp://x:y@custom-rmq:5672//")
        self.assertEqual(settings.backend_url, "redis://localhost:6379/0")

    def test_default_urls_are_valid(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = ClickHouseCeleryWorkerSettings(_env_file=None)

            self.assertEqual(settings.broker_url, "pyamqp://guest:guest@localhost:5672//")
            self.assertEqual(settings.backend_url, "rpc://guest:guest@localhost:5672//")
            self.assertEqual(settings.celery_queue_name, "bench.benchmark")
            self.assertEqual(settings.clickhouse_manager_max_concurrent_streams_per_process, 1)
            self.assertEqual(settings.celery_worker_prefetch_multiplier, 1)
            self.assertTrue(settings.celery_task_acks_late)
            self.assertTrue(settings.celery_task_reject_on_worker_lost)
            self.assertEqual(settings.celery_broker_pool_limit, 10)
            self.assertEqual(settings.celery_broker_heartbeat_sec, 30)
            self.assertEqual(settings.celery_task_compression, "gzip")
            self.assertEqual(settings.celery_result_compression, "gzip")
            self.assertIsNone(settings.clickhouse_stream_slot_acquire_timeout_sec)
            self.assertEqual(settings.max_copy_n_retries, 100)
            self.assertEqual(settings.max_copy_retry_sleep_sec, 10.0)
            self.assertEqual(settings.max_copy_retry_sleep_sec_increment, 2.0)
            self.assertIsNone(settings.celery_task_default_expires_sec)
            self.assertIsNone(settings.celery_result_expires_sec)
            self.assertIsNone(settings.celery_task_soft_time_limit_sec)
            self.assertIsNone(settings.celery_task_time_limit_sec)
            self.assertEqual(settings.celery_broker_visibility_timeout_sec, 86_400)

    def test_rejects_empty_bench_urls(self) -> None:
        with patch.dict(
            os.environ,
            {
                "BENCH_CELERY_BROKER_URL": " ",
                "BENCH_CELERY_BACKEND_URL": "rpc://x",
            },
            clear=True,
        ):
            get_clickhouse_celery_worker_settings.cache_clear()
            with self.assertRaises(ValidationError):
                get_clickhouse_celery_worker_settings()

        with patch.dict(
            os.environ,
            {
                "BENCH_CELERY_BROKER_URL": "pyamqp://x:y@z//",
                "BENCH_CELERY_BACKEND_URL": "  ",
            },
            clear=True,
        ):
            get_clickhouse_celery_worker_settings.cache_clear()
            with self.assertRaises(ValidationError):
                get_clickhouse_celery_worker_settings()

        with patch.dict(
            os.environ,
            {
                "BENCH_CELERY_BROKER_URL": "pyamqp://x:y@z//",
                "BENCH_CELERY_BACKEND_URL": "rpc://x",
                "BENCH_CELERY_QUEUE_NAME": "  ",
            },
            clear=True,
        ):
            get_clickhouse_celery_worker_settings.cache_clear()
            with self.assertRaises(ValidationError):
                get_clickhouse_celery_worker_settings()


if __name__ == "__main__":
    unittest.main()
