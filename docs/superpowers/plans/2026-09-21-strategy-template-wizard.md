# Strategy Template Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace modal strategy creation and editing with a dedicated four-step page backed by a validated, versioned strategy-template contract.

**Architecture:** Extend the existing realtime Control API strategy aggregate with one JSONB configuration document while retaining readable top-level method and derived phases for catalog rendering. Add a pure TypeScript strategy-template model for defaults, phase derivation, pruning, and validation, then build one ADQM design-system page used for both create and edit flows. HTTP mutation responses remain acknowledgements; the WebSocket event remains authoritative.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, PostgreSQL, React 18, TypeScript 5.6, `@adqm/gpb-ui`, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-21-strategy-template-wizard-design.md`

## Global Constraints

- UI copy is Russian for the current product; code identifiers and protocol fields are English.
- The page has exactly four steps: Basics, Search Configuration (Search Method and Variant Rules), Search Budget, and Scoring.
- Search phases are derived from the method and are never accepted as user-authored input.
- Workload and query generation are not part of strategy creation.
- Existing benchmarks keep their copied strategy configuration when a template is later edited.
- REST mutations return HTTP 202; browser state changes only from the WebSocket event stream.
- Use only `@adqm/gpb-ui` product controls and local assets.
- Do not commit, push, or publish; the repository forbids these actions without explicit user authorization.

## Review Focus

- A payload containing fields that do not apply to the selected method is rejected or deterministically pruned before persistence.
- Blank names and non-positive integer budgets cannot advance or create a strategy.
- Phased-only final-validation alternatives never survive when another method is selected.
- Editing a strategy used by a benchmark does not mutate the benchmark's stored configuration.
- A reconnect/bootstrap payload and a live WebSocket event expose identical strategy shapes.

---

### Task 1: Versioned Control API strategy contract

**Files:**
- Create: `docs/adr/0003-strategy-template-contract.md`
- Modify: `apps/realtime_control_api/src/realtime_control_api/main.py`
- Modify: `apps/realtime_control_api/scripts/check_strategy_crud.py`

**Interfaces:**
- Produces: `StrategyTemplateConfig`, `StrategyCreate`, `derive_phases(method)`, and the bootstrap/event strategy shape consumed by the frontend.
- Strategy response shape: `{ id, name, description, strategy, phases, config }`.

- [ ] **Step 1: Write failing contract checks**

Extend `check_strategy_crud.py` with a valid `schema_version: 1` payload and invalid cases for a caller-supplied `phases`, a zero numeric budget, and `final_validation_index_alternatives` on a non-phased method. Assert create/update/bootstrap/event round trips include the same `config` document.

- [ ] **Step 2: Run the check and verify RED**

Run: `docker compose --env-file deploy/benchmark_studio/.env -f deploy/benchmark_studio/compose.yaml exec -T control-api python /app/apps/realtime_control_api/scripts/check_strategy_crud.py`

Expected: FAIL because the API still accepts only `name`, `strategy`, and `phases`.

- [ ] **Step 3: Define the public contract and derivation**

Add literal method, scoring-priority, rule, budget, and hard-constraint Pydantic models. Define:

```python
def derive_phases(method: StrategyMethod) -> list[str]:
    return {
        'types_strategy': ['types', 'codecs'],
        'indexes_strategy': ['indexes'],
        'combined_strategy': ['types', 'codecs', 'indexes'],
        'sequential_topn_strategy': ['types', 'codecs', 'top_n', 'indexes'],
        'sequential_phased_topn_strategy': [
            'order_by', 'types', 'codecs', 'index_granularity', 'indexes',
            'final_validation',
        ],
    }[method]
