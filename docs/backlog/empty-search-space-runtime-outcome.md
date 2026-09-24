# Empty search-space runtime outcome

## Status

Backlog requirement. Do not implement in the current local `/api/v1/runs` endpoint.

## Required behavior

When the production optimizer consumes a strategy snapshot whose search space has
no configured physical-design directions, it creates no candidate variants and
terminates with:

```text
outcome = INCONCLUSIVE
reason_code = EMPTY_SEARCH_SPACE
```

It must not report `NO_IMPROVEMENT`, because no candidate evidence was collected.
The immutable strategy snapshot, baseline evidence if the accepted experiment
contract requires it, and the reason code must remain auditable.

## Implementation gate

Implement this only in the production experiment workflow after its terminal
outcome/reason contract exists. Add deterministic engine tests, workflow retry and
replay tests, and API projection coverage in that future task.
