from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import grpc

from optimizer_sdk.m0.proto import attempt_api_pb2, attempt_api_pb2_grpc


class AttemptApiError(RuntimeError):
    def __init__(self, code: grpc.StatusCode) -> None:
        self.code = code
        super().__init__(f"Attempt API call failed with {code.name}")


def _protocol_error() -> AttemptApiError:
    return AttemptApiError(grpc.StatusCode.FAILED_PRECONDITION)


def _require_schema(response, expected: str) -> None:  # type: ignore[no-untyped-def]
    if response.schema_version != expected:
        raise _protocol_error()


class AttemptApiClient:
    def __init__(self, target: str, *, timeout_seconds: float = 10.0) -> None:
        self._channel = grpc.insecure_channel(
            target,
            options=(
                ("grpc.max_send_message_length", 64 * 1024),
                ("grpc.max_receive_message_length", 64 * 1024),
            ),
        )
        self._stub = attempt_api_pb2_grpc.AttemptResourceServiceStub(self._channel)
        self._timeout_seconds = timeout_seconds

    def close(self) -> None:
        self._channel.close()

    def begin_attempt(
        self, request: attempt_api_pb2.BeginAttemptRequest
    ) -> attempt_api_pb2.BeginAttemptResponse:
        response = self._call(self._stub.BeginAttempt, request)
        _require_schema(response, "m0.begin-attempt-response.v1")
        if response.status not in (
            attempt_api_pb2.ATTEMPT_START_STATUS_STARTED,
            attempt_api_pb2.ATTEMPT_START_STATUS_EXISTING,
            attempt_api_pb2.ATTEMPT_START_STATUS_ALREADY_ACCEPTED,
            attempt_api_pb2.ATTEMPT_START_STATUS_CANCELLED,
        ):
            raise _protocol_error()
        if response.status in (
            attempt_api_pb2.ATTEMPT_START_STATUS_STARTED,
            attempt_api_pb2.ATTEMPT_START_STATUS_EXISTING,
        ) and not (
            response.HasField("attempt_id")
            and response.HasField("fence_token")
            and response.HasField("lease_expires_at")
        ):
            raise _protocol_error()
        if response.status == (
            attempt_api_pb2.ATTEMPT_START_STATUS_ALREADY_ACCEPTED
        ) and not response.HasField("accepted_result_sha256"):
            raise _protocol_error()
        return response

    def register_resource(
        self, request: attempt_api_pb2.RegisterResourceRequest
    ) -> attempt_api_pb2.RegisterResourceResponse:
        response = self._call(self._stub.RegisterResource, request)
        _require_schema(response, "m0.register-resource-response.v1")
        if (
            not response.resource_id
            or not response.locator_ref
            or len(response.locator_sha256) != 64
            or not response.HasField("expires_at")
        ):
            raise _protocol_error()
        return response

    def complete_attempt(
        self, request: attempt_api_pb2.CompleteAttemptRequest
    ) -> attempt_api_pb2.CompleteAttemptResponse:
        response = self._call(self._stub.CompleteAttempt, request)
        _require_schema(response, "m0.complete-attempt-response.v1")
        if response.status not in (
            attempt_api_pb2.COMPLETION_STATUS_ACCEPTED,
            attempt_api_pb2.COMPLETION_STATUS_ALREADY_ACCEPTED,
            attempt_api_pb2.COMPLETION_STATUS_REJECTED_STALE,
            attempt_api_pb2.COMPLETION_STATUS_REJECTED_CANCELLED,
        ):
            raise _protocol_error()
        return response

    def release_resource(
        self, request: attempt_api_pb2.ReleaseResourceRequest
    ) -> attempt_api_pb2.ReleaseResourceResponse:
        response = self._call(self._stub.ReleaseResource, request)
        _require_schema(response, "m0.release-resource-response.v1")
        return response

    def _call(self, method, request):  # type: ignore[no-untyped-def]
        try:
            return method(request, timeout=self._timeout_seconds)
        except grpc.RpcError as error:
            raise AttemptApiError(error.code()) from error


class FinalizationApiClient:
    def __init__(self, target: str, *, timeout_seconds: float = 10.0) -> None:
        self._channel = grpc.insecure_channel(
            target,
            options=(
                ("grpc.max_send_message_length", 64 * 1024),
                ("grpc.max_receive_message_length", 64 * 1024),
            ),
        )
        self._stub = attempt_api_pb2_grpc.StudyFinalizationServiceStub(self._channel)
        self._timeout_seconds = timeout_seconds

    def close(self) -> None:
        self._channel.close()

    def finalize_study(
        self, request: attempt_api_pb2.FinalizeStudyRequest
    ) -> attempt_api_pb2.FinalizeStudyResponse:
        try:
            response = self._stub.FinalizeStudy(request, timeout=self._timeout_seconds)
            _require_schema(response, "m0.finalize-study-response.v1")
            return response
        except grpc.RpcError as error:
            raise AttemptApiError(error.code()) from error


@contextmanager
def attempt_api_client(
    target: str, *, timeout_seconds: float = 10.0
) -> Iterator[AttemptApiClient]:
    client = AttemptApiClient(target, timeout_seconds=timeout_seconds)
    try:
        yield client
    finally:
        client.close()


@contextmanager
def finalization_api_client(
    target: str, *, timeout_seconds: float = 10.0
) -> Iterator[FinalizationApiClient]:
    client = FinalizationApiClient(target, timeout_seconds=timeout_seconds)
    try:
        yield client
    finally:
        client.close()
