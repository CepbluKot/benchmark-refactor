from __future__ import annotations

import os
import signal
import threading

from benchmark_adapters.postgres import (
    PostgresProductRepository,
    create_product_engine,
)

from benchmark_m0_control.settings import ProductSettings


def run_once(repository: PostgresProductRepository) -> tuple[int, int]:
    reaped = repository.reap_expired_resources(limit=32)
    cancelled = repository.finalize_cancelled_studies(limit=32)
    return reaped, cancelled


def main() -> None:
    settings = ProductSettings.from_env()
    engine = create_product_engine(settings.database_url)
    repository = PostgresProductRepository(engine)
    if os.environ.get("M0_REAPER_ONCE", "false").lower() == "true":
        run_once(repository)
        engine.dispose()
        return

    stopping = threading.Event()

    def stop(signum: int, frame: object) -> None:
        del signum, frame
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping.is_set():
            run_once(repository)
            stopping.wait(2.0)
    finally:
        engine.dispose()
