"""
Тестовый launcher benchmark runtime.

Режим конфигурации:
  - читает base64-конфиги из `.env` через переменные `BENCH_*_CONFIG_B64`
    (BENCH_CELERY_CONFIG_B64, BENCH_CONNECTIONS_CONFIG_B64,
     BENCH_RULE_BANKS_CONFIG_B64, BENCH_BENCHMARKS_CONFIG_B64).

Запуск:
  1) подними Celery worker с `-E` (`--events`), если используешь progress monitor:
     ./venv/bin/celery -A src.benchmark_runtime.implementations.clickhouse_celery.tasks worker -E --loglevel=INFO
  python3 main-test.py
"""

from __future__ import annotations

import logging

from main import run_from_settings
from settings import get_settings

logger = logging.getLogger(__name__)


def _configure_logging(level_name: str) -> None:
    """Настраивает формат и уровень логирования."""
    try:
        level = int(level_name)
    except ValueError:
        level = getattr(logging, level_name.upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def main() -> None:
    """Запускает benchmark с конфигами из base64-переменных окружения."""
    app_settings = get_settings()
    _configure_logging(app_settings.log_level)
    logger.info("Старт test launcher (env base64 mode)")
    run_id = run_from_settings()
    print(f"Benchmark test run completed. benchmark_run_id={run_id}")


if __name__ == "__main__":
    main()