```

Reject non-finite constraints, non-positive budgets, and method-inapplicable config fields. Keep all API error text free of credentials and SQL.

- [ ] **Step 4: Add the persistence migration path**

In `initialize()`, add `description text NOT NULL DEFAULT ''` and `config jsonb` to `strategies`, backfill existing rows into a valid schema-v1 default config based on their current method, set `config NOT NULL`, and keep `strategy` plus derived `phases` as readable projections. Record the contract and snapshot semantics in ADR-0003.

- [ ] **Step 5: Persist and publish one canonical shape**

Create/update must derive phases server-side, persist `payload.config`, and publish the same fields returned by bootstrap. Update uses the new template only for future benchmark copies; it must not issue benchmark updates.

- [ ] **Step 6: Rebuild the API and verify GREEN**

Run: `docker compose --env-file deploy/benchmark_studio/.env -f deploy/benchmark_studio/compose.yaml up -d --build control-api`

Run: `docker compose --env-file deploy/benchmark_studio/.env -f deploy/benchmark_studio/compose.yaml exec -T control-api python /app/apps/realtime_control_api/scripts/check_strategy_crud.py`

Expected: the CRUD, validation, bootstrap/event parity, persistence, and deletion-guard checks pass.

---

### Task 2: Pure frontend strategy-template model

**Files:**
- Create: `apps/config_editor_ui/src/strategies/model.ts`
- Create: `apps/config_editor_ui/scripts/strategy-template-check.ts`
- Modify: `apps/config_editor_ui/package.json`
- Modify: `apps/config_editor_ui/src/control/api.ts`
- Modify: `apps/config_editor_ui/src/control/workspace.tsx`

**Interfaces:**
- Consumes: Task 1 strategy response and command shapes.
- Produces: `StrategyMethod`, `StrategyTemplateConfig`, `StrategyDraft`, `createDefaultStrategyDraft()`, `deriveStrategyPhases()`, `pruneStrategyDraft()`, and `validateStrategyStep()`.

- [ ] **Step 1: Write failing model checks**

Create `strategy-template-check.ts` with real assertions for all five method pipelines, method-specific rule pruning, phased-only alternative pruning, positive integer validation, finite percentage constraints, and preservation of ordinary user-entered values.

- [ ] **Step 2: Run the check and verify RED**

Run: `npm run check:strategy-template --prefix apps/config_editor_ui`

Expected: FAIL because the script and model do not exist.

- [ ] **Step 3: Implement the minimal pure model**

Use discriminated string unions and explicit interfaces. Defaults must include a usable rule set, positive budgets, `balanced` scoring, no hard constraints, and `schemaVersion: 1`. `pruneStrategyDraft()` must return the exact API config shape and remove hidden fields rather than sending stale values.

- [ ] **Step 4: Wire the typed API boundary**

Change `Strategy` to contain `description` and `config`. Map camelCase UI fields to snake_case API JSON in `createStrategy` and `updateStrategy`; do not expose `phases` as a mutation input.

- [ ] **Step 5: Run model, type, and existing round-trip checks**

Run: `npm run check:strategy-template --prefix apps/config_editor_ui`

Run: `npm run typecheck --prefix apps/config_editor_ui`

Run: `npm run check:roundtrip --prefix apps/config_editor_ui`

Expected: all commands exit 0.

---

### Task 3: Dedicated four-step strategy page

**Files:**
- Create: `apps/config_editor_ui/src/pages/StrategyEditorPage.tsx`
- Modify: `apps/config_editor_ui/src/App.tsx`
- Modify: `apps/config_editor_ui/src/components/ProductShell.tsx`
- Modify: `apps/config_editor_ui/src/pages/RuleBanksPage.tsx`
- Modify: `apps/config_editor_ui/src/styles.css`

**Interfaces:**
- Consumes: Task 2 draft/model functions and `createStrategy`/`updateStrategy` commands.
- Produces: create and edit routes represented by `ProductPage` states and catalog callbacks.

- [ ] **Step 1: Add failing UI structure checks**

Extend `strategy-template-check.ts` to inspect `StrategyEditorPage.tsx` and require the four Russian step labels, all five method labels, final-step-only create action, no workload/query UI, no technical-ID input, and no raw scoring-expression UI.

- [ ] **Step 2: Run the check and verify RED**

Run: `npm run check:strategy-template --prefix apps/config_editor_ui`

Expected: FAIL because `StrategyEditorPage.tsx` does not exist.

- [ ] **Step 3: Add create/edit navigation**

Add `create-strategy` and `edit-strategy` page states. `Create strategy` opens the dedicated page. Edit opens the same page with the selected strategy ID. Back, Cancel, and a successful authoritative WebSocket update return to the catalog; the 202 acknowledgement alone must not insert local state.

- [ ] **Step 4: Build Basics and Search Method**

Use `TextField` and `TextArea` for name/description. Render accessible method cards as radio inputs inside product-styled cards and show the derived pipeline directly beneath the selected method.

- [ ] **Step 5: Build conditional Variant Rules**

Render only the rule groups applicable to the current method. Use supported ADQM fields and checkboxes. Do not render a rule-bank selector or preserve hidden stale rule data in the submitted document.

- [ ] **Step 6: Build Search Budget**

Render the four default positive-integer fields and an ADQM `Switch` for Advanced. Advanced exposes separate baseline/candidate row limits, per-phase limits, winners per parent, final-validation input size, and phased-only index alternatives.

- [ ] **Step 7: Build Scoring in the focused wizard**

Render four accessible priority cards and optional hard-constraint percentage fields. Use the user-approved horizontal stepper and centered form card for creation and editing. Do not render a persistent summary strip or sidebar, a Review step, or a generated JSON preview. Each step includes short guidance; rule rows explain their scope, and final-validation alternatives explain the bounded search.

- [ ] **Step 8: Enforce step ownership and submission**

Back/Next navigate without network writes. Next validates only the owning step. Create/Save appears only on Scoring, validates the complete pruned draft, sends one command, blocks double submission, and renders API failure in an `Alert`.

- [ ] **Step 9: Run frontend checks**

Run: `npm run check:strategy-template --prefix apps/config_editor_ui`

Run: `npm run check:ui-kit --prefix apps/config_editor_ui`

Run: `npm run typecheck --prefix apps/config_editor_ui`

Run: `npm run build --prefix apps/config_editor_ui`

Expected: all commands exit 0 and the UI-kit check reports no unsupported product-facing controls.

---

### Task 4: Benchmark snapshot contract

**Files:**
- Modify: `apps/realtime_control_api/src/realtime_control_api/main.py`
- Modify: `apps/realtime_control_api/scripts/check_strategy_crud.py`

**Interfaces:**
- Consumes: Task 1 canonical strategy config.
- Produces: immutable `strategy_snapshot jsonb` on every benchmark.

- [ ] **Step 1: Write the failing snapshot regression check**

Create a strategy, create a benchmark using it, update the strategy, then assert the benchmark bootstrap record retains the original `strategySnapshot` while the strategy record contains the new configuration.

- [ ] **Step 2: Run the check and verify RED**

Run: `docker compose --env-file deploy/benchmark_studio/.env -f deploy/benchmark_studio/compose.yaml exec -T control-api python /app/apps/realtime_control_api/scripts/check_strategy_crud.py`

Expected: FAIL because benchmarks currently store only `strategy_id`.

- [ ] **Step 3: Add and populate the snapshot column**

Add `strategy_snapshot jsonb` to `benchmarks`. For existing rows, backfill from the referenced strategy config. On benchmark creation, copy the selected strategy's canonical config in the same transaction. On benchmark update, refresh the snapshot only when the user explicitly saves that benchmark with its chosen strategy.

- [ ] **Step 4: Expose the snapshot and verify GREEN**

Return `strategySnapshot` in bootstrap and benchmark events, update the frontend `Benchmark` type, rebuild the API, and rerun the regression check.

Expected: strategy edits leave existing benchmark snapshots unchanged.

---

### Task 5: Integrated deployment and browser verification

**Files:**
- Modify only if verification reveals a defect in files owned by Tasks 1-4.

**Interfaces:**
- Consumes: complete API and UI implementation.
- Produces: verified local application at `http://127.0.0.1:18901/`.

