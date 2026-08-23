from __future__ import annotations

import os
import signal
import threading
from datetime import timedelta

from hatchet_sdk import IdempotencyCollisionError

from benchmark_adapters.hatchet import HatchetGateway, build_hatchet_client
from benchmark_adapters.postgres import (
    PostgresProductRepository,
    create_product_engine,
)
from experiment_domain.m0 import OutboxCommandKind

from benchmark_m0_control.settings import HatchetSettings, ProductSettings


def run_once(repository: PostgresProductRepository, gateway: HatchetGateway) -> bool:
    command = repository.claim_outbox(lease=timedelta(seconds=30))
    if command is None:
        return False

    try:
        if command.kind == OutboxCommandKind.START_STUDY:
            try:
                run_id = gateway.start_study(command)
            except IdempotencyCollisionError as collision:
                run_id = collision.existing_run_external_id
        else:
            study = repository.get_study(command.study_id)
            run_id = study.hatchet_run_id
            if run_id is not None:
                gateway.cancel_run(run_id)

        repository.mark_outbox_dispatched(
            command.command_id, command.claim_token, run_id
        )
        return True
    except Exception as error:
        repository.release_outbox_claim(
            command.command_id,
            command.claim_token,
            type(error).__name__.upper()[:64],
        )
        return False


def main() -> None:
    product = ProductSettings.from_env()
    hatchet_config = HatchetSettings.from_env()
    engine = create_product_engine(product.database_url)
    repository = PostgresProductRepository(engine)
    hatchet = build_hatchet_client(
        token_file=hatchet_config.token_file,
        host_port=hatchet_config.host_port,
        server_url=hatchet_config.server_url,
        tls_strategy=hatchet_config.tls_strategy,
    )
    gateway = HatchetGateway(hatchet)

    if os.environ.get("M0_STARTER_ONCE", "false").lower() == "true":
        run_once(repository, gateway)
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
            processed = run_once(repository, gateway)
            stopping.wait(0.1 if processed else 1.0)
    finally:
        engine.dispose()
