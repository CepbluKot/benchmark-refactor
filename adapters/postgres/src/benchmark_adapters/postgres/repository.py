from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import Connection, Engine, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from benchmark_adapters.postgres.schema import (
    accepted_results,
    attempts,
    logical_jobs,
    outbox_commands,
    resources,
    studies,
    workflow_projection,
)
from experiment_domain.m0 import (
    AcceptedResultConflict,
    AttemptGrant,
    AttemptStartStatus,
    CapacityExhausted,
    CompletionStatus,
    DesiredState,
    EntityNotFound,
    InvalidTransition,
    OutboxCommand,
    OutboxCommandKind,
    ResourceGrant,
    Study,
    StudyState,
    TerminalOutcome,
)
from optimizer_sdk.m0 import core_study_route, toy_operation_contract_sha256
from runtime_services.m0.commands import (
    BeginAttempt,
    CompleteAttempt,
    RegisterResource,
    SubmitStudy,
)


_ADMISSION_LOCK_KEY = 7_430_021_001
_ACTIVE_ATTEMPT_STATES = ("LEASED", "RUNNING")


def _database_now(connection: Connection) -> datetime:
    value = connection.scalar(select(func.clock_timestamp()))
    if value is None:
        raise RuntimeError("PostgreSQL clock is unavailable")
    return value


