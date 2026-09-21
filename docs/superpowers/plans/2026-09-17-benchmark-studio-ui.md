# Benchmark Studio UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an offline interactive React demo for configuring ClickHouse physical-design benchmarks.

**Architecture:** Keep the existing `BenchmarkConfig` editor as the configuration engine and add a product-level demo state for workspaces, global data sources, reusable strategy templates and runs. Product pages consume this local state and never call a database or external service. The shell and controls use `@adqm/gpb-ui`; local CSS only composes the supplied components into the approved dark GPB visual treatment.

**Tech Stack:** React 18, TypeScript 5.6, Vite 5, `@adqm/gpb-ui` from the vendored tarball.

**Spec:** `docs/superpowers/specs/2026-09-17-workspaces-and-benchmarks-design.md`

## Global Constraints

- Use `@adqm/gpb-ui`, local assets and no external CDN.
- Keep this an offline, local demo; no ClickHouse calls, credential persistence or production workflow changes.
- Sources are global and workspaces only group benchmarks and runs.
- A benchmark chooses exactly one source table expressed as `database.table`.
- Benchmark creation is a separate five-step page; source creation is a compact ACM-style modal.
- Preserve the existing `BenchmarkConfig` import/export and round-trip paths.
- Do not commit, push, alter dependencies or deployment files.

---

### Task 1: Product demo model and navigation

**Files:**
- Modify: `apps/config_editor_ui/src/demo/model.ts`
- Modify: `apps/config_editor_ui/src/demo/data.ts`
- Modify: `apps/config_editor_ui/src/demo/workspace.tsx`
- Modify: `apps/config_editor_ui/src/components/ProductShell.tsx`
- Modify: `apps/config_editor_ui/src/App.tsx`

**Interfaces:**
- Produces `Workspace`, `StrategyTemplate` and workspace-aware benchmark/run selectors.
- Produces `ProductPage = 'benchmarks' | 'create-benchmark' | 'runs' | 'sources' | 'strategies'`.

- [ ] Add typed local entities and sample spaces/templates/sources/runs.
- [ ] Add workspace selection and source/template CRUD helpers to `WorkspaceProvider`.
- [ ] Replace the rule-bank navigation label with `Стратегии поиска`, add a workspace selector to the top bar, and route the benchmark creation page.
- [ ] Verify: `npm run typecheck`.

### Task 2: Benchmark list and five-step creation page

**Files:**
- Modify: `apps/config_editor_ui/src/pages/BenchmarksPage.tsx`
- Create: `apps/config_editor_ui/src/pages/CreateBenchmarkPage.tsx`
- Modify: `apps/config_editor_ui/src/components/BenchmarkEditor.tsx`

**Interfaces:**
- `CreateBenchmarkPage` accepts `onDone()` and `onCancel()`.
- It writes one `BenchmarkConfig` with `tables: { [database]: [table] }`, the chosen source and test database.

- [ ] Keep the existing detail editor for full rules, queries, limits and scoring.
- [ ] Render workspace-filtered benchmark rows with readable strategy labels, state and last run.
- [ ] Add five local form steps: basic settings, source/table, strategy, rules, workload/evaluation; use `Next`, `Back`, cancel and final create actions.
- [ ] Verify: creating a benchmark adds it only to the selected workspace and preserves one `database.table` pair.

### Task 3: Sources and strategy templates

**Files:**
- Modify: `apps/config_editor_ui/src/pages/SourcesPage.tsx`
- Modify: `apps/config_editor_ui/src/pages/RuleBanksPage.tsx`

**Interfaces:**
- `SourcesPage` creates a global `DataSource` from connection name, host, port, login and transient password.
- `RuleBanksPage` becomes the `Стратегии поиска` template catalog.

- [ ] Compose the source list from the approved mockup and open an ACM-anatomy modal for creation/editing.
- [ ] Omit a database selector; benchmark forms list available source objects as `database.table`.
- [ ] Replace rule-bank naming and summary fields with readable strategy templates and actions to use, edit and duplicate a template.
- [ ] Verify: switching workspaces never changes source rows; a new source appears in all workspace contexts.

### Task 4: Runs page and visual integration

**Files:**
- Modify: `apps/config_editor_ui/src/pages/RunsPage.tsx`
- Modify: `apps/config_editor_ui/src/styles.css`
- Modify: `apps/config_editor_ui/scripts/demo-check.ts` as necessary

**Interfaces:**
- Runs list filters through the active workspace and retains the existing detailed mock run view.

- [ ] Render the approved runs table with search/filter controls and semantic statuses.
- [ ] Keep run details and candidates for the selected mock run.
- [ ] Add dark GPB styling only around the design-system controls: blue selection/actions, green successful statuses, compact ACM-like tables and modal anatomy.
- [ ] Verify: `npm run typecheck`, `npm run check:demo`, `npm run check:roundtrip`, `npm run build`, `git diff --check`.
