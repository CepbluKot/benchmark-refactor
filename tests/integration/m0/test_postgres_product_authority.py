from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from benchmark_adapters.postgres import PostgresProductRepository
from benchmark_adapters.postgres.schema import accepted_results, resources
from experiment_domain.m0 import (
    AcceptedResultConflict,
    AttemptStartStatus,
    CapacityExhausted,
    CompletionStatus,
    InvalidTransition,
    StudyState,
    TerminalOutcome,
)
from optimizer_sdk.m0 import toy_operation_contract_sha256
from runtime_services.m0 import (
    BeginAttempt,
    CompleteAttempt,
    RegisterResource,
    SubmitStudy,
)


def _submission(key: str, *, input_hash: str = "a" * 64) -> SubmitStudy:
    return SubmitStudy(
        idempotency_key=key,
        core_release_id="m0-a",
        plugin_release_id="m0-a",
        input_ref=f"artifact://sha256/{input_hash}",
        input_sha256=input_hash,
    )


def _begin(study, request_id: str) -> BeginAttempt:
    return BeginAttempt(
        study_id=study.study_id,
        logical_job_id=study.logical_job_id,
        begin_request_id=request_id,
        physical_invocation_id=request_id,
        hatchet_workflow_run_id="hatchet-workflow-1",
        hatchet_task_run_id=f"task-{request_id}",
        plugin_release_id="m0-a",
        operation_contract_sha256=toy_operation_contract_sha256(
            core_release_id=study.core_release_id,
            plugin_release_id=study.plugin_release_id,
            input_ref=study.input_ref,
            input_sha256=study.input_sha256,
            continuation_no=0,
            deadline_profile_ref="m0.default",
        ),
        worker_id="toy-worker-a",
    )


def test_submission_is_idempotent_and_capacity_is_atomic(product_engine) -> None:
    repository = PostgresProductRepository(product_engine)
    first = repository.submit_study(_submission("same"), active_limit=2)
    repeated = repository.submit_study(_submission("same"), active_limit=2)
    assert repeated.study_id == first.study_id

    with pytest.raises(AcceptedResultConflict):
        repository.submit_study(
            _submission("same", input_hash="b" * 64), active_limit=2
        )

    repository.submit_study(_submission("second"), active_limit=2)
    with pytest.raises(CapacityExhausted):
        repository.submit_study(_submission("third"), active_limit=2)


def test_admission_accepts_100_active_studies_and_rejects_101st(
    product_engine,
) -> None:
    repository = PostgresProductRepository(product_engine)
    for index in range(100):
        repository.submit_study(_submission(f"capacity-{index}"), active_limit=100)

    with pytest.raises(CapacityExhausted):
        repository.submit_study(_submission("capacity-100"), active_limit=100)


def test_concurrent_admission_never_overshoots_limit(product_engine) -> None:
    repository = PostgresProductRepository(product_engine)

    def submit(index: int) -> bool:
        try:
            repository.submit_study(_submission(f"concurrent-{index}"), active_limit=10)
        except CapacityExhausted:
            return False
        return True

    with ThreadPoolExecutor(max_workers=20) as executor:
        accepted = list(executor.map(submit, range(20)))

    assert accepted.count(True) == 10
    assert accepted.count(False) == 10


def test_concurrent_duplicate_begin_returns_one_domain_attempt(product_engine) -> None:
    repository = PostgresProductRepository(product_engine)
    study = repository.submit_study(_submission("concurrent-begin"), active_limit=100)
    command = _begin(study, "same-concurrent-begin")

    with ThreadPoolExecutor(max_workers=8) as executor:
        grants = list(
            executor.map(
                lambda _: repository.begin_attempt(command, lease=timedelta(minutes=1)),
                range(8),
            )
        )

    assert sum(grant.status == AttemptStartStatus.STARTED for grant in grants) == 1
    assert {grant.attempt_id for grant in grants} == {grants[0].attempt_id}
    assert {grant.fence_token for grant in grants} == {grants[0].fence_token}


