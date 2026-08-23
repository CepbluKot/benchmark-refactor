from datetime import timedelta

from hatchet_sdk import (
    DurableContext,
    Hatchet,
    StatusBasedIdempotencyConfig,
)
from hatchet_sdk.exceptions import NonRetryableException
from hatchet_sdk.runnables.task import Task

from optimizer_sdk.m0 import (
    FinalizeStudyRefV1,
    FinalizedStudyV1,
    StudyRunRefV1,
    ToyOperationRefV1,
    ToyResultRefV1,
    core_finalize_route,
    core_study_route,
    toy_measure_route,
)


def build_m0_study_task(
    hatchet: Hatchet, *, core_release_id: str, plugin_release_id: str
) -> Task[StudyRunRefV1, FinalizedStudyV1]:
    """Build one immutable A/B route without importing plugin implementation."""

    plugin_stub = hatchet.stubs.task(
        name=toy_measure_route(plugin_release_id),
        input_validator=ToyOperationRefV1,
        output_validator=ToyResultRefV1,
    )
    finalize_stub = hatchet.stubs.task(
        name=core_finalize_route(core_release_id),
        input_validator=FinalizeStudyRefV1,
        output_validator=FinalizedStudyV1,
    )

    @hatchet.durable_task(
        name=core_study_route(core_release_id),
        input_validator=StudyRunRefV1,
        schedule_timeout=timedelta(minutes=5),
        execution_timeout=timedelta(minutes=30),
        retries=1,
        concurrency=100,
        idempotency=StatusBasedIdempotencyConfig(
            key_expression="input.command_id",
            fallback_ttl=timedelta(days=7),
        ),
    )
    async def orchestrate(
        input: StudyRunRefV1, ctx: DurableContext
    ) -> FinalizedStudyV1:
        if (
            input.core_release_id != core_release_id
            or input.plugin_release_id != plugin_release_id
        ):
            raise NonRetryableException("sealed release route mismatch")

        result = await plugin_stub.aio_run(
            ToyOperationRefV1(
                study_id=input.study_id,
                logical_job_id=input.logical_job_id,
                core_release_id=input.core_release_id,
                plugin_release_id=input.plugin_release_id,
                operation_contract_sha256=input.operation_contract_sha256,
                input_ref=input.input_ref,
                input_sha256=input.input_sha256,
                continuation_no=input.continuation_no,
                deadline_profile_ref=input.deadline_profile_ref,
            ),
            child_key=f"{input.study_id}:toy:{input.continuation_no}",
        )
        return await finalize_stub.aio_run(
            FinalizeStudyRefV1(
                study_id=input.study_id,
                logical_job_id=input.logical_job_id,
                result_sha256=result.result_sha256,
            ),
            child_key=f"{input.study_id}:finalize:{input.continuation_no}",
        )

    return orchestrate