def _advisory_key(namespace: str, value: str) -> int:
    digest = sha256(f"{namespace}:{value}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


class PostgresProductRepository:
    """PostgreSQL implementation of product authority and fencing."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def submit_study(self, command: SubmitStudy, *, active_limit: int) -> Study:
        study_id = str(uuid4())
        logical_job_id = str(uuid4())
        outbox_id = str(uuid4())
        operation_contract_sha256 = toy_operation_contract_sha256(
            core_release_id=command.core_release_id,
            plugin_release_id=command.plugin_release_id,
            input_ref=command.input_ref,
            input_sha256=command.input_sha256,
            continuation_no=0,
            deadline_profile_ref=command.deadline_profile_ref,
        )
        with self._engine.begin() as connection:
            now = _database_now(connection)
            connection.execute(select(func.pg_advisory_xact_lock(_ADMISSION_LOCK_KEY)))

            existing = (
                connection.execute(
                    select(studies).where(
                        studies.c.idempotency_key == command.idempotency_key
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                expected = (
                    command.core_release_id,
                    command.plugin_release_id,
                    command.input_ref,
                    command.input_sha256,
                    command.deadline_profile_ref,
                )
                actual = (
                    existing["core_release_id"],
                    existing["plugin_release_id"],
                    existing["input_ref"],
                    existing["input_sha256"],
                    existing["deadline_profile_ref"],
                )
                if actual != expected:
                    raise AcceptedResultConflict(
                        "idempotency key is already bound to a different submission"
                    )
                return self._study_on_connection(connection, existing["id"])

            active_count = connection.scalar(
                select(func.count())
                .select_from(studies)
                .where(studies.c.state != StudyState.TERMINAL.value)
            )
            if int(active_count or 0) >= active_limit:
                raise CapacityExhausted(
                    f"active study limit {active_limit} has been reached"
                )

            connection.execute(
                studies.insert().values(
                    id=study_id,
                    idempotency_key=command.idempotency_key,
                    state=StudyState.QUEUED.value,
                    desired_state=DesiredState.RUN.value,
                    terminal_outcome=None,
                    core_release_id=command.core_release_id,
                    plugin_release_id=command.plugin_release_id,
                    input_ref=command.input_ref,
                    input_sha256=command.input_sha256,
                    deadline_profile_ref=command.deadline_profile_ref,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                logical_jobs.insert().values(
                    id=logical_job_id,
                    study_id=study_id,
                    logical_key="m0.toy.measure",
                    operation_contract_sha256=operation_contract_sha256,
                    state="READY",
                    current_fence=0,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                outbox_commands.insert().values(
                    id=outbox_id,
                    study_id=study_id,
                    logical_job_id=logical_job_id,
                    kind=OutboxCommandKind.START_STUDY.value,
                    idempotency_key=f"start:{study_id}:0",
                    status="PENDING",
                    core_release_id=command.core_release_id,
                    plugin_release_id=command.plugin_release_id,
                    operation_contract_sha256=operation_contract_sha256,
                    input_ref=command.input_ref,
                    input_sha256=command.input_sha256,
                    continuation_no=0,
                    deadline_profile_ref=command.deadline_profile_ref,
                    created_at=now,
                )
            )
            connection.execute(
                workflow_projection.insert().values(
                    study_id=study_id,
                    start_command_id=outbox_id,
                    workflow_route=core_study_route(command.core_release_id),
                    updated_at=now,
                )
            )

            return self._study_on_connection(connection, study_id)

    def get_study(self, study_id: str) -> Study:
        with self._engine.connect() as connection:
            return self._study_on_connection(connection, study_id)

    def request_cancellation(self, study_id: str) -> Study:
        with self._engine.begin() as connection:
            now = _database_now(connection)
            study_row = (
                connection.execute(
                    select(studies).where(studies.c.id == study_id).with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if study_row is None:
                raise EntityNotFound("study does not exist")
            if study_row["state"] == StudyState.TERMINAL.value:
                return self._study_on_connection(connection, study_id)

            job_row = (
                connection.execute(
                    select(logical_jobs)
                    .where(logical_jobs.c.study_id == study_id)
                    .with_for_update()
                )
                .mappings()
                .one()
            )

            connection.execute(
                studies.update()
                .where(studies.c.id == study_id)
                .values(
                    desired_state=DesiredState.CANCEL.value,
                    state=StudyState.CANCELLING.value,
                    updated_at=now,
                )
            )
            connection.execute(
                logical_jobs.update()
                .where(logical_jobs.c.id == job_row["id"])
                .values(
                    current_fence=logical_jobs.c.current_fence + 1,
                    state="CANCELLED",
                    updated_at=now,
                )
            )
            connection.execute(
                attempts.update()
                .where(
                    attempts.c.logical_job_id == job_row["id"],
                    attempts.c.state.in_(_ACTIVE_ATTEMPT_STATES),
                )
                .values(state="CANCELLED", updated_at=now)
            )
            connection.execute(
                pg_insert(outbox_commands)
                .values(
                    id=str(uuid4()),
                    study_id=study_id,
                    logical_job_id=job_row["id"],
                    kind=OutboxCommandKind.CANCEL_STUDY.value,
                    idempotency_key=f"cancel:{study_id}",
                    status="PENDING",
                    core_release_id=study_row["core_release_id"],
                    plugin_release_id=study_row["plugin_release_id"],
                    operation_contract_sha256=job_row["operation_contract_sha256"],
                    input_ref=study_row["input_ref"],
                    input_sha256=study_row["input_sha256"],
                    continuation_no=0,
                    deadline_profile_ref=study_row["deadline_profile_ref"],
                    created_at=now,
                )
                .on_conflict_do_nothing(index_elements=["idempotency_key"])
            )
            return self._study_on_connection(connection, study_id)

    def claim_outbox(self, *, lease: timedelta) -> OutboxCommand | None:
        claim_token = str(uuid4())
        with self._engine.begin() as connection:
            now = _database_now(connection)
            row = (
                connection.execute(
                    select(outbox_commands)
                    .where(
                        outbox_commands.c.status == "PENDING",
                        or_(
                            outbox_commands.c.claim_until.is_(None),
                            outbox_commands.c.claim_until < now,
                        ),
                    )
                    .order_by(outbox_commands.c.created_at, outbox_commands.c.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None

            connection.execute(
                outbox_commands.update()
                .where(outbox_commands.c.id == row["id"])
                .values(
                    claim_token=claim_token,
                    claim_until=now + lease,
                    attempt_count=outbox_commands.c.attempt_count + 1,
                )
            )
            return OutboxCommand(
                command_id=row["id"],
                kind=OutboxCommandKind(row["kind"]),
                study_id=row["study_id"],
                logical_job_id=row["logical_job_id"],
                core_release_id=row["core_release_id"],
                plugin_release_id=row["plugin_release_id"],
                operation_contract_sha256=row["operation_contract_sha256"],
                input_ref=row["input_ref"],
                input_sha256=row["input_sha256"],
                continuation_no=row["continuation_no"],
                deadline_profile_ref=row["deadline_profile_ref"],
                claim_token=claim_token,
            )

    def mark_outbox_dispatched(
        self, command_id: str, claim_token: str, hatchet_run_id: str | None
    ) -> None:
        with self._engine.begin() as connection:
            now = _database_now(connection)
            row = (
                connection.execute(
                    select(outbox_commands)
                    .where(outbox_commands.c.id == command_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise EntityNotFound("outbox command does not exist")
            if row["status"] == "DISPATCHED":
                if row["hatchet_run_id"] != hatchet_run_id:
                    raise AcceptedResultConflict(
                        "outbox command is mapped to a different Hatchet run"
                    )
                return
            if row["claim_token"] != claim_token:
                raise InvalidTransition("outbox claim is no longer current")

            connection.execute(
                outbox_commands.update()
                .where(outbox_commands.c.id == command_id)
                .values(
                    status="DISPATCHED",
                    hatchet_run_id=hatchet_run_id,
                    dispatched_at=now,
                    claim_token=None,
                    claim_until=None,
                    last_error_code=None,
                )
            )
            if row["kind"] == OutboxCommandKind.START_STUDY.value:
                projection = (
                    connection.execute(
                        select(workflow_projection)
                        .where(workflow_projection.c.study_id == row["study_id"])
                        .with_for_update()
                    )
                    .mappings()
                    .one()
                )
                existing_run_id = projection["hatchet_run_id"]
                if existing_run_id not in (None, hatchet_run_id):
                    raise AcceptedResultConflict(
                        "study is mapped to a different Hatchet run"
                    )
                connection.execute(
                    workflow_projection.update()
                    .where(workflow_projection.c.study_id == row["study_id"])
                    .values(hatchet_run_id=hatchet_run_id, updated_at=now)
                )
                connection.execute(
                    studies.update()
                    .where(
                        studies.c.id == row["study_id"],
                        studies.c.desired_state == DesiredState.RUN.value,
                        studies.c.state != StudyState.TERMINAL.value,
                        studies.c.terminal_outcome.is_(None),
                    )
                    .values(state=StudyState.RUNNING.value, updated_at=now)
                )

    def release_outbox_claim(
        self, command_id: str, claim_token: str, error_code: str
    ) -> None:
        with self._engine.begin() as connection:
            result = connection.execute(
                outbox_commands.update()
                .where(
                    outbox_commands.c.id == command_id,
                    outbox_commands.c.status == "PENDING",
                    outbox_commands.c.claim_token == claim_token,
                )
                .values(
                    claim_token=None,
                    claim_until=None,
                    last_error_code=error_code[:64],
                )
            )
            if result.rowcount != 1:
                raise InvalidTransition("outbox claim is no longer current")

    def begin_attempt(self, command: BeginAttempt, *, lease: timedelta) -> AttemptGrant:
        with self._engine.begin() as connection:
            now = _database_now(connection)
            connection.execute(
                select(
                    func.pg_advisory_xact_lock(
                        _advisory_key("begin-attempt", command.begin_request_id)
                    )
                )
            )
            existing = (
                connection.execute(
                    select(attempts).where(
                        attempts.c.begin_request_id == command.begin_request_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                binding = (
                    existing["study_id"],
                    existing["logical_job_id"],
                    existing["physical_invocation_id"],
                    existing["hatchet_workflow_run_id"],
                    existing["hatchet_task_run_id"],
                    existing["plugin_release_id"],
                    existing["operation_contract_sha256"],
                    existing["worker_id"],
                )
                requested = (
                    command.study_id,
                    command.logical_job_id,
                    command.physical_invocation_id,
                    command.hatchet_workflow_run_id,
                    command.hatchet_task_run_id,
                    command.plugin_release_id,
                    command.operation_contract_sha256,
                    command.worker_id,
                )
                if binding != requested:
                    raise InvalidTransition(
                        "begin request ID is bound to a different invocation"
                    )
                accepted = self._accepted_result_on_connection(
                    connection, existing["logical_job_id"]
                )
                return AttemptGrant(
                    status=(
                        AttemptStartStatus.ALREADY_ACCEPTED
                        if accepted is not None
                        else AttemptStartStatus.EXISTING
                    ),
                    attempt_id=existing["id"],
                    fence_token=existing["fence_token"],
                    lease_expires_at=existing["lease_expires_at"],
                    accepted_result_sha256=(
                        accepted["result_sha256"] if accepted is not None else None
                    ),
                )

            study_row = (
                connection.execute(
                    select(studies)
                    .where(studies.c.id == command.study_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            job_row = (
                connection.execute(
                    select(logical_jobs)
                    .where(logical_jobs.c.id == command.logical_job_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if study_row is None or job_row is None:
                raise EntityNotFound("study or logical job does not exist")
            if job_row["study_id"] != command.study_id:
                raise InvalidTransition("logical job does not belong to study")
            if study_row["plugin_release_id"] != command.plugin_release_id:
                raise InvalidTransition("plugin release does not match sealed study")
            if (
                job_row["operation_contract_sha256"]
                != command.operation_contract_sha256
            ):
                raise InvalidTransition("operation contract does not match sealed job")
            if study_row["desired_state"] == DesiredState.CANCEL.value:
                return AttemptGrant(
                    status=AttemptStartStatus.CANCELLED,
                    attempt_id=None,
                    fence_token=None,
                    lease_expires_at=None,
                )

            accepted = self._accepted_result_on_connection(
                connection, command.logical_job_id
            )
            if accepted is not None:
                return AttemptGrant(
                    status=AttemptStartStatus.ALREADY_ACCEPTED,
                    attempt_id=accepted["attempt_id"],
                    fence_token=accepted["fence_token"],
                    lease_expires_at=None,
                    accepted_result_sha256=accepted["result_sha256"],
                )

            connection.execute(
                attempts.update()
                .where(
                    attempts.c.logical_job_id == command.logical_job_id,
                    attempts.c.state.in_(_ACTIVE_ATTEMPT_STATES),
                )
                .values(state="LOST", updated_at=now)
            )
            new_fence = connection.scalar(
                logical_jobs.update()
                .where(logical_jobs.c.id == command.logical_job_id)
                .values(
                    current_fence=logical_jobs.c.current_fence + 1,
                    state="ACTIVE",
                    updated_at=now,
                )
                .returning(logical_jobs.c.current_fence)
            )
            if new_fence is None:
                raise InvalidTransition("logical job could not be fenced")

            attempt_id = str(uuid4())
            lease_expires_at = now + lease
            connection.execute(
                attempts.insert().values(
                    id=attempt_id,
                    study_id=command.study_id,
                    logical_job_id=command.logical_job_id,
                    begin_request_id=command.begin_request_id,
                    physical_invocation_id=command.physical_invocation_id,
                    fence_token=new_fence,
                    state="LEASED",
                    lease_expires_at=lease_expires_at,
                    hatchet_workflow_run_id=command.hatchet_workflow_run_id,
                    hatchet_task_run_id=command.hatchet_task_run_id,
                    plugin_release_id=command.plugin_release_id,
                    operation_contract_sha256=command.operation_contract_sha256,
                    worker_id=command.worker_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            return AttemptGrant(
                status=AttemptStartStatus.STARTED,
                attempt_id=attempt_id,
                fence_token=int(new_fence),
                lease_expires_at=lease_expires_at,
            )

    def register_resource(
        self, command: RegisterResource, *, lease: timedelta
    ) -> ResourceGrant:
        with self._engine.begin() as connection:
            now = _database_now(connection)
            attempt_row = (
                connection.execute(
                    select(attempts).where(attempts.c.id == command.attempt_id)
                )
                .mappings()
                .one_or_none()
            )
            job_row = (
                connection.execute(
                    select(logical_jobs)
                    .where(logical_jobs.c.id == command.logical_job_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if attempt_row is None or job_row is None:
                raise EntityNotFound("attempt or logical job does not exist")
            if (
                attempt_row["study_id"] != command.study_id
                or attempt_row["logical_job_id"] != command.logical_job_id
                or attempt_row["fence_token"] != command.fence_token
                or attempt_row["state"] not in _ACTIVE_ATTEMPT_STATES
                or attempt_row["lease_expires_at"] <= now
                or job_row["study_id"] != command.study_id
                or job_row["state"] != "ACTIVE"
                or job_row["current_fence"] != command.fence_token
            ):
                raise InvalidTransition("attempt fence is stale")

            existing = (
                connection.execute(
                    select(resources).where(
                        resources.c.attempt_id == command.attempt_id,
                        resources.c.resource_key == command.resource_key,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if (
                    existing["study_id"] != command.study_id
                    or existing["logical_job_id"] != command.logical_job_id
                    or existing["fence_token"] != command.fence_token
                    or existing["resource_kind"] != command.resource_kind
                ):
                    raise InvalidTransition(
                        "resource key is bound to a different attempt operation"
                    )
                if existing["state"] != "ACTIVE" or existing["expires_at"] <= now:
                    raise InvalidTransition("resource grant is no longer active")
                return ResourceGrant(
                    resource_id=existing["id"],
                    locator_ref=existing["locator_ref"],
                    locator_sha256=existing["locator_sha256"],
                    expires_at=existing["expires_at"],
                )

            locator_ref = (
                f"m0://toy/{command.study_id}/{command.logical_job_id}/"
                f"{command.attempt_id}/{command.resource_kind}/{command.resource_key}"
            )
            locator_sha256 = sha256(locator_ref.encode("utf-8")).hexdigest()
            resource_id = str(uuid4())
            expires_at = now + lease
            connection.execute(
                resources.insert().values(
                    id=resource_id,
                    study_id=command.study_id,
                    logical_job_id=command.logical_job_id,
                    attempt_id=command.attempt_id,
                    fence_token=command.fence_token,
                    resource_key=command.resource_key,
                    resource_kind=command.resource_kind,
                    locator_ref=locator_ref,
                    locator_sha256=locator_sha256,
                    state="ACTIVE",
                    expires_at=expires_at,
                    created_at=now,
                )
            )
            return ResourceGrant(
                resource_id=resource_id,
                locator_ref=locator_ref,
                locator_sha256=locator_sha256,
                expires_at=expires_at,
            )

    def complete_attempt(self, command: CompleteAttempt) -> CompletionStatus:
        with self._engine.begin() as connection:
            now = _database_now(connection)
            study_row = (
                connection.execute(
                    select(studies)
                    .where(studies.c.id == command.study_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            job_row = (
                connection.execute(
                    select(logical_jobs)
                    .where(logical_jobs.c.id == command.logical_job_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            attempt_row = (
                connection.execute(
                    select(attempts)
                    .where(attempts.c.id == command.attempt_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if study_row is None or job_row is None or attempt_row is None:
                raise EntityNotFound("study, job, or attempt does not exist")

            if job_row["study_id"] != command.study_id:
                raise InvalidTransition("logical job does not belong to study")
            if (
                attempt_row["study_id"] != command.study_id
                or attempt_row["logical_job_id"] != command.logical_job_id
                or attempt_row["fence_token"] != command.fence_token
            ):
                raise InvalidTransition("attempt identity does not match request")

            accepted = self._accepted_result_on_connection(
                connection, command.logical_job_id
            )
            if accepted is not None:
                if accepted["result_sha256"] != command.result_sha256:
                    raise AcceptedResultConflict(
                        "a different result is already accepted for logical job"
                    )
                return CompletionStatus.ALREADY_ACCEPTED

            if study_row["desired_state"] == DesiredState.CANCEL.value:
                connection.execute(
                    attempts.update()
                    .where(attempts.c.id == command.attempt_id)
                    .values(state="CANCELLED", updated_at=now)
                )
                return CompletionStatus.REJECTED_CANCELLED

            is_current = (
                job_row["current_fence"] == command.fence_token
                and attempt_row["state"] in _ACTIVE_ATTEMPT_STATES
                and attempt_row["lease_expires_at"] > now
            )
            if not is_current:
                connection.execute(
                    attempts.update()
                    .where(attempts.c.id == command.attempt_id)
                    .values(state="REJECTED_STALE", updated_at=now)
                )
                return CompletionStatus.REJECTED_STALE

            connection.execute(
                accepted_results.insert().values(
                    id=str(uuid4()),
                    logical_job_id=command.logical_job_id,
                    attempt_id=command.attempt_id,
                    fence_token=command.fence_token,
                    result_sha256=command.result_sha256,
                    summary={"observation_count": command.observation_count},
                    accepted_at=now,
                )
            )
            connection.execute(
                attempts.update()
                .where(attempts.c.id == command.attempt_id)
                .values(state="SUCCEEDED", updated_at=now)
            )
            connection.execute(
                logical_jobs.update()
                .where(logical_jobs.c.id == command.logical_job_id)
                .values(state="SUCCEEDED", updated_at=now)
            )
            return CompletionStatus.ACCEPTED

    def release_resource(
        self, resource_id: str, attempt_id: str, fence_token: int
    ) -> bool:
        with self._engine.begin() as connection:
            now = _database_now(connection)
            row = (
                connection.execute(
                    select(resources)
                    .where(resources.c.id == resource_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise EntityNotFound("resource does not exist")
            if row["attempt_id"] != attempt_id or row["fence_token"] != fence_token:
                raise InvalidTransition("resource owner or fence mismatch")
            if row["state"] in ("RELEASED", "REAPED"):
                return False
            connection.execute(
                resources.update()
                .where(resources.c.id == resource_id)
                .values(state="RELEASED", released_at=now)
            )
            return True

    def finalize_study(
        self, study_id: str, logical_job_id: str, result_sha256: str
    ) -> Study:
        with self._engine.begin() as connection:
            now = _database_now(connection)
            study_row = (
                connection.execute(
                    select(studies).where(studies.c.id == study_id).with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if study_row is None:
                raise EntityNotFound("study does not exist")

            job_row = (
                connection.execute(
                    select(logical_jobs).where(logical_jobs.c.id == logical_job_id)
                )
                .mappings()
                .one_or_none()
            )
            if job_row is None:
                raise EntityNotFound("logical job does not exist")
            if job_row["study_id"] != study_id:
                raise InvalidTransition("logical job does not belong to study")

            accepted = self._accepted_result_on_connection(connection, logical_job_id)
            if accepted is None or accepted["result_sha256"] != result_sha256:
                raise InvalidTransition(
                    "terminal outcome requires exact accepted result"
                )

            if study_row["state"] == StudyState.TERMINAL.value:
                if study_row["terminal_outcome"] != TerminalOutcome.RECOMMENDED.value:
                    raise InvalidTransition("study is terminal with another outcome")
                return self._study_on_connection(connection, study_id)
            if study_row["desired_state"] != DesiredState.RUN.value:
                raise InvalidTransition("cancelled study cannot be recommended")

            connection.execute(
                studies.update()
                .where(studies.c.id == study_id)
                .values(
                    state=StudyState.TERMINAL.value,
                    terminal_outcome=TerminalOutcome.RECOMMENDED.value,
                    updated_at=now,
                )
            )
            return self._study_on_connection(connection, study_id)

    def reap_expired_resources(self, *, limit: int) -> int:
        with self._engine.begin() as connection:
            now = _database_now(connection)
            ids = list(
                connection.scalars(
                    select(resources.c.id)
                    .where(
                        resources.c.state == "ACTIVE",
                        resources.c.expires_at < now,
                    )
                    .order_by(resources.c.expires_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            if not ids:
                return 0
            connection.execute(
                resources.update()
                .where(resources.c.id.in_(ids))
                .values(state="REAPED", released_at=now)
            )
            return len(ids)

    def finalize_cancelled_studies(self, *, limit: int) -> int:
        active_resource = exists(
            select(resources.c.id).where(
                resources.c.study_id == studies.c.id,
                resources.c.state == "ACTIVE",
            )
        )
        with self._engine.begin() as connection:
            now = _database_now(connection)
            ids = list(
                connection.scalars(
                    select(studies.c.id)
                    .where(
                        studies.c.state == StudyState.CANCELLING.value,
                        ~active_resource,
                    )
                    .order_by(studies.c.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            if not ids:
                return 0
            connection.execute(
                studies.update()
                .where(studies.c.id.in_(ids))
                .values(
                    state=StudyState.TERMINAL.value,
                    terminal_outcome=TerminalOutcome.CANCELLED.value,
                    updated_at=now,
                )
            )
            return len(ids)

    def _study_on_connection(self, connection: Connection, study_id: str) -> Study:
        row = (
            connection.execute(
                select(
                    studies.c.id.label("study_id"),
                    logical_jobs.c.id.label("logical_job_id"),
                    studies.c.idempotency_key,
                    studies.c.state,
                    studies.c.desired_state,
                    studies.c.terminal_outcome,
                    studies.c.core_release_id,
                    studies.c.plugin_release_id,
                    logical_jobs.c.operation_contract_sha256,
                    studies.c.input_ref,
                    studies.c.input_sha256,
                    workflow_projection.c.hatchet_run_id,
                    studies.c.created_at,
                    studies.c.updated_at,
                )
                .join(logical_jobs, logical_jobs.c.study_id == studies.c.id)
                .join(
                    workflow_projection,
                    workflow_projection.c.study_id == studies.c.id,
                )
                .where(studies.c.id == study_id)
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise EntityNotFound("study does not exist")
        return Study(
            study_id=row["study_id"],
            logical_job_id=row["logical_job_id"],
            idempotency_key=row["idempotency_key"],
            state=StudyState(row["state"]),
            desired_state=DesiredState(row["desired_state"]),
            terminal_outcome=(
                TerminalOutcome(row["terminal_outcome"])
                if row["terminal_outcome"] is not None
                else None
            ),
            core_release_id=row["core_release_id"],
            plugin_release_id=row["plugin_release_id"],
            operation_contract_sha256=row["operation_contract_sha256"],
            input_ref=row["input_ref"],
            input_sha256=row["input_sha256"],
            hatchet_run_id=row["hatchet_run_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _accepted_result_on_connection(connection: Connection, logical_job_id: str):
        return (
            connection.execute(
                select(accepted_results).where(
                    accepted_results.c.logical_job_id == logical_job_id
                )
            )
            .mappings()
            .one_or_none()
        )
