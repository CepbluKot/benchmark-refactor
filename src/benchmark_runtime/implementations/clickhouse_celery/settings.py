"""Настройки Celery worker для ClickHouse runtime."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ClickHouseCeleryWorkerSettings(BaseSettings):
    """Runtime-настройки Celery worker для benchmark задач."""

    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    celery_worker_concurrency: int = Field(
        default=4,
        validation_alias="CELERY_WORKER_CONCURRENCY",
        gt=0,
    )
    clickhouse_manager_max_concurrent_streams_per_process: int = Field(
        default=1,
        validation_alias="CLICKHOUSE_MANAGER_MAX_CONCURRENT_STREAMS_PER_PROCESS",
        gt=0,
    )
    clickhouse_stream_slot_acquire_timeout_sec: float | None = Field(
        default=None,
        validation_alias="CLICKHOUSE_STREAM_SLOT_ACQUIRE_TIMEOUT_SEC",
        gt=0,
    )
    max_copy_n_retries: int = Field(
        default=100,
        validation_alias="MAX_COPY_N_RETRIES",
        ge=-1,
    )
    max_copy_retry_sleep_sec: float = Field(
        default=10.0,
        validation_alias="MAX_COPY_RETRY_SLEEP_SEC",
        ge=0,
    )
    max_copy_retry_sleep_sec_increment: float = Field(
        default=2.0,
        validation_alias="MAX_COPY_RETRY_SLEEP_SEC_INCREMENT",
        ge=0,
    )
    celery_broker_url: str = Field(
        default="pyamqp://guest:guest@localhost:5672//",
        validation_alias="BENCH_CELERY_BROKER_URL",
    )
    celery_backend_url: str = Field(
        default="rpc://guest:guest@localhost:5672//",
        validation_alias="BENCH_CELERY_BACKEND_URL",
    )
    celery_queue_name: str = Field(
        default="bench.benchmark",
        validation_alias="BENCH_CELERY_QUEUE_NAME",
    )
    celery_task_default_expires_sec: float | None = Field(
        default=None,
        validation_alias="BENCH_CELERY_TASK_DEFAULT_EXPIRES_SEC",
    )
    celery_result_expires_sec: float | None = Field(
        default=None,
        validation_alias="BENCH_CELERY_RESULT_EXPIRES_SEC",
    )
    celery_task_soft_time_limit_sec: float | None = Field(
        default=None,
        validation_alias="BENCH_CELERY_TASK_SOFT_TIME_LIMIT_SEC",
    )
    celery_task_time_limit_sec: float | None = Field(
        default=None,
        validation_alias="BENCH_CELERY_TASK_TIME_LIMIT_SEC",
    )
    celery_broker_visibility_timeout_sec: int = Field(
        default=86_400,
        validation_alias="BENCH_CELERY_BROKER_VISIBILITY_TIMEOUT_SEC",
        gt=0,
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("celery_broker_url", mode="before")
    @classmethod
    def validate_celery_broker_url(cls, value: object) -> str:
        """Проверяет, что broker URL не пустой."""
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("BENCH_CELERY_BROKER_URL не должен быть пустым")
        return cleaned

    @field_validator("celery_backend_url", mode="before")
    @classmethod
    def validate_celery_backend_url(cls, value: object) -> str:
        """Проверяет, что backend URL не пустой."""
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("BENCH_CELERY_BACKEND_URL не должен быть пустым")
        return cleaned

    @field_validator("celery_queue_name", mode="before")
    @classmethod
    def validate_celery_queue_name(cls, value: object) -> str:
        """Проверяет, что имя очереди не пустое."""
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("BENCH_CELERY_QUEUE_NAME не должен быть пустым")
        return cleaned

    @field_validator(
        "celery_task_default_expires_sec",
        "celery_result_expires_sec",
        "celery_task_soft_time_limit_sec",
        "celery_task_time_limit_sec",
        mode="before",
    )
    @classmethod
    def normalize_optional_positive_seconds(cls, value: object) -> float | None:
        """
        Нормализует optional timeout/TTL.

        Пустые/нулевые/отрицательные значения трактуются как `None` (без ограничения).
        """
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = float(text)
        except Exception as exc:
            raise ValueError("Ожидалось число секунд или пустое значение") from exc
        if parsed <= 0:
            return None
        return parsed

    @property
    def broker_url(self) -> str:
        """Broker URL для Celery."""
        return self.celery_broker_url.strip()

    @property
    def backend_url(self) -> str:
        """Backend URL для Celery."""
        return self.celery_backend_url.strip()


@lru_cache(maxsize=1)
def get_clickhouse_celery_worker_settings() -> ClickHouseCeleryWorkerSettings:
    """Возвращает кэшированный инстанс worker settings."""
    return ClickHouseCeleryWorkerSettings()