def test_late_fence_cannot_commit_and_only_one_result_is_accepted(
    product_engine,
) -> None:
    repository = PostgresProductRepository(product_engine)
    study = repository.submit_study(_submission("fencing"), active_limit=100)

    first = repository.begin_attempt(
        _begin(study, "task-1:1"), lease=timedelta(minutes=1)
    )
    duplicate = repository.begin_attempt(
        _begin(study, "task-1:1"), lease=timedelta(minutes=1)
    )
    assert first.status == AttemptStartStatus.STARTED
    assert duplicate.status == AttemptStartStatus.EXISTING
    assert duplicate.attempt_id == first.attempt_id
    assert duplicate.fence_token == first.fence_token

    second = repository.begin_attempt(
        _begin(study, "task-1:2"), lease=timedelta(minutes=1)
    )
    assert second.fence_token == first.fence_token + 1

    stale = repository.complete_attempt(
        CompleteAttempt(
            study_id=study.study_id,
            logical_job_id=study.logical_job_id,
            attempt_id=first.attempt_id,
            fence_token=first.fence_token,
            result_sha256="1" * 64,
            observation_count=1,
        )
    )
    assert stale == CompletionStatus.REJECTED_STALE

    accepted = repository.complete_attempt(
        CompleteAttempt(
            study_id=study.study_id,
            logical_job_id=study.logical_job_id,
            attempt_id=second.attempt_id,
            fence_token=second.fence_token,
            result_sha256="2" * 64,
            observation_count=1,
        )
    )
    assert accepted == CompletionStatus.ACCEPTED
    assert (
        repository.complete_attempt(
            CompleteAttempt(
                study_id=study.study_id,
                logical_job_id=study.logical_job_id,
                attempt_id=second.attempt_id,
                fence_token=second.fence_token,
                result_sha256="2" * 64,
                observation_count=1,
            )
        )
        == CompletionStatus.ALREADY_ACCEPTED
    )

    with pytest.raises(AcceptedResultConflict):
        repository.complete_attempt(
            CompleteAttempt(
                study_id=study.study_id,
                logical_job_id=study.logical_job_id,
                attempt_id=second.attempt_id,
                fence_token=second.fence_token,
                result_sha256="3" * 64,
                observation_count=1,
            )
        )

    terminal = repository.finalize_study(study.study_id, study.logical_job_id, "2" * 64)
    assert terminal.state == StudyState.TERMINAL
    assert terminal.terminal_outcome == TerminalOutcome.RECOMMENDED
    with product_engine.connect() as connection:
        assert (
            connection.scalar(select(func.count()).select_from(accepted_results)) == 1
        )


def test_resources_are_attempt_scoped_and_cancellation_finishes_via_reaper(
    product_engine,
) -> None:
    repository = PostgresProductRepository(product_engine)
    study = repository.submit_study(_submission("resources"), active_limit=100)
    first = repository.begin_attempt(
        _begin(study, "task-2:1"), lease=timedelta(minutes=1)
    )
    old_resource = repository.register_resource(
        RegisterResource(
            study_id=study.study_id,
            logical_job_id=study.logical_job_id,
            attempt_id=first.attempt_id,
            fence_token=first.fence_token,
            resource_key="scratch",
            resource_kind="toy.scratch",
        ),
        lease=timedelta(seconds=-1),
    )
    second = repository.begin_attempt(
        _begin(study, "task-2:2"), lease=timedelta(minutes=1)
    )
    new_resource = repository.register_resource(
        RegisterResource(
            study_id=study.study_id,
            logical_job_id=study.logical_job_id,
            attempt_id=second.attempt_id,
            fence_token=second.fence_token,
            resource_key="scratch",
            resource_kind="toy.scratch",
        ),
        lease=timedelta(minutes=1),
    )

    assert repository.release_resource(
        old_resource.resource_id, first.attempt_id, first.fence_token
    )
    with product_engine.connect() as connection:
        new_state = connection.scalar(
            select(resources.c.state).where(resources.c.id == new_resource.resource_id)
        )
    assert new_state == "ACTIVE"

    cancelling = repository.request_cancellation(study.study_id)
    assert cancelling.state == StudyState.CANCELLING
    assert repository.finalize_cancelled_studies(limit=10) == 0
    assert repository.release_resource(
        new_resource.resource_id, second.attempt_id, second.fence_token
    )
    assert repository.finalize_cancelled_studies(limit=10) == 1
    terminal = repository.get_study(study.study_id)
    assert terminal.terminal_outcome == TerminalOutcome.CANCELLED


def test_idempotency_keys_are_bound_to_the_original_invocation(product_engine) -> None:
    repository = PostgresProductRepository(product_engine)
    first_study = repository.submit_study(
        _submission("binding-first"), active_limit=100
    )
    second_study = repository.submit_study(
        _submission("binding-second"), active_limit=100
    )
    first = repository.begin_attempt(
        _begin(first_study, "shared-begin-id"), lease=timedelta(minutes=1)
    )

    with pytest.raises(InvalidTransition):
        repository.begin_attempt(
            replace(
                _begin(first_study, "shared-begin-id"),
                operation_contract_sha256="f" * 64,
            ),
            lease=timedelta(minutes=1),
        )

    with pytest.raises(InvalidTransition):
        repository.begin_attempt(
            _begin(second_study, "shared-begin-id"), lease=timedelta(minutes=1)
        )

    resource = repository.register_resource(
        RegisterResource(
            study_id=first_study.study_id,
            logical_job_id=first_study.logical_job_id,
            attempt_id=first.attempt_id,
            fence_token=first.fence_token,
            resource_key="scratch",
            resource_kind="toy.scratch",
        ),
        lease=timedelta(minutes=1),
    )
    assert resource.resource_id
    with pytest.raises(InvalidTransition):
        repository.register_resource(
            RegisterResource(
                study_id=first_study.study_id,
                logical_job_id=first_study.logical_job_id,
                attempt_id=first.attempt_id,
                fence_token=first.fence_token,
                resource_key="scratch",
                resource_kind="toy.other",
            ),
            lease=timedelta(minutes=1),
        )

    repository.begin_attempt(
        _begin(first_study, "newer-attempt"), lease=timedelta(minutes=1)
    )
    with pytest.raises(InvalidTransition):
        repository.register_resource(
            RegisterResource(
                study_id=first_study.study_id,
                logical_job_id=first_study.logical_job_id,
                attempt_id=first.attempt_id,
                fence_token=first.fence_token,
                resource_key="scratch",
                resource_kind="toy.scratch",
            ),
            lease=timedelta(minutes=1),
        )


