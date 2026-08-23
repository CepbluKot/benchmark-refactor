from __future__ import annotations

import os
import re
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import UUID

import grpc
from google.protobuf.timestamp_pb2 import Timestamp

from benchmark_adapters.postgres import (
    PostgresProductRepository,
    create_product_engine,
)
from experiment_domain.m0 import (
    AcceptedResultConflict,
    AttemptStartStatus as DomainAttemptStartStatus,
    CompletionStatus as DomainCompletionStatus,
    EntityNotFound,
    InvalidTransition,
)
from optimizer_sdk.m0.proto import attempt_api_pb2, attempt_api_pb2_grpc
from runtime_services.m0 import (
    BeginAttempt,
    CompleteAttempt,
    ControlService,
    RegisterResource,
)

from benchmark_m0_control.settings import ProductSettings


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_ATTEMPT_STATUS = {
    DomainAttemptStartStatus.STARTED: attempt_api_pb2.ATTEMPT_START_STATUS_STARTED,
    DomainAttemptStartStatus.EXISTING: attempt_api_pb2.ATTEMPT_START_STATUS_EXISTING,
    DomainAttemptStartStatus.ALREADY_ACCEPTED: (
        attempt_api_pb2.ATTEMPT_START_STATUS_ALREADY_ACCEPTED
    ),
    DomainAttemptStartStatus.CANCELLED: attempt_api_pb2.ATTEMPT_START_STATUS_CANCELLED,
}

_COMPLETION_STATUS = {
    DomainCompletionStatus.ACCEPTED: attempt_api_pb2.COMPLETION_STATUS_ACCEPTED,
    DomainCompletionStatus.ALREADY_ACCEPTED: (
        attempt_api_pb2.COMPLETION_STATUS_ALREADY_ACCEPTED
    ),
    DomainCompletionStatus.REJECTED_STALE: (
        attempt_api_pb2.COMPLETION_STATUS_REJECTED_STALE
    ),
    DomainCompletionStatus.REJECTED_CANCELLED: (
        attempt_api_pb2.COMPLETION_STATUS_REJECTED_CANCELLED
    ),
}


def _timestamp(value: datetime) -> Timestamp:
    result = Timestamp()
    result.FromDatetime(value)
    return result


def _require_version(actual: str, expected: str) -> None:
    if actual != expected:
        raise ValueError("unsupported schema version")


def _require_uuid(value: str) -> None:
    UUID(value)


def _require_text(value: str, *, maximum: int) -> None:
    if not value or len(value) > maximum:
        raise ValueError("invalid bounded text field")


def _require_sha256(value: str) -> None:
    if not _SHA256.fullmatch(value):
        raise ValueError("invalid sha256")


def _require_identifier(value: str, *, maximum: int) -> None:
    _require_text(value, maximum=maximum)
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError("invalid identifier")


def _abort_domain(context: grpc.ServicerContext, error: Exception) -> None:
    if isinstance(error, EntityNotFound):
        context.abort(grpc.StatusCode.NOT_FOUND, "entity not found")
    if isinstance(error, (InvalidTransition, AcceptedResultConflict)):
        context.abort(grpc.StatusCode.FAILED_PRECONDITION, "request rejected")
    context.abort(grpc.StatusCode.INTERNAL, "internal error")


