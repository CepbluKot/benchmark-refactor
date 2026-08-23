import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AttemptStartStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ATTEMPT_START_STATUS_UNSPECIFIED: _ClassVar[AttemptStartStatus]
    ATTEMPT_START_STATUS_STARTED: _ClassVar[AttemptStartStatus]
    ATTEMPT_START_STATUS_EXISTING: _ClassVar[AttemptStartStatus]
    ATTEMPT_START_STATUS_ALREADY_ACCEPTED: _ClassVar[AttemptStartStatus]
    ATTEMPT_START_STATUS_CANCELLED: _ClassVar[AttemptStartStatus]

class CompletionStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    COMPLETION_STATUS_UNSPECIFIED: _ClassVar[CompletionStatus]
    COMPLETION_STATUS_ACCEPTED: _ClassVar[CompletionStatus]
    COMPLETION_STATUS_ALREADY_ACCEPTED: _ClassVar[CompletionStatus]
    COMPLETION_STATUS_REJECTED_STALE: _ClassVar[CompletionStatus]
    COMPLETION_STATUS_REJECTED_CANCELLED: _ClassVar[CompletionStatus]

ATTEMPT_START_STATUS_UNSPECIFIED: AttemptStartStatus
ATTEMPT_START_STATUS_STARTED: AttemptStartStatus
ATTEMPT_START_STATUS_EXISTING: AttemptStartStatus
ATTEMPT_START_STATUS_ALREADY_ACCEPTED: AttemptStartStatus
ATTEMPT_START_STATUS_CANCELLED: AttemptStartStatus
COMPLETION_STATUS_UNSPECIFIED: CompletionStatus
COMPLETION_STATUS_ACCEPTED: CompletionStatus
COMPLETION_STATUS_ALREADY_ACCEPTED: CompletionStatus
COMPLETION_STATUS_REJECTED_STALE: CompletionStatus
COMPLETION_STATUS_REJECTED_CANCELLED: CompletionStatus

class BeginAttemptRequest(_message.Message):
    __slots__ = (
        "schema_version",
        "study_id",
        "logical_job_id",
        "begin_request_id",
        "physical_invocation_id",
        "hatchet_workflow_run_id",
        "hatchet_task_run_id",
        "plugin_release_id",
        "worker_id",
        "operation_contract_sha256",
    )
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    STUDY_ID_FIELD_NUMBER: _ClassVar[int]
    LOGICAL_JOB_ID_FIELD_NUMBER: _ClassVar[int]
    BEGIN_REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    PHYSICAL_INVOCATION_ID_FIELD_NUMBER: _ClassVar[int]
    HATCHET_WORKFLOW_RUN_ID_FIELD_NUMBER: _ClassVar[int]
    HATCHET_TASK_RUN_ID_FIELD_NUMBER: _ClassVar[int]
    PLUGIN_RELEASE_ID_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    OPERATION_CONTRACT_SHA256_FIELD_NUMBER: _ClassVar[int]
    schema_version: str
    study_id: str
    logical_job_id: str
    begin_request_id: str
    physical_invocation_id: str
    hatchet_workflow_run_id: str
    hatchet_task_run_id: str
    plugin_release_id: str
    worker_id: str
    operation_contract_sha256: str
    def __init__(
        self,
        schema_version: _Optional[str] = ...,
        study_id: _Optional[str] = ...,
        logical_job_id: _Optional[str] = ...,
        begin_request_id: _Optional[str] = ...,
        physical_invocation_id: _Optional[str] = ...,
        hatchet_workflow_run_id: _Optional[str] = ...,
        hatchet_task_run_id: _Optional[str] = ...,
        plugin_release_id: _Optional[str] = ...,
        worker_id: _Optional[str] = ...,
        operation_contract_sha256: _Optional[str] = ...,
    ) -> None: ...

class BeginAttemptResponse(_message.Message):
    __slots__ = (
        "schema_version",
        "status",
        "attempt_id",
        "fence_token",
        "lease_expires_at",
        "accepted_result_sha256",
    )
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    ATTEMPT_ID_FIELD_NUMBER: _ClassVar[int]
    FENCE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    LEASE_EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    ACCEPTED_RESULT_SHA256_FIELD_NUMBER: _ClassVar[int]
    schema_version: str
    status: AttemptStartStatus
    attempt_id: str
    fence_token: int
    lease_expires_at: _timestamp_pb2.Timestamp
    accepted_result_sha256: str
    def __init__(
        self,
        schema_version: _Optional[str] = ...,
        status: _Optional[_Union[AttemptStartStatus, str]] = ...,
        attempt_id: _Optional[str] = ...,
        fence_token: _Optional[int] = ...,
        lease_expires_at: _Optional[
            _Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]
        ] = ...,
        accepted_result_sha256: _Optional[str] = ...,
    ) -> None: ...

