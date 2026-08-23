from hatchet_sdk import Hatchet

from experiment_domain.m0 import OutboxCommand
from optimizer_sdk.m0 import FinalizedStudyV1, StudyRunRefV1, core_study_route


class HatchetGateway:
    def __init__(self, client: Hatchet) -> None:
        self._client = client

    def start_study(self, command: OutboxCommand) -> str:
        study_stub = self._client.stubs.task(
            name=core_study_route(command.core_release_id),
            input_validator=StudyRunRefV1,
            output_validator=FinalizedStudyV1,
        )
        run_ref = study_stub.run(
            StudyRunRefV1(
                command_id=command.command_id,
                study_id=command.study_id,
                logical_job_id=command.logical_job_id,
                core_release_id=command.core_release_id,
                plugin_release_id=command.plugin_release_id,
                operation_contract_sha256=command.operation_contract_sha256,
                input_ref=command.input_ref,
                input_sha256=command.input_sha256,
                continuation_no=command.continuation_no,
                deadline_profile_ref=command.deadline_profile_ref,
            ),
            wait_for_result=False,
        )
        return run_ref.workflow_run_id

    def cancel_run(self, run_id: str) -> None:
        self._client.runs.cancel(run_id)
