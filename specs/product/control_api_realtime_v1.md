# Control API realtime v1

## Scope

The browser uses a versioned FastAPI Control API. PostgreSQL is the authoritative
business-state and event store. The browser may obtain an initial snapshot via REST;
after that it changes its model only from the WebSocket event stream.

## Commands and reads

- `GET /api/v1/bootstrap` returns projections plus `event_watermark`.
- `POST /api/v1/...` commands require an idempotency key and return only
  `202 Accepted` with `command_id`, `aggregate_id`, and `accepted_event_id`.
- A command response is never a state update. The browser waits for its matching
  event before showing an authoritative transition.
- Polling and Server-Sent Events are forbidden.

## WebSocket contract

`GET /api/v1/events?after=<event_id>` upgrades to WebSocket. The server replays
persisted events strictly after `after`, then follows the durable event log.

Each event has this envelope:

```json
{
  "schema_version": 1,
  "event_id": 42,
  "aggregate_type": "study",
  "aggregate_id": "...",
  "aggregate_revision": 3,
  "event_type": "study.stage_changed",
  "occurred_at": "2026-09-18T00:00:00Z",
  "command_id": "...",
  "payload": {}
}
```

Delivery is at least once. Clients deduplicate by `event_id`; reconnects repeat
the last durable cursor. If retention no longer covers a requested cursor, the
server sends `resync_required`; the client repeats `GET /api/v1/bootstrap` and
reconnects from its returned watermark.

## Safety

Source credentials, raw connection URLs, SQL, DDL, secret values, and cleanup
locators never appear in REST payloads, event payloads, logs, or browser state.
The API stores secret references only. Source access is read-only. Sandbox writes
and cleanup use an isolated identity and may never fall back to the source.

## Runtime evidence

Every visible run state is emitted from an executed physical path. Fake candidates,
timer-driven completion, fixture-only result data, and mocked I/O are forbidden.
The first ClickHouse slice performs a real capability check, creates resources only
in its sandbox, records a baseline and candidate observation, and verifies the
source was not modified.
