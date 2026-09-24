# Empty Strategy Search Space Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow schema-v2 strategy templates with zero configured search directions while keeping every added rule strict, showing a clear nonblocking warning, and projecting no fake Top-N/final-validation phase.

**Architecture:** Keep the existing v2 document shape and change only validation and derived projection behavior. The frontend owns draft validation and warning presentation; the Control API owns boundary validation, persistence, and authoritative phase projection. The current run endpoint remains untouched because it does not execute strategy search.

**Tech Stack:** React 18, TypeScript 5.6, `@adqm/gpb-ui`, Python 3.12, FastAPI, Pydantic v2, PostgreSQL, Docker Compose.

**Spec:** `specs/product/strategy-empty-search-space-handoff.md`

## Global Constraints

- Read `AGENTS.md`, `docs/AI_EXECUTION_WORKFLOW.md`, the spec above, and the current dirty diff before editing.
- Preserve all unrelated and pre-existing uncommitted work. Do not revert or rewrite it.
- Do not commit, push, tag, or publish unless the user explicitly requests that action in the execution task.
- Maintained backend code remains Python `>=3.12,<3.13`; frontend code remains React/TypeScript and uses `@adqm/gpb-ui` product controls.
- All locally built images use the literal mutable tag `:local`; never introduce `:latest`, commit tags, or public runtime assets.
- The v2 wire document stays unchanged. Do not add an `is_empty`, `baseline_only`, or similar persisted field.
- Empty search is valid; a rule that exists but is incomplete remains invalid.
- Empty Combined, Sequential, and persisted Phased documents all derive `phases=[]`.
- Do not modify `/api/v1/runs` or claim the current local run endpoint executes the strategy.
- Future runtime behavior is `INCONCLUSIVE` with reason `EMPTY_SEARCH_SPACE`; document it only unless a separate runtime task exists.
- All user-facing copy must be present in Russian and English.

## Review Focus

- Entirely empty document: accepts and round trips unchanged instead of failing with “at least one dimension”.
- Partial rule: an empty search space does not accidentally legitimize a present rule with missing source type or alternatives.
- Sequential empty document: derives `[]`, not a standalone `['top_n']` phase.
- Persisted Phased empty document: derives `[]` without re-exposing Phased in the editor.
- Removing the last rule: immediately switches from blocking rule validation to the nonblocking empty-state warning.

---

### Task 1: Pin the Control API empty-space contract

**Files:**
- Create: `apps/realtime_control_api/scripts/check_empty_search_space_contract.py`
- Modify: `apps/realtime_control_api/src/realtime_control_api/main.py`

**Interfaces:**
- Consumes: `StrategyTemplateConfigV2`, `StrategyAlternativeRule`, and `strategy_projection()` from `realtime_control_api.main`.
- Produces: Pydantic acceptance of the existing empty v2 document and `strategy_projection(config) -> (method, [])` for every procedure when no physical direction exists.

- [ ] **Step 1: Create the failing model-level contract check**

Create the file with this complete content:

```python
from copy import deepcopy

from pydantic import ValidationError

from realtime_control_api.main import StrategyTemplateConfigV2, strategy_projection


BASE_CONFIG = {
    'schema_version': 2,
    'procedure': 'combined',
    'search_space': {
        'column_types': [],
        'codecs': [],
        'skip_indexes': [],
        'order_by': {'candidates': []},
        'column_order': [],
        'table_index_granularity_values': [],
    },
    'budget': {
        'rows_per_insert': 100000,
        'insert_repetitions': 3,
        'max_candidates': 100,
        'top_n': 10,
    },
    'scoring': {
        'preset': 'balanced',
        'formula': 'read_gain',
        'direction': 'maximize',
    },
}


for procedure in ('combined', 'sequential', 'phased'):
    raw = deepcopy(BASE_CONFIG)
    raw['procedure'] = procedure
    config = StrategyTemplateConfigV2.model_validate(raw)
    _, phases = strategy_projection(config)
    assert phases == [], (procedure, phases)

invalid = deepcopy(BASE_CONFIG)
invalid['search_space']['column_types'] = [
    {'by_type': 'String', 'alternatives': []},
]
try:
    StrategyTemplateConfigV2.model_validate(invalid)
except ValidationError:
    pass
else:
    raise AssertionError('A present type rule without alternatives must remain invalid')

print('Empty strategy search-space model contract passed')
```

