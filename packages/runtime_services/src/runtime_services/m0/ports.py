from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from experiment_domain.m0 import (
    AttemptGrant,
    CompletionStatus,
    OutboxCommand,
    ResourceGrant,
    Study,
)
from runtime_services.m0.commands import (
    BeginAttempt,
    CompleteAttempt,
    RegisterResource,
    SubmitStudy,
)


class ProductRepository(Protocol):
    def submit_study(self, command: SubmitStudy, *, active_limit: int) -> Study: ...

    def get_study(self, study_id: str) -> Study: ...

    def request_cancellation(self, study_id: str) -> Study: ...

    def claim_outbox(self, *, lease: timedelta) -> OutboxCommand | None: ...

    def mark_outbox_dispatched(
        self, command_id: str, claim_token: str, hatchet_run_id: str | None
    ) -> None: ...

    def release_outbox_claim(
        self, command_id: str, claim_token: str, error_code: str
    ) -> None: ...

    def begin_attempt(
        self, command: BeginAttempt, *, lease: timedelta
    ) -> AttemptGrant: ...

    def register_resource(
        self, command: RegisterResource, *, lease: timedelta
    ) -> ResourceGrant: ...

    def complete_attempt(self, command: CompleteAttempt) -> CompletionStatus: ...

    def release_resource(
        self, resource_id: str, attempt_id: str, fence_token: int
    ) -> bool: ...

    def finalize_study(
        self, study_id: str, logical_job_id: str, result_sha256: str
    ) -> Study: ...

    def reap_expired_resources(self, *, limit: int) -> int: ...

    def finalize_cancelled_studies(self, *, limit: int) -> int: ...
