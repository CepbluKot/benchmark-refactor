from hashlib import sha256
import json
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


Sha256 = str
ReleaseId = str


def toy_operation_contract_sha256(
    *,
    core_release_id: str,
    plugin_release_id: str,
    input_ref: str,
    input_sha256: str,
    continuation_no: int,
    deadline_profile_ref: str,
) -> str:
    canonical = json.dumps(
        {
            "schema_version": "m0.toy-operation-contract.v1",
            "operation_kind": "toy.measure",
            "core_release_id": core_release_id,
            "plugin_release_id": plugin_release_id,
            "input_ref": input_ref,
            "input_sha256": input_sha256,
            "continuation_no": continuation_no,
            "deadline_profile_ref": deadline_profile_ref,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


class ContractModel(BaseModel):
    # Hatchet decodes UUIDs from JSON strings before boundary validation.
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContentAddressedInput(ContractModel):
    input_ref: str = Field(pattern=r"^artifact://sha256/[0-9a-f]{64}$")
    input_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def require_matching_reference(self) -> Self:
        if self.input_ref != f"artifact://sha256/{self.input_sha256}":
            raise ValueError("input_ref must match input_sha256")
        return self


class StudyRunRefV1(ContentAddressedInput):
    schema_version: Literal["m0.study-run.v1"] = "m0.study-run.v1"
    command_id: UUID
    study_id: UUID
    logical_job_id: UUID
    core_release_id: ReleaseId = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    plugin_release_id: ReleaseId = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    operation_contract_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    continuation_no: int = Field(ge=0, le=10_000)
    deadline_profile_ref: Literal["m0.default"] = "m0.default"

    @model_validator(mode="after")
    def require_matching_operation_contract(self) -> Self:
        expected = toy_operation_contract_sha256(
            core_release_id=self.core_release_id,
            plugin_release_id=self.plugin_release_id,
            input_ref=self.input_ref,
            input_sha256=self.input_sha256,
            continuation_no=self.continuation_no,
            deadline_profile_ref=self.deadline_profile_ref,
        )
        if self.operation_contract_sha256 != expected:
            raise ValueError("operation contract fingerprint mismatch")
        return self


class ToyOperationRefV1(ContentAddressedInput):
    schema_version: Literal["m0.toy-operation.v1"] = "m0.toy-operation.v1"
    study_id: UUID
    logical_job_id: UUID
    operation_kind: Literal["toy.measure"] = "toy.measure"
    core_release_id: ReleaseId = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    plugin_release_id: ReleaseId = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    operation_contract_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    continuation_no: int = Field(ge=0, le=10_000)
    deadline_profile_ref: Literal["m0.default"] = "m0.default"

    @model_validator(mode="after")
    def require_matching_operation_contract(self) -> Self:
        expected = toy_operation_contract_sha256(
            core_release_id=self.core_release_id,
            plugin_release_id=self.plugin_release_id,
            input_ref=self.input_ref,
            input_sha256=self.input_sha256,
            continuation_no=self.continuation_no,
            deadline_profile_ref=self.deadline_profile_ref,
        )
        if self.operation_contract_sha256 != expected:
            raise ValueError("operation contract fingerprint mismatch")
        return self


class ToyResultRefV1(ContractModel):
    schema_version: Literal["m0.toy-result.v1"] = "m0.toy-result.v1"
    study_id: UUID
    logical_job_id: UUID
    plugin_release_id: ReleaseId = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    result_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    observation_count: int = Field(ge=1, le=1_000_000)


class FinalizeStudyRefV1(ContractModel):
    schema_version: Literal["m0.finalize-study.v1"] = "m0.finalize-study.v1"
    study_id: UUID
    logical_job_id: UUID
    result_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")


class FinalizedStudyV1(ContractModel):
    schema_version: Literal["m0.finalized-study.v1"] = "m0.finalized-study.v1"
    study_id: UUID
    outcome: Literal["RECOMMENDED"]
    result_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