class RegisterResourceRequest(_message.Message):
    __slots__ = (
        "schema_version",
        "study_id",
        "logical_job_id",
        "attempt_id",
        "fence_token",
        "resource_key",
        "resource_kind",
    )
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    STUDY_ID_FIELD_NUMBER: _ClassVar[int]
    LOGICAL_JOB_ID_FIELD_NUMBER: _ClassVar[int]
    ATTEMPT_ID_FIELD_NUMBER: _ClassVar[int]
    FENCE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_KEY_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_KIND_FIELD_NUMBER: _ClassVar[int]
    schema_version: str
    study_id: str
    logical_job_id: str
    attempt_id: str
    fence_token: int
    resource_key: str
    resource_kind: str
    def __init__(
        self,
        schema_version: _Optional[str] = ...,
        study_id: _Optional[str] = ...,
        logical_job_id: _Optional[str] = ...,
        attempt_id: _Optional[str] = ...,
        fence_token: _Optional[int] = ...,
        resource_key: _Optional[str] = ...,
        resource_kind: _Optional[str] = ...,
    ) -> None: ...

class RegisterResourceResponse(_message.Message):
    __slots__ = (
        "schema_version",
        "resource_id",
        "locator_ref",
        "locator_sha256",
        "expires_at",
    )
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_REF_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_SHA256_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    schema_version: str
    resource_id: str
    locator_ref: str
    locator_sha256: str
    expires_at: _timestamp_pb2.Timestamp
    def __init__(
        self,
        schema_version: _Optional[str] = ...,
        resource_id: _Optional[str] = ...,
        locator_ref: _Optional[str] = ...,
        locator_sha256: _Optional[str] = ...,
        expires_at: _Optional[
            _Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]
        ] = ...,
    ) -> None: ...

class CompleteAttemptRequest(_message.Message):
    __slots__ = (
        "schema_version",
        "study_id",
        "logical_job_id",
        "attempt_id",
        "fence_token",
        "result_sha256",
        "observation_count",
    )
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    STUDY_ID_FIELD_NUMBER: _ClassVar[int]
    LOGICAL_JOB_ID_FIELD_NUMBER: _ClassVar[int]
    ATTEMPT_ID_FIELD_NUMBER: _ClassVar[int]
    FENCE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    RESULT_SHA256_FIELD_NUMBER: _ClassVar[int]
    OBSERVATION_COUNT_FIELD_NUMBER: _ClassVar[int]
    schema_version: str
    study_id: str
    logical_job_id: str
    attempt_id: str
    fence_token: int
    result_sha256: str
    observation_count: int
    def __init__(
        self,
        schema_version: _Optional[str] = ...,
        study_id: _Optional[str] = ...,
        logical_job_id: _Optional[str] = ...,
        attempt_id: _Optional[str] = ...,
        fence_token: _Optional[int] = ...,
        result_sha256: _Optional[str] = ...,
        observation_count: _Optional[int] = ...,
    ) -> None: ...

class CompleteAttemptResponse(_message.Message):
    __slots__ = ("schema_version", "status")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    schema_version: str
    status: CompletionStatus
    def __init__(
        self,
        schema_version: _Optional[str] = ...,
        status: _Optional[_Union[CompletionStatus, str]] = ...,
    ) -> None: ...

class ReleaseResourceRequest(_message.Message):
    __slots__ = ("schema_version", "resource_id", "attempt_id", "fence_token")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    ATTEMPT_ID_FIELD_NUMBER: _ClassVar[int]
    FENCE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    schema_version: str
    resource_id: str
    attempt_id: str
    fence_token: int
    def __init__(
        self,
        schema_version: _Optional[str] = ...,
        resource_id: _Optional[str] = ...,
        attempt_id: _Optional[str] = ...,
        fence_token: _Optional[int] = ...,
    ) -> None: ...

class ReleaseResourceResponse(_message.Message):
    __slots__ = ("schema_version", "changed")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    CHANGED_FIELD_NUMBER: _ClassVar[int]
    schema_version: str
    changed: bool
    def __init__(
        self, schema_version: _Optional[str] = ..., changed: bool = ...
    ) -> None: ...

class FinalizeStudyRequest(_message.Message):
    __slots__ = ("schema_version", "study_id", "logical_job_id", "result_sha256")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    STUDY_ID_FIELD_NUMBER: _ClassVar[int]
    LOGICAL_JOB_ID_FIELD_NUMBER: _ClassVar[int]
    RESULT_SHA256_FIELD_NUMBER: _ClassVar[int]
    schema_version: str
    study_id: str
    logical_job_id: str
    result_sha256: str
    def __init__(
        self,
        schema_version: _Optional[str] = ...,
        study_id: _Optional[str] = ...,
        logical_job_id: _Optional[str] = ...,
        result_sha256: _Optional[str] = ...,
    ) -> None: ...

class FinalizeStudyResponse(_message.Message):
    __slots__ = ("schema_version", "study_id", "terminal_outcome", "result_sha256")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    STUDY_ID_FIELD_NUMBER: _ClassVar[int]
    TERMINAL_OUTCOME_FIELD_NUMBER: _ClassVar[int]
    RESULT_SHA256_FIELD_NUMBER: _ClassVar[int]
    schema_version: str
    study_id: str
    terminal_outcome: str
    result_sha256: str
    def __init__(
        self,
        schema_version: _Optional[str] = ...,
        study_id: _Optional[str] = ...,
        terminal_outcome: _Optional[str] = ...,
        result_sha256: _Optional[str] = ...,
    ) -> None: ...