- [ ] **Step 1: Run all static and contract checks**

Run: `npm run check:strategy-template --prefix apps/config_editor_ui && npm run check:ui-kit --prefix apps/config_editor_ui && npm run check:roundtrip --prefix apps/config_editor_ui && npm run typecheck --prefix apps/config_editor_ui && npm run build --prefix apps/config_editor_ui`

Run: `git diff --check`

Expected: all commands exit 0.

- [ ] **Step 2: Rebuild and recreate affected services**

Run: `docker compose --env-file deploy/benchmark_studio/.env -f deploy/benchmark_studio/compose.yaml up -d --build control-api ui`

Run: `docker compose --env-file deploy/benchmark_studio/.env -f deploy/benchmark_studio/compose.yaml ps`

Expected: PostgreSQL, ClickHouse, Control API, and UI are healthy/running.

- [ ] **Step 3: Run live API checks**

Run the strategy CRUD check inside the rebuilt container and verify `/health/ready` returns 204.

Expected: live validation, durable event, persistence, snapshot, and deletion-guard checks pass.

- [ ] **Step 4: Verify the complete browser flow**

At `http://127.0.0.1:18901/`, open Search Strategies, create a template through all four steps, confirm method-specific sections and advanced controls, save it, wait for the WebSocket-driven catalog row, reopen it for editing, save a change, and verify the catalog updates. Confirm no start button, modal editor, workload fields, technical ID, manual phases, raw scoring expression, or Review step appears.

- [ ] **Step 5: Re-read the spec and inspect the final diff**

Compare every spec section to the rendered flow and API payload. Confirm unrelated dirty files were not reverted or overwritten.
