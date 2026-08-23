from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SubmitStudy:
    idempotency_key: str
    core_release_id: str
    plugin_release_id: str
    input_ref: str
    input_sha256: str
    deadline_profile_ref: str = "m0.default"


@dataclass(frozen=True, slots=True)
class BeginAttempt:
    study_id: str
    logical_job_id: str
    begin_request_id: str
    physical_invocation_id: str
    hatchet_workflow_run_id: str
    hatchet_task_run_id: str
    plugin_release_id: str
    operation_contract_sha256: str
    worker_id: str


@dataclass(frozen=True, slots=True)
class RegisterResource:
    study_id: str
    logical_job_id: str
    attempt_id: str
    fence_token: int
    resource_key: str
    resource_kind: str


@dataclass(frozen=True, slots=True)
class CompleteAttempt:
    study_id: str
    logical_job_id: str
    attempt_id: str
    fence_token: int
    result_sha256: str
    observation_count: int
