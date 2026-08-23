from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class StudyState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    TERMINAL = "TERMINAL"


class DesiredState(StrEnum):
    RUN = "RUN"
    CANCEL = "CANCEL"


class TerminalOutcome(StrEnum):
    RECOMMENDED = "RECOMMENDED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"


class OutboxCommandKind(StrEnum):
    START_STUDY = "START_STUDY"
    CANCEL_STUDY = "CANCEL_STUDY"


class AttemptStartStatus(StrEnum):
    STARTED = "STARTED"
    EXISTING = "EXISTING"
    ALREADY_ACCEPTED = "ALREADY_ACCEPTED"
    CANCELLED = "CANCELLED"


class CompletionStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    ALREADY_ACCEPTED = "ALREADY_ACCEPTED"
    REJECTED_STALE = "REJECTED_STALE"
    REJECTED_CANCELLED = "REJECTED_CANCELLED"


@dataclass(frozen=True, slots=True)
class Study:
    study_id: str
    logical_job_id: str
    idempotency_key: str
    state: StudyState
    desired_state: DesiredState
    terminal_outcome: TerminalOutcome | None
    core_release_id: str
    plugin_release_id: str
    operation_contract_sha256: str
    input_ref: str
    input_sha256: str
    hatchet_run_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class OutboxCommand:
    command_id: str
    kind: OutboxCommandKind
    study_id: str
    logical_job_id: str
    core_release_id: str
    plugin_release_id: str
    operation_contract_sha256: str
    input_ref: str
    input_sha256: str
    continuation_no: int
    deadline_profile_ref: str
    claim_token: str


@dataclass(frozen=True, slots=True)
class AttemptGrant:
    status: AttemptStartStatus
    attempt_id: str | None
    fence_token: int | None
    lease_expires_at: datetime | None
    accepted_result_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ResourceGrant:
    resource_id: str
    locator_ref: str
    locator_sha256: str
    expires_at: datetime
