import os

from benchmark_adapters.hatchet import build_hatchet_client
from core_workflows.m0_study import build_m0_study_task

from benchmark_m0_control.core_tasks import build_finalize_task
from benchmark_m0_control.settings import HatchetSettings


def main() -> None:
    core_release_id = os.environ.get("M0_CORE_RELEASE_ID", "m0-a")
    plugin_release_id = os.environ.get("M0_PLUGIN_RELEASE_ID", "m0-a")
    finalization_api_target = os.environ.get(
        "M0_FINALIZATION_API_TARGET", "finalization-api:50052"
    )
    config = HatchetSettings.from_env()
    hatchet = build_hatchet_client(
        token_file=config.token_file,
        host_port=config.host_port,
        server_url=config.server_url,
        tls_strategy=config.tls_strategy,
    )

    finalize_task = build_finalize_task(
        hatchet,
        core_release_id=core_release_id,
        finalization_api_target=finalization_api_target,
    )
    study_task = build_m0_study_task(
        hatchet,
        core_release_id=core_release_id,
        plugin_release_id=plugin_release_id,
    )
    worker = hatchet.worker(
        f"core-{core_release_id}-worker",
        slots=4,
        durable_slots=16,
        workflows=[study_task, finalize_task],
    )
    worker.start()