def test_expired_attempt_cannot_register_or_commit(product_engine) -> None:
    repository = PostgresProductRepository(product_engine)
    study = repository.submit_study(_submission("expired"), active_limit=100)
    attempt = repository.begin_attempt(
        _begin(study, "expired-attempt"), lease=timedelta(seconds=-1)
    )

    with pytest.raises(InvalidTransition):
        repository.register_resource(
            RegisterResource(
                study_id=study.study_id,
                logical_job_id=study.logical_job_id,
                attempt_id=attempt.attempt_id,
                fence_token=attempt.fence_token,
                resource_key="scratch",
                resource_kind="toy.scratch",
            ),
            lease=timedelta(minutes=1),
        )

    assert (
        repository.complete_attempt(
            CompleteAttempt(
                study_id=study.study_id,
                logical_job_id=study.logical_job_id,
                attempt_id=attempt.attempt_id,
                fence_token=attempt.fence_token,
                result_sha256="4" * 64,
                observation_count=1,
            )
        )
        == CompletionStatus.REJECTED_STALE
    )


def test_attempt_and_finalization_cannot_cross_study_boundary(product_engine) -> None:
    repository = PostgresProductRepository(product_engine)
    first_study = repository.submit_study(_submission("cross-first"), active_limit=100)
    second_study = repository.submit_study(
        _submission("cross-second"), active_limit=100
    )
    attempt = repository.begin_attempt(
        _begin(first_study, "cross-attempt"), lease=timedelta(minutes=1)
    )
    result_hash = "5" * 64
    assert (
        repository.complete_attempt(
            CompleteAttempt(
                study_id=first_study.study_id,
                logical_job_id=first_study.logical_job_id,
                attempt_id=attempt.attempt_id,
                fence_token=attempt.fence_token,
                result_sha256=result_hash,
                observation_count=1,
            )
        )
        == CompletionStatus.ACCEPTED
    )

    with pytest.raises(InvalidTransition):
        repository.complete_attempt(
            CompleteAttempt(
                study_id=second_study.study_id,
                logical_job_id=first_study.logical_job_id,
                attempt_id=attempt.attempt_id,
                fence_token=attempt.fence_token,
                result_sha256=result_hash,
                observation_count=1,
            )
        )
    with pytest.raises(InvalidTransition):
        repository.finalize_study(
            second_study.study_id, first_study.logical_job_id, result_hash
        )

    repository.finalize_study(
        first_study.study_id, first_study.logical_job_id, result_hash
    )
    with pytest.raises(InvalidTransition):
        repository.finalize_study(
            first_study.study_id, first_study.logical_job_id, "6" * 64
        )


def test_late_outbox_mapping_cannot_reopen_terminal_study(product_engine) -> None:
    repository = PostgresProductRepository(product_engine)
    study = repository.submit_study(_submission("terminal-race"), active_limit=100)
    outbox = repository.claim_outbox(lease=timedelta(minutes=1))
    assert outbox is not None

    attempt = repository.begin_attempt(
        _begin(study, "terminal-race-attempt"), lease=timedelta(minutes=1)
    )
    result_hash = "7" * 64
    assert (
        repository.complete_attempt(
            CompleteAttempt(
                study_id=study.study_id,
                logical_job_id=study.logical_job_id,
                attempt_id=attempt.attempt_id,
                fence_token=attempt.fence_token,
                result_sha256=result_hash,
                observation_count=1,
            )
        )
        == CompletionStatus.ACCEPTED
    )
    repository.finalize_study(study.study_id, study.logical_job_id, result_hash)

    repository.mark_outbox_dispatched(
        outbox.command_id, outbox.claim_token, "hatchet-run-after-terminal"
    )
    terminal = repository.get_study(study.study_id)
    assert terminal.state == StudyState.TERMINAL
    assert terminal.terminal_outcome == TerminalOutcome.RECOMMENDED
    assert terminal.hatchet_run_id == "hatchet-run-after-terminal"
