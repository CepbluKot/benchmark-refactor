from __future__ import annotations

import os
from datetime import timedelta
from hashlib import sha256

import grpc
from hatchet_sdk import Context, Hatchet
from hatchet_sdk.exceptions import NonRetryableException

from benchmark_adapters.hatchet import build_hatchet_client
from optimizer_sdk.m0 import (
    AttemptApiError,
    ToyOperationRefV1,
    ToyResultRefV1,
    attempt_api_client,
    toy_measure_route,
)
from optimizer_sdk.m0.proto import attempt_api_pb2


def _fatal_if_nonretryable(error: AttemptApiError) -> None:
    if error.code in (
        grpc.StatusCode.INVALID_ARGUMENT,
        grpc.StatusCode.NOT_FOUND,
        grpc.StatusCode.FAILED_PRECONDITION,
    ):
        raise NonRetryableException(
            f"Attempt API rejected operation with {error.code.name}"
        ) from error


def _fault_once(point: str, ctx: Context) -> None:
    configured = os.environ.get("M0_TOY_FAULT_POINT", "")
    if configured == point and ctx.retry_count == 0:
        # Deliberate hard worker crash used only by HAT-04 component tests.
        os._exit(86)


def build_toy_measure_task(
    hatchet: Hatchet, *, plugin_release_id: str, attempt_api_target: str
):
    @hatchet.task(
        name=toy_measure_route(plugin_release_id),
        input_validator=ToyOperationRefV1,
        schedule_timeout=timedelta(minutes=5),
        execution_timeout=timedelta(minutes=2),
        retries=3,
        backoff_factor=2.0,
        backoff_max_seconds=10,
        concurrency=4,
    )
    def measure(input: ToyOperationRefV1, ctx: Context) -> ToyResultRefV1:
        if input.plugin_release_id != plugin_release_id:
            raise NonRetryableException("sealed plugin release route mismatch")
        if ctx.is_cancelled:
            raise NonRetryableException("task cancellation observed")

        begin_request_id = f"{ctx.task_run_id}:{ctx.attempt_number}"
        try:
            with attempt_api_client(attempt_api_target) as client:
                grant = client.begin_attempt(
                    attempt_api_pb2.BeginAttemptRequest(
                        schema_version="m0.begin-attempt.v1",
                        study_id=str(input.study_id),
                        logical_job_id=str(input.logical_job_id),
                        begin_request_id=begin_request_id,
                        physical_invocation_id=begin_request_id,
                        hatchet_workflow_run_id=ctx.workflow_run_id,
                        hatchet_task_run_id=ctx.task_run_id,
                        plugin_release_id=plugin_release_id,
                        operation_contract_sha256=input.operation_contract_sha256,
                        worker_id=ctx.worker_id,
                    )
                )

                if grant.status == attempt_api_pb2.ATTEMPT_START_STATUS_CANCELLED:
                    raise NonRetryableException("product cancellation observed")
                if grant.status == (
                    attempt_api_pb2.ATTEMPT_START_STATUS_ALREADY_ACCEPTED
                ):
                    if not grant.HasField("accepted_result_sha256"):
                        raise NonRetryableException(
                            "accepted result reference is missing"
                        )
                    return ToyResultRefV1(
                        study_id=input.study_id,
                        logical_job_id=input.logical_job_id,
                        plugin_release_id=plugin_release_id,
                        result_sha256=grant.accepted_result_sha256,
                        observation_count=1,
                    )
                if not grant.HasField("attempt_id") or not grant.HasField(
                    "fence_token"
                ):
                    raise NonRetryableException("attempt grant is incomplete")

                resource = client.register_resource(
                    attempt_api_pb2.RegisterResourceRequest(
                        schema_version="m0.register-resource.v1",
                        study_id=str(input.study_id),
                        logical_job_id=str(input.logical_job_id),
                        attempt_id=grant.attempt_id,
                        fence_token=grant.fence_token,
                        resource_key="measurement",
                        resource_kind="toy.scratch",
                    )
                )
                _fault_once("before_side_effect", ctx)

                result_sha256 = sha256(
                    (
                        f"{input.input_sha256}:{plugin_release_id}:"
                        f"{input.operation_kind}:{input.continuation_no}"
                    ).encode("utf-8")
                ).hexdigest()
                _fault_once("after_side_effect", ctx)

                completion = client.complete_attempt(
                    attempt_api_pb2.CompleteAttemptRequest(
                        schema_version="m0.complete-attempt.v1",
                        study_id=str(input.study_id),
                        logical_job_id=str(input.logical_job_id),
                        attempt_id=grant.attempt_id,
                        fence_token=grant.fence_token,
                        result_sha256=result_sha256,
                        observation_count=1,
                    )
                )
                if completion.status not in (
                    attempt_api_pb2.COMPLETION_STATUS_ACCEPTED,
                    attempt_api_pb2.COMPLETION_STATUS_ALREADY_ACCEPTED,
                ):
                    raise NonRetryableException("attempt completion was fenced")
                _fault_once("after_commit", ctx)

                client.release_resource(
                    attempt_api_pb2.ReleaseResourceRequest(
                        schema_version="m0.release-resource.v1",
                        resource_id=resource.resource_id,
                        attempt_id=grant.attempt_id,
                        fence_token=grant.fence_token,
                    )
                )
        except AttemptApiError as error:
            _fatal_if_nonretryable(error)
            raise

        return ToyResultRefV1(
            study_id=input.study_id,
            logical_job_id=input.logical_job_id,
            plugin_release_id=plugin_release_id,
            result_sha256=result_sha256,
            observation_count=1,
        )

    return measure


def main() -> None:
    plugin_release_id = os.environ.get("M0_PLUGIN_RELEASE_ID", "m0-a")
    attempt_api_target = os.environ.get("M0_ATTEMPT_API_TARGET", "attempt-api:50051")
    token_file = os.environ.get(
        "HATCHET_CLIENT_TOKEN_FILE", "/run/secrets/hatchet_worker_token"
    )
    hatchet = build_hatchet_client(
        token_file=token_file,
        host_port=os.environ.get("HATCHET_CLIENT_HOST_PORT", "hatchet-engine:7070"),
        server_url=os.environ.get(
            "HATCHET_CLIENT_SERVER_URL", "http://hatchet-api:8080"
        ),
        tls_strategy=os.environ.get("HATCHET_CLIENT_TLS_STRATEGY", "none"),
    )
    task = build_toy_measure_task(
        hatchet,
        plugin_release_id=plugin_release_id,
        attempt_api_target=attempt_api_target,
    )
    worker = hatchet.worker(
        f"toy-{plugin_release_id}-worker",
        slots=4,
        durable_slots=1,
        workflows=[task],
    )
    worker.start()
