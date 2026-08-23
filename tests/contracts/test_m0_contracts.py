import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from benchmark_m0_control.settings import ProductSettings
from optimizer_sdk.m0 import (
    AttemptApiClient,
    AttemptApiError,
    StudyRunRefV1,
    core_finalize_route,
    core_study_route,
    toy_operation_contract_sha256,
    toy_measure_route,
)
from optimizer_sdk.m0.proto import attempt_api_pb2


def _payload() -> dict[str, object]:
    input_sha256 = "a" * 64
    return {
        "command_id": uuid4(),
        "study_id": uuid4(),
        "logical_job_id": uuid4(),
        "core_release_id": "m0-a",
        "plugin_release_id": "m0-a",
        "operation_contract_sha256": toy_operation_contract_sha256(
            core_release_id="m0-a",
            plugin_release_id="m0-a",
            input_ref=f"artifact://sha256/{input_sha256}",
            input_sha256=input_sha256,
            continuation_no=0,
            deadline_profile_ref="m0.default",
        ),
        "input_ref": f"artifact://sha256/{input_sha256}",
        "input_sha256": input_sha256,
        "continuation_no": 0,
        "deadline_profile_ref": "m0.default",
    }


def test_hatchet_payload_is_small_and_rejects_unknown_sensitive_fields() -> None:
    model = StudyRunRefV1(**_payload())
    encoded = model.model_dump_json().encode("utf-8")
    assert len(encoded) < 4096

    for field in ("password", "connection_url", "ddl", "cleanup_locator"):
        with pytest.raises(ValidationError):
            StudyRunRefV1(**_payload(), **{field: "secret"})

    unsafe_reference = _payload()
    unsafe_reference["input_ref"] = "postgresql://user:password@source/database"
    with pytest.raises(ValidationError):
        StudyRunRefV1(**unsafe_reference)

    mismatched_reference = _payload()
    mismatched_reference["input_ref"] = f"artifact://sha256/{'b' * 64}"
    with pytest.raises(ValidationError):
        StudyRunRefV1(**mismatched_reference)

    unsupported_deadline = _payload()
    unsupported_deadline["deadline_profile_ref"] = "m0.unbounded"
    with pytest.raises(ValidationError):
        StudyRunRefV1(**unsupported_deadline)


def test_release_routes_are_exact_and_invalid_release_is_rejected() -> None:
    assert core_study_route("m0-a") == "core.m0.study.m0-a.v1"
    assert core_finalize_route("m0-b") == "core.m0.finalize.m0-b.v1"
    assert toy_measure_route("m0-a") == "plugin.toy.m0-a.measure.v1"
    with pytest.raises(ValueError):
        toy_measure_route("../../latest")


def test_protobuf_request_has_no_credential_or_physical_locator_field() -> None:
    forbidden_fragments = ("password", "connection_url", "credential", "secret")
    for message in attempt_api_pb2.DESCRIPTOR.message_types_by_name.values():
        fields = {field.name for field in message.fields}
        assert not any(
            fragment in field for field in fields for fragment in forbidden_fragments
        ), message.name
    assert "schema_version" in fields


def test_operation_contract_fingerprint_changes_with_sealed_input() -> None:
    first = _payload()
    changed = toy_operation_contract_sha256(
        core_release_id="m0-a",
        plugin_release_id="m0-a",
        input_ref=f"artifact://sha256/{'b' * 64}",
        input_sha256="b" * 64,
        continuation_no=0,
        deadline_profile_ref="m0.default",
    )
    assert changed != first["operation_contract_sha256"]


def test_contract_json_round_trip_is_deterministic() -> None:
    model = StudyRunRefV1(**_payload())
    first = model.model_dump(mode="json")
    second = StudyRunRefV1.model_validate_json(json.dumps(first)).model_dump(
        mode="json"
    )
    assert second == first


def test_wire_uuid_strings_are_accepted() -> None:
    payload = _payload()
    payload["command_id"] = str(payload["command_id"])
    payload["study_id"] = str(payload["study_id"])
    payload["logical_job_id"] = str(payload["logical_job_id"])
    assert StudyRunRefV1.model_validate(payload).study_id


def test_attempt_client_fails_closed_on_unknown_response_contract() -> None:
    client = AttemptApiClient.__new__(AttemptApiClient)
    client._timeout_seconds = 1.0
    client._stub = SimpleNamespace(
        BeginAttempt=lambda request, timeout: attempt_api_pb2.BeginAttemptResponse(
            schema_version="m0.begin-attempt-response.v2",
            status=attempt_api_pb2.ATTEMPT_START_STATUS_STARTED,
            attempt_id=str(uuid4()),
            fence_token=1,
        )
    )
    request = attempt_api_pb2.BeginAttemptRequest(schema_version="m0.begin-attempt.v1")
    with pytest.raises(AttemptApiError):
        client.begin_attempt(request)


def test_release_approval_uses_compatible_pairs(monkeypatch) -> None:
    monkeypatch.setenv(
        "PRODUCT_DATABASE_URL",
        "postgresql+psycopg://app:secret@postgres/benchmark_control",
    )
    monkeypatch.setenv("M0_ALLOWED_RELEASE_PAIRS", "m0-a:m0-a,m0-b:m0-b")
    settings = ProductSettings.from_env()
    assert ("m0-a", "m0-a") in settings.allowed_release_pairs
    assert ("m0-a", "m0-b") not in settings.allowed_release_pairs

    monkeypatch.setenv("M0_ALLOWED_RELEASE_PAIRS", "m0-a")
    with pytest.raises(ValueError):
        ProductSettings.from_env()