- [ ] **Step 2: Run the contract check and verify the expected failure**

Run from the repository root:

```bash
docker run --rm \
  --entrypoint python \
  -e PYTHONPATH=/app/apps/realtime_control_api/src \
  -v "$PWD/apps/realtime_control_api:/app/apps/realtime_control_api:ro" \
  benchmark-studio-control:local \
  /app/apps/realtime_control_api/scripts/check_empty_search_space_contract.py
```

Expected before implementation: FAIL with Pydantic validation text containing
`At least one search dimension is required`.

- [ ] **Step 3: Remove only the backend nonempty-space rejection**

In `StrategySearchSpace.valid_search_space()`, delete this exact branch:

```python
if not any((self.column_types, self.codecs, self.skip_indexes, self.order_by.candidates, self.column_order, self.table_index_granularity_values)):
    raise ValueError('At least one search dimension is required')
```

Keep the table-granularity, column-name, position, nested-rule, length, and duplicate
validation unchanged.

- [ ] **Step 4: Prevent synthetic phases for an empty search space**

In `strategy_projection()`, build the physical `phases` list exactly as today, then
append procedure phases only when that list is nonempty:

```python
if phases and config.procedure == 'sequential':
    phases.append('top_n')
if phases and config.procedure == 'phased':
    phases.append('final_validation')
```

Do not change the schema-v1 `derive_phases()` mapping.

- [ ] **Step 5: Run the focused backend contract check**

Run the same `docker run` command from Step 2.

Expected: PASS and the final line
`Empty strategy search-space model contract passed`.

- [ ] **Step 6: Inspect the diff before continuing**

Run:

```bash
git diff -- apps/realtime_control_api/src/realtime_control_api/main.py \
  apps/realtime_control_api/scripts/check_empty_search_space_contract.py
```

Confirm that nested validators remain present and `/api/v1/runs` is untouched.

Do not commit unless the user explicitly authorized commits.

---

### Task 2: Make empty frontend validation valid without weakening rules

**Files:**
- Modify: `apps/config_editor_ui/src/strategies/dimensions.ts`
- Modify: `apps/config_editor_ui/scripts/strategy-template-check.ts`

**Interfaces:**
- Consumes: `SearchDimensions` and the existing validation-message object.
- Produces: `hasSearchDimensions(value: SearchDimensions): boolean`, empty-aware `validateDimensions()`, and empty-aware `dimensionPhases()`.

- [ ] **Step 1: Change the frontend contract assertions first**

In `strategy-template-check.ts`, replace the assertion expecting
`Настройте хотя бы одно направление оптимизации.` with:

```ts
assert.equal(validateDimensions(draft.dimensions), undefined);
assert.deepEqual(dimensionPhases(draft.dimensions, 'combined'), []);
assert.deepEqual(dimensionPhases(draft.dimensions, 'sequential'), []);
assert.deepEqual(dimensionPhases(draft.dimensions, 'phased'), []);
```

Add these assertions so partial rules remain invalid:

```ts
assert.equal(
  validateDimensions({
    ...draft.dimensions,
    column_types: [{ by_type: 'String', alternatives: [] }],
  }),
  'Для каждого правила задайте исходный тип и хотя бы одну альтернативу.',
);
assert.equal(
  validateDimensions({
    ...draft.dimensions,
    skip_indexes: [{ by_type: 'String', indexes: [] }],
  }),
  'Для индекса задайте исходный тип, тип индекса и целую гранулярность больше нуля.',
);
```

- [ ] **Step 2: Run the frontend check and verify the expected failure**

Run:

```bash
cd apps/config_editor_ui
npm run check:strategy-template
```

Expected before implementation: FAIL because empty validation still returns the
old required-dimension message.

- [ ] **Step 3: Add one canonical frontend emptiness predicate**

In `dimensions.ts`, add:

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

Do not count `order_by.first_column` by itself.

- [ ] **Step 4: Remove only the whole-document required validation**

Delete `required` from `DimensionValidationMessages` and its default object. Delete
the final `if (...) return messages.required` branch from `validateDimensions()`.

