import json
import os
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest


BASE_URL = os.environ.get("M0_E2E_BASE_URL", "").rstrip("/")
RUN_CANCELLATION = os.environ.get("M0_E2E_RUN_CANCELLATION") == "1"


def _request(method: str, path: str, payload: dict[str, object] | None = None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{BASE_URL}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            return error.code, json.loads(body)
        except json.JSONDecodeError:
            return error.code, {"raw_response": body}


@pytest.mark.skipif(not BASE_URL, reason="M0_E2E_BASE_URL is not configured")
def test_real_hatchet_toy_full_path_and_submission_idempotency() -> None:
    payload = {
        "idempotency_key": f"e2e-{uuid4()}",
        "core_release_id": "m0-a",
        "plugin_release_id": "m0-a",
        "input_ref": f"artifact://sha256/{'e' * 64}",
        "input_sha256": "e" * 64,
        "deadline_profile_ref": "m0.default",
    }
    status, submitted = _request("POST", "/v1/studies", payload)
    assert status == 202

    repeated_status, repeated = _request("POST", "/v1/studies", payload)
    assert repeated_status == 202
    assert repeated["study_id"] == submitted["study_id"]

    conflicting = {
        **payload,
        "input_ref": f"artifact://sha256/{'f' * 64}",
        "input_sha256": "f" * 64,
    }
    conflict_status, conflict = _request("POST", "/v1/studies", conflicting)
    assert conflict_status == 409
    assert conflict == {"error_code": "IDEMPOTENCY_CONFLICT"}

    deadline = time.monotonic() + float(os.environ.get("M0_E2E_TIMEOUT", "120"))
    current = submitted
    while time.monotonic() < deadline:
        current_status, current = _request(
            "GET", f"/v1/studies/{submitted['study_id']}"
        )
        assert current_status == 200
        if current["state"] == "TERMINAL":
            break
        time.sleep(0.5)

    assert current["state"] == "TERMINAL"
    assert current["terminal_outcome"] == "RECOMMENDED"
    assert current["hatchet_run_id"]


@pytest.mark.skipif(not BASE_URL, reason="M0_E2E_BASE_URL is not configured")
@pytest.mark.skipif(
    not RUN_CANCELLATION,
    reason="M0_E2E_RUN_CANCELLATION is not enabled",
)
def test_real_hatchet_cancellation_while_plugin_child_is_waiting() -> None:
    payload = {
        "idempotency_key": f"e2e-cancel-{uuid4()}",
        "core_release_id": "m0-a",
        "plugin_release_id": "m0-a",
        "input_ref": f"artifact://sha256/{'c' * 64}",
        "input_sha256": "c" * 64,
        "deadline_profile_ref": "m0.default",
    }
    status, submitted = _request("POST", "/v1/studies", payload)
    assert status == 202

    deadline = time.monotonic() + float(os.environ.get("M0_E2E_TIMEOUT", "120"))
    current = submitted
    while time.monotonic() < deadline:
        current_status, current = _request(
            "GET", f"/v1/studies/{submitted['study_id']}"
        )
        assert current_status == 200
        if current["state"] == "RUNNING" and current["hatchet_run_id"]:
            break
        time.sleep(0.25)
    assert current["state"] == "RUNNING"

    cancel_status, cancelling = _request(
        "POST", f"/v1/studies/{submitted['study_id']}/cancel"
    )
    assert cancel_status == 202
    assert cancelling["desired_state"] == "CANCEL"

    while time.monotonic() < deadline:
        current_status, current = _request(
            "GET", f"/v1/studies/{submitted['study_id']}"
        )
        assert current_status == 200
        if current["state"] == "TERMINAL":
            break
        time.sleep(0.25)

    assert current["state"] == "TERMINAL"
    assert current["terminal_outcome"] == "CANCELLED"
