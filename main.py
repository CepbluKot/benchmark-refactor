"""
Точка входа запуска benchmark-алгоритма по JSON-конфигам из settings.

Этот launcher использует production-пайплайн:
  - metadata через реальный FetcherMetadataProvider;
  - execution через CeleryClickHouseExecutionAdapter;
  - top-N чтение через ClickHouseBenchmarkResultStore.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from src.benchmark_engine import BenchmarkEngine, BenchmarkPlanner, BenchmarkRunner
from src.benchmark_runtime import FetcherMetadataProvider
from src.benchmark_runtime.implementations.clickhouse_celery import (
    CeleryClickHouseExecutionAdapter,
    ClickHouseBenchmarkResultStore,
)
from src.fetcher import make_fetcher
from src.loader import parse_config_parts
from src.models import BenchmarkRootConfig, ConnectionConfig

from settings import get_settings

logger = logging.getLogger(__name__)


def _configure_logging(level_name: str) -> None:
    """Настраивает формат и уровень логирования приложения."""
    try:
        level = int(level_name)
    except ValueError:
        level = getattr(logging, level_name.upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def _apply_default_test_database(
    config: BenchmarkRootConfig,
    default_test_database: Optional[str],
) -> int:
    """
    Применяет test_database из env как fallback для benchmark'ов без явного test_database.

    Возвращает количество benchmark-конфигов, которые были обновлены.
    """
    if not default_test_database:
        return 0

    applied = 0
    for benchmark in config.benchmarks:
        if benchmark.test_database is None:
            benchmark.test_database = default_test_database
            applied += 1
    return applied


def _resolve_result_connection(
    config: BenchmarkRootConfig,
    preferred_connection_id: Optional[str],
) -> ConnectionConfig:
    """Выбирает connection для result-store и записи worker-результатов."""
    if not config.connections:
        raise ValueError("В конфиге отсутствуют connections")

    if preferred_connection_id is None:
        return config.connections[0]

    normalized = preferred_connection_id.strip()
    if not normalized:
        return config.connections[0]

    for connection in config.connections:
        if connection.id == normalized:
            return connection

    available_ids = ", ".join(sorted(conn.id for conn in config.connections))
    raise ValueError(
        "BENCH_RESULT_CONNECTION_ID указывает на несуществующий connection_id: "
        f"{normalized!r}. Доступные connection_id: {available_ids}"
    )


def _build_metadata_providers(
    connections: List[ConnectionConfig],
) -> Tuple[Dict[str, FetcherMetadataProvider], Dict[str, object]]:
    """Создаёт и подключает fetcher-провайдеры по всем connection_id."""
    providers: Dict[str, FetcherMetadataProvider] = {}
    fetchers: Dict[str, object] = {}

    try:
        for connection in connections:
            fetcher = make_fetcher(connection)
            fetcher.connect()
            providers[connection.id] = FetcherMetadataProvider(fetcher)
            fetchers[connection.id] = fetcher
            logger.info(
                "Подключён metadata fetcher для connection_id=%s (%s:%d)",
                connection.id,
                connection.host,
                connection.port,
            )
        return providers, fetchers
    except Exception:
        _disconnect_fetchers(fetchers)
        raise


def _disconnect_fetchers(fetchers: Dict[str, object]) -> None:
    """Закрывает все подключенные fetcher'ы (best-effort)."""
    for connection_id, fetcher in fetchers.items():
        disconnect_hook = getattr(fetcher, "disconnect", None)
        if not callable(disconnect_hook):
            continue
        try:
            disconnect_hook()
            logger.debug("Fetcher отключён: connection_id=%s", connection_id)
        except Exception:
            logger.exception("Ошибка disconnect fetcher для connection_id=%s", connection_id)


def _close_result_store_if_supported(result_store: object) -> None:
    """Закрывает result store, если реализация поддерживает close()."""
    close_hook = getattr(result_store, "close", None)
    if not callable(close_hook):
        return
    try:
        close_hook()
    except Exception:
        logger.exception("Ошибка закрытия result store")


def run_from_settings() -> int:
    """Запускает BenchmarkRunner по настройкам и возвращает run id."""
    app_settings = get_settings()
    logger.info("Чтение и декодирование конфигов из переменных окружения")
    config = parse_config_parts(
        celery_raw=app_settings.decode_celery_config(),
        connections_raw=app_settings.decode_connections_config(),
        rule_banks_raw=app_settings.decode_rule_banks_config(),
        benchmarks_raw=app_settings.decode_benchmarks_config(),
    )
    overridden = _apply_default_test_database(config, app_settings.test_database)
    if overridden > 0:
        logger.info(
            "Применён BENCH_TEST_DATABASE=%s для %d benchmark-конфигов без test_database",
            app_settings.test_database,
            overridden,
        )
    logger.info(
        "Конфиг загружен: connections=%d, benchmarks=%d",
        len(config.connections),
        len(config.benchmarks),
    )

    result_connection = _resolve_result_connection(
        config=config,
        preferred_connection_id=app_settings.result_connection_id,
    )
    logger.info(
        "Result store connection: connection_id=%s, target=%s.%s",
        result_connection.id,
        app_settings.result_database,
        app_settings.result_table,
    )
    result_store = ClickHouseBenchmarkResultStore(
        connection=result_connection,
        database=app_settings.result_database,
        table=app_settings.result_table,
        create_table_if_missing=True,
    )

    connections_by_id = {connection.id: connection for connection in config.connections}
    result_connections_by_id = {
        connection_id: result_connection for connection_id in connections_by_id
    }

    execution_adapter = CeleryClickHouseExecutionAdapter(
        connections_by_id=connections_by_id,
        result_connections_by_id=result_connections_by_id,
        result_database=app_settings.result_database,
        result_table=app_settings.result_table,
    )

    fetchers: Dict[str, object] = {}
    try:
        providers, fetchers = _build_metadata_providers(config.connections)
        planner = BenchmarkPlanner(
            config=config,
            providers_by_connection_id=providers,
        )
        engine = BenchmarkEngine(planner=planner)
        runner = BenchmarkRunner(
            engine=engine,
            execution_adapter=execution_adapter,
            result_store=result_store,
        )

        benchmark_ids: Optional[List[str]] = app_settings.benchmark_ids or None
        run_id = runner.run(
            benchmark_ids=benchmark_ids,
            benchmark_run_id=app_settings.benchmark_run_id,
        )
        logger.info("Benchmark run завершён: benchmark_run_id=%d", run_id)
        return run_id
    finally:
        _disconnect_fetchers(fetchers)
        _close_result_store_if_supported(result_store)


def main() -> None:
    """CLI entrypoint."""
    app_settings = get_settings()
    _configure_logging(app_settings.log_level)
    logger.info("Старт benchmark launcher (log_level=%s)", app_settings.log_level)
    run_id = run_from_settings()
    print(f"Benchmark run completed. benchmark_run_id={run_id}")


if __name__ == "__main__":
    main()

