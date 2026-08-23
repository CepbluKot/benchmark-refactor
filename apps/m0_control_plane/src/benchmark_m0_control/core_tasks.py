from datetime import timedelta

import grpc
from hatchet_sdk import Context, Hatchet
from hatchet_sdk.exceptions import NonRetryableException

from optimizer_sdk.m0 import (
    AttemptApiError,
    FinalizeStudyRefV1,
    FinalizedStudyV1,
    core_finalize_route,
    finalization_api_client,
)
from optimizer_sdk.m0.proto import attempt_api_pb2


def build_finalize_task(
    hatchet: Hatchet, *, core_release_id: str, finalization_api_target: str
):
    @hatchet.task(
        name=core_finalize_route(core_release_id),
        input_validator=FinalizeStudyRefV1,
        schedule_timeout=timedelta(minutes=5),
        execution_timeout=timedelta(seconds=30),
        retries=3,
        backoff_factor=2.0,
        backoff_max_seconds=10,
        concurrency=4,
    )
    def finalize(input: FinalizeStudyRefV1, ctx: Context) -> FinalizedStudyV1:
        del ctx
        try:
            with finalization_api_client(finalization_api_target) as client:
                response = client.finalize_study(
                    attempt_api_pb2.FinalizeStudyRequest(
                        schema_version="m0.finalize-study.v1",
                        study_id=str(input.study_id),
                        logical_job_id=str(input.logical_job_id),
                        result_sha256=input.result_sha256,
                    )
                )
        except AttemptApiError as error:
            if error.code in (
                grpc.StatusCode.INVALID_ARGUMENT,
                grpc.StatusCode.NOT_FOUND,
                grpc.StatusCode.FAILED_PRECONDITION,
            ):
                raise NonRetryableException(
                    f"finalize rejected with {error.code.name}"
                ) from error
            raise

        if (
            response.study_id != str(input.study_id)
            or response.result_sha256 != input.result_sha256
            or response.terminal_outcome != "RECOMMENDED"
        ):
            raise NonRetryableException("unexpected terminal outcome")
        return FinalizedStudyV1(
            study_id=response.study_id,
            outcome="RECOMMENDED",
            result_sha256=response.result_sha256,
        )

    return finalize
