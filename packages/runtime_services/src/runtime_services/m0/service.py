from __future__ import annotations

from datetime import timedelta

from experiment_domain.m0 import (
    AttemptGrant,
    CompletionStatus,
    ResourceGrant,
    Study,
)
from runtime_services.m0.commands import (
    BeginAttempt,
    CompleteAttempt,
    RegisterResource,
    SubmitStudy,
)
from runtime_services.m0.ports import ProductRepository


class ControlService:
    """Thin application boundary; transactional invariants live in the repository."""

    def __init__(
        self,
        repository: ProductRepository,
        *,
        active_study_limit: int = 100,
        attempt_lease: timedelta = timedelta(seconds=30),
        resource_lease: timedelta = timedelta(seconds=45),
    ) -> None:
        if active_study_limit < 1:
            raise ValueError("active_study_limit must be positive")
        self._repository = repository
        self._active_study_limit = active_study_limit
        self._attempt_lease = attempt_lease
        self._resource_lease = resource_lease

    def submit(self, command: SubmitStudy) -> Study:
        return self._repository.submit_study(
            command, active_limit=self._active_study_limit
        )

    def status(self, study_id: str) -> Study:
        return self._repository.get_study(study_id)

    def cancel(self, study_id: str) -> Study:
        return self._repository.request_cancellation(study_id)

    def begin_attempt(self, command: BeginAttempt) -> AttemptGrant:
        return self._repository.begin_attempt(command, lease=self._attempt_lease)

    def register_resource(self, command: RegisterResource) -> ResourceGrant:
        return self._repository.register_resource(command, lease=self._resource_lease)

    def complete_attempt(self, command: CompleteAttempt) -> CompletionStatus:
        return self._repository.complete_attempt(command)

    def release_resource(
        self, resource_id: str, attempt_id: str, fence_token: int
    ) -> bool:
        return self._repository.release_resource(resource_id, attempt_id, fence_token)

    def finalize(self, study_id: str, logical_job_id: str, result_sha256: str) -> Study:
        return self._repository.finalize_study(study_id, logical_job_id, result_sha256)