Keep every loop and all validation branches for rules that exist.

- [ ] **Step 5: Make phase derivation empty-aware**

After constructing the physical `phases` array in `dimensionPhases()`, return early
when it is empty:

```ts
if (!phases.length) return [];
return [
  ...phases,
  ...(procedure === 'sequential'
    ? ['top_n']
    : procedure === 'phased'
      ? ['final_validation']
      : []),
];
```

Do not change ordering for a nonempty document.

- [ ] **Step 6: Run the focused frontend check**

Run:

```bash
cd apps/config_editor_ui
npm run check:strategy-template
```

Expected: PASS with `Strategy template model checks passed`.

Do not commit unless the user explicitly authorized commits.

---

### Task 3: Replace the blocking error with a nonblocking warning

**Files:**
- Create: `apps/config_editor_ui/scripts/strategy-empty-search-space-check.ts`
- Modify: `apps/config_editor_ui/package.json`
- Modify: `apps/config_editor_ui/src/pages/StrategyEditorPage.tsx`

**Interfaces:**
- Consumes: `hasSearchDimensions()` from Task 2 and the existing ADQM `Alert`.
- Produces: exact RU/EN warning copy that never enters the `errors` object and does not block Continue or Save.

- [ ] **Step 1: Create a failing source contract check**

Create `strategy-empty-search-space-check.ts` with:

```ts
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const page = readFileSync(
  resolve(process.cwd(), 'src/pages/StrategyEditorPage.tsx'),
  'utf8',
);

assert.match(page, /hasSearchDimensions/);
assert.match(page, /Направления поиска не настроены/);
assert.match(page, /Стратегию можно сохранить, но при запуске новые варианты создаваться не будут\./);
assert.match(page, /No search dimensions configured/);
assert.match(page, /no candidate variants will be created when it runs\./);
assert.match(page, /tone="warning"/);
assert.doesNotMatch(page, /Настройте хотя бы одно направление оптимизации/);
assert.doesNotMatch(page, /Configure at least one optimization dimension/);

console.log('Empty strategy search-space UI checks passed');
```

- [ ] **Step 2: Register and run the check to prove it fails**

Add this package script:

```json
"check:strategy-empty-search-space": "esbuild scripts/strategy-empty-search-space-check.ts --bundle --platform=node --format=esm --outfile=node_modules/.cache/strategy-empty-search-space-check.mjs && node node_modules/.cache/strategy-empty-search-space-check.mjs"
```

Run:

```bash
cd apps/config_editor_ui
npm run check:strategy-empty-search-space
```

Expected before implementation: FAIL because the exact warning copy is absent.

- [ ] **Step 3: Remove the obsolete required-message argument**

Import `hasSearchDimensions` from `../strategies/dimensions` alongside the existing
imports. In the `validateDimensions()` message object, remove only:

```ts
required: t(
  'Настройте хотя бы одно направление оптимизации.',
  'Configure at least one optimization dimension.',
),
```

Do not remove the messages for incomplete rules, invalid indexes, invalid
granularity, or duplicate column-order values.

- [ ] **Step 4: Render the exact warning only for an entirely empty document**

In step 2 (`step === 1`), after the explanatory text and before the existing
`StrategyDimensionsEditor` element, render:

```tsx
{!hasSearchDimensions(draft.dimensions) ? (
  <Alert
    tone="warning"
    title={t(
      'Направления поиска не настроены',
      'No search dimensions configured',
    )}
  >
    {t(
      'Стратегию можно сохранить, но при запуске новые варианты создаваться не будут.',
      'You can save the strategy, but no candidate variants will be created when it runs.',
    )}
  </Alert>
) : null}
```

Do not write this warning into `errors`. Do not disable the stepper, Continue, or
Save. Keep the existing red Alert for `errors.dimensions`; it is still required for
partial invalid rules.

- [ ] **Step 5: Run focused UI and localization checks**

Run:

```bash
cd apps/config_editor_ui
npm run check:strategy-empty-search-space
npm run check:strategy-template
npm run check:i18n
npm run check:ui-kit
npm run typecheck
```

Expected: every command exits 0.

Do not commit unless the user explicitly authorized commits.

---

