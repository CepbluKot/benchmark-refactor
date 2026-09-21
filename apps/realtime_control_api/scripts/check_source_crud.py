"""Run source CRUD verification against the local Control API and PostgreSQL."""

import json
import urllib.error
import urllib.request
from uuid import uuid4

import websocket


BASE = "http://127.0.0.1:18900"


def request(path: str, body: dict[str, object] | None = None, method: str = "GET") -> dict[str, object]:
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(
        urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    ) as response:
        return json.load(response)


snapshot = request("/api/v1/bootstrap")
socket = websocket.create_connection(f"ws://127.0.0.1:18900/api/v1/events?after={snapshot['event_watermark']}", timeout=5)


def event_payload(ack: dict[str, object], event_type: str) -> dict[str, object]:
    while True:
        event = json.loads(socket.recv())
        if event["event_id"] == ack["accepted_event_id"]:
            assert event["event_type"] == event_type
            return event["payload"]


source_id: str | None = None
try:
    source = {
        "name": f"CRUD validation {uuid4()}",
        "host": "clickhouse",
        "port": 8123,
        "login": "benchmark_reader",
        "secret_ref": "secret://validation/source-reader",
    }
    ack = request("/api/v1/sources", source, "POST")
    source_id = str(ack["aggregate_id"])
    assert event_payload(ack, "source.created")["name"] == source["name"]

    source["name"] += " updated"
    ack = request(f"/api/v1/sources/{source_id}", source, "PUT")
    assert event_payload(ack, "source.updated")["name"] == source["name"]
    assert next(item for item in request("/api/v1/bootstrap")["sources"] if item["id"] == source_id)["name"] == source["name"]

    ack = request(f"/api/v1/sources/{source_id}", {}, "DELETE")
    event_payload(ack, "source.deleted")
    assert all(item["id"] != source_id for item in request("/api/v1/bootstrap")["sources"])
    source_id = None

    for benchmark in snapshot["benchmarks"]:
        try:
            request(f"/api/v1/sources/{benchmark['sourceId']}", {}, "DELETE")
            raise AssertionError("Referenced source deletion was accepted")
        except urllib.error.HTTPError as error:
            assert error.code == 409
    print("Source CRUD, durable events, persistence and deletion guard passed")
finally:
    if source_id:
        request(f"/api/v1/sources/{source_id}", {}, "DELETE")
    socket.close()