class AttemptResourceService(attempt_api_pb2_grpc.AttemptResourceServiceServicer):
    def __init__(self, control: ControlService) -> None:
        self._control = control

    def BeginAttempt(self, request, context):  # type: ignore[no-untyped-def]
        try:
            _require_version(request.schema_version, "m0.begin-attempt.v1")
            _require_uuid(request.study_id)
            _require_uuid(request.logical_job_id)
            for value, maximum in (
                (request.begin_request_id, 256),
                (request.physical_invocation_id, 256),
                (request.hatchet_workflow_run_id, 128),
                (request.hatchet_task_run_id, 128),
                (request.plugin_release_id, 64),
                (request.worker_id, 128),
            ):
                _require_text(value, maximum=maximum)
            _require_sha256(request.operation_contract_sha256)
            grant = self._control.begin_attempt(
                BeginAttempt(
                    study_id=request.study_id,
                    logical_job_id=request.logical_job_id,
                    begin_request_id=request.begin_request_id,
                    physical_invocation_id=request.physical_invocation_id,
                    hatchet_workflow_run_id=request.hatchet_workflow_run_id,
                    hatchet_task_run_id=request.hatchet_task_run_id,
                    plugin_release_id=request.plugin_release_id,
                    operation_contract_sha256=request.operation_contract_sha256,
                    worker_id=request.worker_id,
                )
            )
            response = attempt_api_pb2.BeginAttemptResponse(
                schema_version="m0.begin-attempt-response.v1",
                status=_ATTEMPT_STATUS[grant.status],
            )
            if grant.attempt_id is not None:
                response.attempt_id = grant.attempt_id
            if grant.fence_token is not None:
                response.fence_token = grant.fence_token
            if grant.lease_expires_at is not None:
                response.lease_expires_at.CopyFrom(_timestamp(grant.lease_expires_at))
            if grant.accepted_result_sha256 is not None:
                response.accepted_result_sha256 = grant.accepted_result_sha256
            return response
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid request")
        except Exception as error:
            _abort_domain(context, error)

    def RegisterResource(self, request, context):  # type: ignore[no-untyped-def]
        try:
            _require_version(request.schema_version, "m0.register-resource.v1")
            _require_uuid(request.study_id)
            _require_uuid(request.logical_job_id)
            _require_uuid(request.attempt_id)
            _require_identifier(request.resource_key, maximum=128)
            _require_identifier(request.resource_kind, maximum=64)
            if request.fence_token < 1:
                raise ValueError("invalid fence")
            grant = self._control.register_resource(
                RegisterResource(
                    study_id=request.study_id,
                    logical_job_id=request.logical_job_id,
                    attempt_id=request.attempt_id,
                    fence_token=request.fence_token,
                    resource_key=request.resource_key,
                    resource_kind=request.resource_kind,
                )
            )
            return attempt_api_pb2.RegisterResourceResponse(
                schema_version="m0.register-resource-response.v1",
                resource_id=grant.resource_id,
                locator_ref=grant.locator_ref,
                locator_sha256=grant.locator_sha256,
                expires_at=_timestamp(grant.expires_at),
            )
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid request")
        except Exception as error:
            _abort_domain(context, error)

    def CompleteAttempt(self, request, context):  # type: ignore[no-untyped-def]
        try:
            _require_version(request.schema_version, "m0.complete-attempt.v1")
            _require_uuid(request.study_id)
            _require_uuid(request.logical_job_id)
            _require_uuid(request.attempt_id)
            _require_sha256(request.result_sha256)
            if (
                request.fence_token < 1
                or request.observation_count < 1
                or request.observation_count > 1_000_000
            ):
                raise ValueError("invalid numeric field")
            completion = self._control.complete_attempt(
                CompleteAttempt(
                    study_id=request.study_id,
                    logical_job_id=request.logical_job_id,
                    attempt_id=request.attempt_id,
                    fence_token=request.fence_token,
                    result_sha256=request.result_sha256,
                    observation_count=request.observation_count,
                )
            )
            return attempt_api_pb2.CompleteAttemptResponse(
                schema_version="m0.complete-attempt-response.v1",
                status=_COMPLETION_STATUS[completion],
            )
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid request")
        except Exception as error:
            _abort_domain(context, error)

    def ReleaseResource(self, request, context):  # type: ignore[no-untyped-def]
        try:
            _require_version(request.schema_version, "m0.release-resource.v1")
            _require_uuid(request.resource_id)
            _require_uuid(request.attempt_id)
            if request.fence_token < 1:
                raise ValueError("invalid fence")
            changed = self._control.release_resource(
                request.resource_id, request.attempt_id, request.fence_token
            )
            return attempt_api_pb2.ReleaseResourceResponse(
                schema_version="m0.release-resource-response.v1",
                changed=changed,
            )
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid request")
        except Exception as error:
            _abort_domain(context, error)


class StudyFinalizationService(attempt_api_pb2_grpc.StudyFinalizationServiceServicer):
    def __init__(self, control: ControlService) -> None:
        self._control = control

    def FinalizeStudy(self, request, context):  # type: ignore[no-untyped-def]
        try:
            _require_version(request.schema_version, "m0.finalize-study.v1")
            _require_uuid(request.study_id)
            _require_uuid(request.logical_job_id)
            _require_sha256(request.result_sha256)
            study = self._control.finalize(
                request.study_id, request.logical_job_id, request.result_sha256
            )
            return attempt_api_pb2.FinalizeStudyResponse(
                schema_version="m0.finalize-study-response.v1",
                study_id=study.study_id,
                terminal_outcome=study.terminal_outcome.value,
                result_sha256=request.result_sha256,
            )
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid request")
        except Exception as error:
            _abort_domain(context, error)


def _serve(*, service_kind: str, bind_address: str) -> None:
    settings = ProductSettings.from_env()
    engine = create_product_engine(settings.database_url)
    repository = PostgresProductRepository(engine)
    control = ControlService(repository, active_study_limit=settings.active_study_limit)

    server = grpc.server(
        ThreadPoolExecutor(max_workers=4),
        maximum_concurrent_rpcs=8,
        options=(
            ("grpc.max_send_message_length", 64 * 1024),
            ("grpc.max_receive_message_length", 64 * 1024),
        ),
    )
    if service_kind == "attempt":
        attempt_api_pb2_grpc.add_AttemptResourceServiceServicer_to_server(
            AttemptResourceService(control), server
        )
    elif service_kind == "finalization":
        attempt_api_pb2_grpc.add_StudyFinalizationServiceServicer_to_server(
            StudyFinalizationService(control), server
        )
    else:
        raise ValueError("unknown gRPC service kind")
    if server.add_insecure_port(bind_address) == 0:
        raise RuntimeError(f"{service_kind} API could not bind")

    stopping = threading.Event()

    def stop(signum: int, frame: object) -> None:
        del signum, frame
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    server.start()
    try:
        stopping.wait()
    finally:
        server.stop(grace=10).wait()
        engine.dispose()


def main() -> None:
    _serve(
        service_kind="attempt",
        bind_address=os.environ.get("M0_ATTEMPT_API_BIND", "[::]:50051"),
    )


def main_finalization() -> None:
    _serve(
        service_kind="finalization",
        bind_address=os.environ.get("M0_FINALIZATION_API_BIND", "[::]:50052"),
    )