### Task 4: Prove Control API persistence and preserve strict nested validation

**Files:**
- Modify: `apps/realtime_control_api/scripts/check_strategy_v2_and_options.py`

**Interfaces:**
- Consumes: live POST/DELETE strategy endpoints, bootstrap, and the Task 1 boundary model.
- Produces: disposable live proof that an empty v2 document persists unchanged with `phases=[]`, while an incomplete rule still returns HTTP 422.

- [ ] **Step 1: Generalize cleanup before adding a second created strategy**

Replace `created = None` with:

```python
created_ids: list[str] = []
```

Whenever a strategy is created, append its ID. Replace the final cleanup with:

```python
finally:
    for strategy_id in created_ids:
        request('/api/v1/strategies/' + strategy_id, {}, 'DELETE')
```

- [ ] **Step 2: Add an empty persistence case**

After the existing nonempty v2 round-trip assertions, add:

```python
empty_config = {
    **config,
    'procedure': 'combined',
    'search_space': {
        'column_types': [],
        'codecs': [],
        'skip_indexes': [],
        'order_by': {'candidates': []},
        'column_order': [],
        'table_index_granularity_values': [],
    },
}
empty_body = {
    'name': f'Empty v2 strategy {uuid4()}',
    'description': 'empty search-space API check',
    'config': empty_config,
}
empty_id = request('/api/v1/strategies', empty_body, 'POST')['aggregate_id']
created_ids.append(empty_id)
empty_persisted = next(
    item for item in request('/api/v1/bootstrap')['strategies']
    if item['id'] == empty_id
)
assert empty_persisted['config'] == empty_config
assert empty_persisted['phases'] == []
```

Keep the existing HTTP 422 assertion for a present type rule with an empty
`alternatives` list. Do not weaken or delete it.

- [ ] **Step 3: Rebuild the backend image using the required local tag**

Run from the repository root:

```bash
docker build \
  -f apps/realtime_control_api/Dockerfile \
  -t benchmark-studio-control:local \
  .
```

Expected: build succeeds without pulling a replacement application image and the
resulting application image is tagged exactly `benchmark-studio-control:local`.

- [ ] **Step 4: Run the model-level check against the rebuilt image**

Run the Task 1 `docker run` command again.

Expected: PASS.

- [ ] **Step 5: Run the live persistence check only when local deployment is authorized and fully configured**

Do not recreate Control API with invented or placeholder credentials. The env files
currently present in this checkout were observed to be incomplete for a Control API
recreation. Unless the execution context provides an already verified complete
Benchmark Studio Compose environment, report this live deployment check as not run.
Do not reconstruct, print, or copy secrets from the running container merely to make
this optional check pass.

When a complete approved environment is explicitly available, use that environment's
canonical deployment command to recreate only `control-api`, wait for its readiness
healthcheck, and run the host-side standard-library check:

```bash
python3.12 apps/realtime_control_api/scripts/check_strategy_v2_and_options.py
```

Expected live result: `V2 strategy persistence and options contract passed` and no
disposable test strategies left behind. If the host command fails before contacting
the API because `python3.12` is unavailable, use the repository's configured Python
3.12 runtime; do not substitute another Python minor.

Do not commit unless the user explicitly authorized commits.

---

### Task 5: Synchronize superseded documentation and record future runtime work

**Files:**
- Modify: `specs/product/strategy-editor-page-handoff.md`
- Create: `docs/backlog/empty-search-space-runtime-outcome.md`

**Interfaces:**
- Consumes: accepted contract in `specs/product/strategy-empty-search-space-handoff.md`.
- Produces: no contradictory “at least one rule” requirement and an explicit future runtime requirement without modifying the current fake/local run path.

- [ ] **Step 1: Replace the superseded validation statement**

In section 13 of `strategy-editor-page-handoff.md`, replace the sentence requiring at
least one effective optimization rule with a short pointer:

```markdown
- An entirely empty search space is valid. A rule that exists must still be
  complete. The warning, API, and phase-projection contract is defined in
  [Empty Strategy Search Space Handoff](strategy-empty-search-space-handoff.md).
```

Also update any acceptance/test bullet that says empty effective search space must
be rejected. It must instead require a valid empty round trip and continued
rejection of incomplete nested rules.

