# Empty Strategy Search Space Handoff

## 1. Purpose and status

This document is the product and boundary-contract source of truth for strategy
templates whose search space contains no configured optimization directions.

It supersedes the requirement in section 13 of
`strategy-editor-page-handoff.md` that at least one effective optimization rule
must exist. It does not supersede validation of rules that the user has actually
added.

The accepted product decision is:

- a strategy template may contain zero configured search directions;
- an entirely empty search space is valid and may be saved;
- a partially configured rule remains invalid;
- the UI must explain that an empty search space creates no candidate variants;
- empty search must not be represented as evidence that no improvement exists.

## 2. Current implementation evidence

The frontend default draft contains empty arrays and an empty `order_by` document.
`validateDimensions()` accepts that entirely empty document, while retaining strict
validation for every rule that is present. The Control API accepts and persists the
same document. Its projection emits an empty phase list for an empty search space,
including Sequential and Phased procedure values, so it never reports synthetic-only
`top_n` or `final_validation` phases.

The current local `/api/v1/runs` endpoint does not consume the selected strategy
configuration. Therefore this change can prove editing, validation, persistence,
event/bootstrap round trips, and phase projection. It cannot prove optimizer
execution or a terminal scientific outcome.

## 3. Exact definition of an empty search space

`StrategySearchSpace` is empty only when all of the following are empty:

- `column_types`;
- `codecs`;
- `skip_indexes`;
- `order_by.candidates`;
- `column_order`;
- `table_index_granularity_values`.

`order_by.first_column` alone does not create a search direction. It is only a
selector or hint for actual ORDER BY candidates.

Use one frontend helper as the canonical UI predicate:

```ts
export function hasSearchDimensions(value: SearchDimensions): boolean {
  return Boolean(
    value.column_types.length
    || value.codecs.length
    || value.skip_indexes.length
    || value.order_by.candidates.length
    || value.column_order.length
    || value.table_index_granularity_values.length
  );
}
```

The backend may use the equivalent Python predicate locally inside validation or
projection code. Do not add a database column, persisted flag, or new wire field.

## 4. Validation contract

### 4.1 Valid empty document

The following v2 search space is valid:

```json
{
  "column_types": [],
  "codecs": [],
  "skip_indexes": [],
  "order_by": {"candidates": []},
  "column_order": [],
  "table_index_granularity_values": []
}
```

It must pass frontend validation, Control API validation, create/update
persistence, authoritative event delivery, and bootstrap round trip unchanged.

### 4.2 Invalid partial documents

Allowing the whole search space to be empty must not make incomplete objects valid.
If the user adds an object, that object must be complete:

- type or codec rule: nonblank `by_type` and at least one nonblank unique
  alternative;
- skip-index rule: nonblank `by_type` and at least one index with a nonblank type
  and a positive integer granularity;
- ORDER BY candidate: nonblank and unique;
- column-order row: nonblank column name, positive integer position, unique name,
  and unique position;
- table granularity: positive integer and unique.

An incomplete rule blocks step progression and save with the existing field or
step-level error. Never silently delete an incomplete rule during serialization.

## 5. Frontend behavior

When `hasSearchDimensions(draft.dimensions)` is false, replace the current blocking
red error with a nonblocking ADQM warning Alert.

Exact copy:

- RU title: `Направления поиска не настроены`
- RU body: `Стратегию можно сохранить, но при запуске новые варианты создаваться не будут.`
- EN title: `No search dimensions configured`
- EN body: `You can save the strategy, but no candidate variants will be created when it runs.`

Use `tone="warning"`. The warning must not set `errors.dimensions`, disable Continue,
or disable Save. Keep icon, title, and text so color is not the only signal.

Do not add a default rule, hidden candidate, preset, or automatic alternative.
Removing the last configured rule must return the editor to this valid warning state.

If any rule exists but is incomplete, show the existing blocking validation error
instead of the empty-state warning. A document is either entirely empty or contains
configured objects; an incomplete object is not treated as empty.

## 6. Phase projection

For an empty search space, the frontend `dimensionPhases()` and backend
`strategy_projection()` must both return an empty phase list for every persisted
procedure:

```text
combined   -> []
sequential -> []
phased     -> []
```

For a nonempty search space, preserve existing behavior:

- configured physical directions appear in their current deterministic order;
- Sequential appends `top_n` after the configured directions;
- Phased appends `final_validation` after the configured directions.

Do not expose Phased Top-N again in the product UI. Its empty projection is covered
only for compatibility with already persisted documents.

## 7. API and persistence behavior

The v2 wire schema shape does not change. Remove only the nonempty-space rejection
from `StrategySearchSpace.valid_search_space()`.

Keep all nested field validators, maximum lengths, duplicate checks, and positive
integer checks unchanged.

POST and PUT must accept the valid empty document. PostgreSQL, strategy events, and
bootstrap must preserve the exact empty arrays and `order_by` document. Do not omit
keys, inject defaults, or upgrade/downgrade the schema version.

Schema v1 behavior is outside this change. Existing stored strategies and immutable
benchmark snapshots must not be rewritten.

## 8. Future runtime semantics

When a real optimizer runtime begins consuming the strategy snapshot, an empty search
space produces no candidate variants. It must not report `NO_IMPROVEMENT`, because no
candidate evidence was collected.

The required future terminal result is:

```text
outcome = INCONCLUSIVE
reason_code = EMPTY_SEARCH_SPACE
```

This handoff does not authorize implementing that runtime path inside the legacy run
endpoint or inventing a fake completion. Record it as a requirements/backlog item if
the production optimizer does not yet expose the outcome/reason contract.

## 9. Non-goals

This change does not:

- execute the optimizer from the current local run endpoint;
- create a baseline-only benchmark mode;
- add a new strategy procedure;
- change budgets, scoring, autocomplete, or available alternatives;
- auto-populate any search direction;
- relax validation inside a rule that exists;
- migrate or rewrite stored strategy documents;
- re-enable Phased Top-N in the UI.

## 10. Acceptance criteria

1. A new strategy with all six search directions empty can advance, save, and round
   trip through events/bootstrap.
2. The empty editor shows the exact RU/EN nonblocking warning and no red validation
   error.
3. Adding an incomplete type, codec, or index rule still blocks progression.
4. Invalid ORDER BY, column-order, and table-granularity values remain rejected.
5. Removing the final complete rule returns to a valid empty warning state.
6. Empty Combined, Sequential, and persisted Phased strategies project `phases=[]`.
7. Nonempty phase ordering remains unchanged.
8. No wire-field, database-schema, or stored-document migration is introduced.
9. The UI continues to use `@adqm/gpb-ui` controls and RU/EN localization.
10. Frontend checks, backend contract checks, typecheck, production build, and
    `git diff --check` pass.
