"""Настройки Celery worker для ClickHouse runtime (по аналогии с legacy settings)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
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
    rabbitmq_hostname: str = Field(
        default="localhost",
        validation_alias="RABBITMQ_HOSTNAME",
    )
    rabbitmq_login: SecretStr = Field(
        default=SecretStr("guest"),
        validation_alias="RABBITMQ_LOGIN",
    )
    rabbitmq_password: SecretStr = Field(
        default=SecretStr("guest"),
        validation_alias="RABBITMQ_PASSWORD",
    )
    rabbitmq_port: int = Field(
        default=5672,
        validation_alias="RABBITMQ_PORT",
        gt=0,
        lt=65536,
    )

    # Явные URL можно переопределить через env; если пусто — собираем из RABBITMQ_*
    celery_broker_url: str | None = Field(
        default=None,
        validation_alias="BENCH_CELERY_BROKER_URL",
    )
    celery_backend_url: str | None = Field(
        default=None,
        validation_alias="BENCH_CELERY_BACKEND_URL",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("rabbitmq_hostname", mode="before")
    @classmethod
    def validate_rabbitmq_hostname(cls, value: object) -> str:
        """Проверяет, что hostname не пустой."""
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("RABBITMQ_HOSTNAME не должен быть пустым")
        return cleaned

    @property
    def broker_url(self) -> str:
        """Broker URL для Celery."""
        if self.celery_broker_url:
            return self.celery_broker_url.strip()

        login = self.rabbitmq_login.get_secret_value()
        password = self.rabbitmq_password.get_secret_value()
        return (
            f"pyamqp://{login}:{password}"
            f"@{self.rabbitmq_hostname}:{self.rabbitmq_port}//"
        )

    @property
    def backend_url(self) -> str:
        """Backend URL для Celery."""
        if self.celery_backend_url:
            return self.celery_backend_url.strip()

        login = self.rabbitmq_login.get_secret_value()
        password = self.rabbitmq_password.get_secret_value()
        return (
            f"rpc://{login}:{password}"
            f"@{self.rabbitmq_hostname}:{self.rabbitmq_port}//"
        )


@lru_cache(maxsize=1)
def get_clickhouse_celery_worker_settings() -> ClickHouseCeleryWorkerSettings:
    """Возвращает кэшированный инстанс worker settings."""
    return ClickHouseCeleryWorkerSettings()