- [ ] **Step 2: Record the deferred runtime outcome**

Create `docs/backlog/empty-search-space-runtime-outcome.md` with:

````markdown
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
````

- [ ] **Step 3: Validate documentation**

Run from the repository root:

```bash
rg -n "At least one search dimension is required|Настройте хотя бы одно направление оптимизации|Configure at least one optimization dimension" \
  specs/product docs apps/config_editor_ui/src apps/realtime_control_api/src
git diff --check
```

Expected: no active product/UI/API requirement still mandates a nonempty search
space. Historical implementation plans may retain old text only when explicitly
marked superseded.

Do not commit unless the user explicitly authorized commits.

---

### Task 6: Run the complete verification gate and optionally deploy the UI

**Files:**
- Verify only; do not add unrelated source changes.

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: fresh evidence that the focused contract, frontend suite, build, docs,
  and optional authorized live application agree.

- [ ] **Step 1: Run the backend model contract**

Run the Task 1 `docker run` command against `benchmark-studio-control:local`.

Expected: PASS.

- [ ] **Step 2: Run the complete frontend gate**

Run:

```bash
cd apps/config_editor_ui
npm run check:ui-kit
npm run check:strategy-options
npm run check:strategy-template
npm run check:strategy-empty-search-space
npm run check:strategy-budget-layout
npm run check:alternative-focus
npm run check:source-type-autocomplete
npm run check:navigation-state
npm run check:i18n
npm run typecheck
npm run build
```

Expected: every command exits 0. The existing Vite `runtime-config.js` non-module
warning may remain if it is unchanged; no new warning is acceptable.

- [ ] **Step 3: Run repository hygiene checks**

Run from the repository root:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors. Review `git status` and distinguish this task's
files from pre-existing user changes.

- [ ] **Step 4: Rebuild and deploy the UI only when deployment is authorized**

Build with the required tag:

```bash
docker build \
  -f apps/config_editor_ui/Dockerfile \
  -t benchmark-studio-ui:local \
  .
```

Recreate only the UI service. Compose validates unrelated required variables even
with `--no-deps`; these non-secret values are validation-only and are acceptable here
because the Control API is not recreated:

```bash
env \
  CONTROL_DB_PASSWORD=validation-only \
  CLICKHOUSE_SOURCE_HOST=validation-only \
  CLICKHOUSE_SOURCE_PORT=1 \
  CLICKHOUSE_SOURCE_USER=validation-only \
  CLICKHOUSE_SANDBOX_USER=validation-only \
  docker compose \
    -f deploy/benchmark_studio/compose.yaml \
    up -d --no-deps --force-recreate ui
```

Never use validation placeholders when recreating Control API.

Verify:

```bash
curl --fail --retry 8 --retry-connrefused --retry-delay 1 \
  --silent --show-error http://127.0.0.1:18901/ >/dev/null
docker ps --filter name=benchmark-studio-ui \
  --format '{{.Names}} {{.Image}} {{.Status}}'
```

Expected: HTTP request succeeds and the UI uses `benchmark-studio-ui:local`.

- [ ] **Step 5: Perform live browser acceptance when deployment is authorized**

Verify all of the following without saving unrelated edits:

1. Create a new strategy and open `Настройки поиска`.
2. Confirm all directions can remain empty.
3. Confirm the yellow warning uses the exact Russian copy and Continue is enabled.
4. Switch to English and confirm the exact English copy.
5. Add an incomplete type rule and confirm progression is blocked by the existing
   red error.
6. Remove that rule and confirm the red error disappears and the warning returns.
7. Select Sequential and confirm the empty document remains valid.
8. Save only if the acceptance run is allowed to create a disposable strategy;
   otherwise cancel and rely on the live API script for persistence proof.

- [ ] **Step 6: Report the outcome without overclaiming**

Report:

- changed files and contract behavior;
- focused and full checks actually run;
- whether live Control API persistence was run;
- whether UI deployment/browser acceptance was run;
- unchanged nested validation;
- no database migration;
- deferred production runtime outcome requirement;
- any checks skipped and the exact reason.

Do not claim the optimizer executes empty strategies. Do not commit or push unless
the user separately requests it.
