# Strategy Search Budget Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign strategy step 3 so INSERT-test data and candidate/Top-N search limits are visibly separate, understandable, and free of Advanced budget controls.

**Architecture:** Extract the budget UI from the already-large strategy page into one focused `StrategyBudgetEditor` component. Keep the current versioned API and draft serializer unchanged so old optional advanced values remain compatible, while the product UI renders only the four primary controls with procedure-specific explanations.

**Tech Stack:** React 18, TypeScript 5.6, `@adqm/gpb-ui`, local ADQM theme tokens, Vite.

**Spec:** `specs/product/strategy-search-budget-handoff.md`

## Global Constraints

- Use only `@adqm/gpb-ui` product controls and existing local `MaterialIcon` assets.
- User-facing text is bilingual through `t(ru, en)`; identifiers and protocol fields remain English.
- Do not change `StrategyBudgetConfig`, Control API payloads, persistence, or runtime behavior.
- Preserve old optional advanced values during an existing-strategy round trip; new strategies continue omitting them.
- Do not render the Advanced switch, its six fields, presets, duration estimates, or Phased Top-N.
- Combined hides Top-N and explains joint comparison; Sequential shows Top-N and explains winner propagation.
- Preserve all unrelated dirty worktree changes.
- Do not commit, push, or deploy unless the user explicitly requests those actions.

## Review Focus

- An old schema-v2 strategy containing advanced budget keys must retain those keys after save even though the controls are hidden.
- A newly created strategy must not acquire hidden optional budget keys.
- Combined must not display an editable Top-N field or imply that intermediate pruning occurs.
- Sequential must display Top-N, validate it, and explain that winners continue after each direction.
- Long Russian/English helper text, field errors, dark theme, and a 320 px viewport must not overlap or scroll horizontally.

---

### Task 1: Lock the new UI and compatibility behavior with failing checks

**Files:**
- Create: `apps/config_editor_ui/scripts/strategy-budget-layout-check.ts`
- Modify: `apps/config_editor_ui/scripts/strategy-template-check.ts`
- Modify: `apps/config_editor_ui/package.json`

**Interfaces:**
- Consumes: current `StrategyBudgetDraft`, `pruneStrategyDraft()`, and source files.
- Produces: `npm run check:strategy-budget-layout`, which prevents the Advanced UI or mixed budget layout from returning.

- [ ] **Step 1: Add the structural check script**

Create `strategy-budget-layout-check.ts` with these assertions:

```ts
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const page = readFileSync(resolve(root, 'src/pages/StrategyEditorPage.tsx'), 'utf8');
const editorPath = resolve(root, 'src/components/StrategyBudgetEditor.tsx');

assert.equal(existsSync(editorPath), true, 'StrategyBudgetEditor must exist');
const editor = readFileSync(editorPath, 'utf8');

assert.match(page, /<StrategyBudgetEditor/);
assert.doesNotMatch(page, /Расширенные настройки бюджета|Advanced budget settings/);
assert.match(page, /baselineRows: config\.budget\.baseline_rows/);
assert.match(page, /candidateRows: config\.budget\.candidate_rows/);
assert.match(page, /perPhaseCandidates: config\.budget\.per_phase_candidates/);
assert.match(page, /winnersPerParent: config\.budget\.winners_per_parent/);
assert.match(page, /finalValidationCandidates: config\.budget\.final_validation_candidates/);
assert.match(page, /finalValidationIndexAlternatives: config\.budget\.final_validation_index_alternatives/);
assert.match(editor, /Данные для INSERT-теста/);
assert.match(editor, /Ограничения поиска/);
assert.match(editor, /rowsPerInsert/);
assert.match(editor, /insertRepetitions/);
assert.match(editor, /maxCandidates/);
assert.match(editor, /procedure === 'sequential'/);
assert.match(editor, /topN/);
assert.doesNotMatch(editor, /baselineRows|candidateRows|perPhaseCandidates|winnersPerParent|finalValidationCandidates|finalValidationIndexAlternatives/);

console.log('Strategy budget layout checks passed');
```

- [ ] **Step 2: Register and run the check to verify RED**

Add to `package.json`:

```json
"check:strategy-budget-layout": "esbuild scripts/strategy-budget-layout-check.ts --bundle --platform=node --format=esm --outfile=node_modules/.cache/strategy-budget-layout-check.mjs && node node_modules/.cache/strategy-budget-layout-check.mjs"
```

Run:

```bash
npm run check:strategy-budget-layout
```

Expected: FAIL because `StrategyBudgetEditor.tsx` does not exist.

- [ ] **Step 3: Add round-trip assertions for hidden old values**

Extend `strategy-template-check.ts` after its existing payload assertions:

```ts
const legacyAdvancedPayload = pruneStrategyDraft({
  ...draft,
  budget: {
    ...draft.budget,
    advanced: true,
    baselineRows: 50_000,
    candidateRows: 40_000,
    perPhaseCandidates: 25,
    winnersPerParent: 5,
    finalValidationCandidates: 8,
    finalValidationIndexAlternatives: 2,
  },
});
assert.equal(legacyAdvancedPayload.config.budget.baseline_rows, 50_000);
assert.equal(legacyAdvancedPayload.config.budget.candidate_rows, 40_000);
assert.equal(legacyAdvancedPayload.config.budget.per_phase_candidates, 25);
assert.equal(legacyAdvancedPayload.config.budget.winners_per_parent, 5);
assert.equal(legacyAdvancedPayload.config.budget.final_validation_candidates, 8);
assert.equal(legacyAdvancedPayload.config.budget.final_validation_index_alternatives, 2);

const newPayload = pruneStrategyDraft({ ...draft, budget: { ...draft.budget, advanced: false } });
assert.equal('baseline_rows' in newPayload.config.budget, false);
assert.equal('candidate_rows' in newPayload.config.budget, false);
assert.equal('per_phase_candidates' in newPayload.config.budget, false);
assert.equal('winners_per_parent' in newPayload.config.budget, false);
assert.equal('final_validation_candidates' in newPayload.config.budget, false);
assert.equal('final_validation_index_alternatives' in newPayload.config.budget, false);
```

- [ ] **Step 4: Run the existing model check**

Run:

```bash
npm run check:strategy-template
```

Expected: PASS. This proves the current serializer already satisfies the required compatibility behavior before UI changes.

- [ ] **Step 5: Review without committing**

Run `git diff --check`. Do not commit or push; this repository requires explicit user authorization.

---

### Task 2: Build the focused StrategyBudgetEditor component

**Files:**
- Create: `apps/config_editor_ui/src/components/StrategyBudgetEditor.tsx`

**Interfaces:**
- Consumes: `StrategyBudgetDraft`, `SearchProcedure`, field errors, and an immutable update callback.
- Produces: `StrategyBudgetEditor(props): JSX.Element` with two semantic groups and procedure-aware copy.

- [ ] **Step 1: Define the component boundary**

Use this public interface exactly:

```ts
interface StrategyBudgetEditorProps {
  value: StrategyBudgetDraft;
  procedure: SearchProcedure;
  errors: Record<string, string>;
  onChange(next: StrategyBudgetDraft): void;
}
```

Import `Alert` and `TextField` from `@adqm/gpb-ui`, `MaterialIcon`, `useI18n`, and the two strategy types. Do not import `Switch`.

- [ ] **Step 2: Add one immutable numeric updater**

Use the four visible keys only:

```ts
type VisibleBudgetKey = 'rowsPerInsert' | 'insertRepetitions' | 'maxCandidates' | 'topN';

const updateNumber = (key: VisibleBudgetKey, raw: string): void => {
  onChange({ ...value, [key]: raw === '' ? 0 : Number(raw) });
};
```

Do not delete or reconstruct `value`; spreading it preserves hidden compatibility
properties loaded from older strategies.

- [ ] **Step 3: Render the INSERT-test section**

Render a `<section className="strategy-budget-group strategy-budget-group--data" aria-labelledby="strategy-budget-data-title">` containing:

- `MaterialIcon name="data"`;
- the exact bilingual heading and description from the spec;
- `TextField type="number" step={1} min={1}` for `rowsPerInsert` and `insertRepetitions`;
- a `.field-help` paragraph immediately after each field;
- `.strategy-budget-explanation` with the live `N × rows` description.

Use `toLocaleString(locale === 'ru' ? 'ru-RU' : 'en-US')` for displayed numbers.
Do not calculate `rowsPerInsert * insertRepetitions`.

- [ ] **Step 4: Render the search-limit section**

Render a sibling `<section className="strategy-budget-group strategy-budget-group--search" aria-labelledby="strategy-budget-search-title">` containing:

- `MaterialIcon name="strategy"`;
- the exact bilingual heading and description from the spec;
- an always-visible `maxCandidates` field;
- a `topN` field only inside `procedure === 'sequential'`;
- the sequential live explanation when sequential;
- the specified ADQM informational `Alert` when combined.

Do not render a disabled Top-N field for Combined. Do not mention Phased Top-N.

- [ ] **Step 5: Verify GREEN for the focused check**

Run:

```bash
npm run check:strategy-budget-layout
npm run typecheck
```

Expected: both commands exit 0.

- [ ] **Step 6: Review without committing**

Inspect the component for raw product inputs, unsupported UI libraries, and hidden-field reconstruction. Run `git diff --check`. Do not commit or push.

---

### Task 3: Integrate the component into the strategy wizard

**Files:**
- Modify: `apps/config_editor_ui/src/pages/StrategyEditorPage.tsx`

**Interfaces:**
- Consumes: `StrategyBudgetEditor` from Task 2.
- Produces: step 3 state updates through the existing `patch('budget', next)` flow.

- [ ] **Step 1: Replace the inline budget JSX**

Add:

```ts
import { StrategyBudgetEditor } from '../components/StrategyBudgetEditor';
```

Replace the complete `step === 2` inline block with:

```tsx
{step === 2 ? (
  <StrategyBudgetEditor
    value={draft.budget}
    procedure={draft.procedure}
    errors={errors}
    onChange={(value) => patch('budget', value)}
  />
) : null}
```

- [ ] **Step 2: Remove obsolete page-level budget helpers**

Remove `Switch` from the `@adqm/gpb-ui` import and delete the page-level `numberField`
helper. Keep `numberValue` because scoring percentage fields still use it. Keep the
existing step-2 validation call; do not alter API submission.

- [ ] **Step 3: Update the step helper copy**

Change only the third `stepHelp` item to:

```ts
t(
  'Настройте объём тестовых INSERT и ограничения перебора вариантов.',
  'Configure test INSERT volume and candidate-search limits.',
)
```

- [ ] **Step 4: Run integration checks**

Run:

```bash
npm run check:strategy-budget-layout
npm run check:strategy-template
npm run check:i18n
npm run typecheck
```

Expected: all commands exit 0.

- [ ] **Step 5: Review without committing**

Run `git diff --check`. Confirm no unrelated strategy, scoring, or autocomplete code changed. Do not commit or push.

---

### Task 4: Add responsive, theme-safe visual separation

**Files:**
- Modify: `apps/config_editor_ui/src/styles.css`

**Interfaces:**
- Consumes: the class structure from Task 2.
- Produces: two equal desktop groups, one-column mobile layout, teal data identity, and violet search identity.

- [ ] **Step 1: Add the group layout**

Add budget-specific styles near existing `.strategy-budget-help` rules:

```css
.strategy-budget-editor {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}
.strategy-budget-group {
  --budget-accent: var(--acm-accent);
  --budget-tint: var(--accent-soft);
  min-width: 0;
  padding: 22px;
  border: 1px solid var(--border);
  border-left: 4px solid var(--budget-accent);
  border-radius: 11px;
  background: var(--surface);
}
.strategy-budget-group--data {
  --budget-accent: #35b9bd;
  --budget-tint: color-mix(in srgb, #35b9bd 12%, var(--surface));
}
.strategy-budget-group--search {
  --budget-accent: #8b72e8;
  --budget-tint: color-mix(in srgb, #8b72e8 12%, var(--surface));
}
```

- [ ] **Step 2: Add heading, field, and explanation styles**

Use grid/flex styles so the icon, title, description, two fields, and explanation
remain aligned. The icon container uses `var(--budget-tint)` and
`var(--budget-accent)`. The explanation uses the same tint, 12 px radius or less,
13 px readable text, and no fixed height. Scope all selectors beneath
`.strategy-budget-editor`.

- [ ] **Step 3: Add mobile behavior**

Inside the existing `@media (max-width: 760px)` strategy block add:

```css
.strategy-budget-editor { grid-template-columns: minmax(0, 1fr); }
.strategy-budget-group { padding: 18px; }
```

Do not add horizontal overflow or truncate helper/error text.

- [ ] **Step 4: Run static checks**

Run:

```bash
npm run check:ui-kit
npm run typecheck
npm run build
git diff --check
```

Expected: all commands exit 0. The existing Vite `runtime-config.js` non-module warning may remain; no new warning is acceptable.

- [ ] **Step 5: Review without committing**

Confirm both group meanings remain clear in monochrome and dark theme. Do not commit or push.

---

### Task 5: Synchronize docs and verify the complete page

**Files:**
- Modify only if verification exposes a defect in files owned by Tasks 1–4.

**Interfaces:**
- Consumes: complete budget UI implementation.
- Produces: verified source and a browser-tested page; deployment remains a separate user-authorized action.

- [ ] **Step 1: Run the full frontend gate**

Run from `apps/config_editor_ui`:

```bash
npm run check:ui-kit
npm run check:strategy-options
npm run check:strategy-template
npm run check:strategy-budget-layout
npm run check:alternative-focus
npm run check:source-type-autocomplete
npm run check:navigation-state
npm run check:i18n
npm run typecheck
npm run build
```

Run from the repository root:

```bash
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 2: Verify behavior in a local browser**

Using the already configured local frontend environment, inspect both create and edit flows in Russian and English:

1. Sequential shows two groups, all four primary fields, and the Top-N explanation.
2. Combined shows two groups, hides Top-N, and displays the joint-comparison Alert.
3. There is no Advanced budget switch or advanced field label.
4. Invalid zero, negative, and fractional visible values cannot advance.
5. At 320 px width the groups stack without horizontal scrolling.
6. At 200% zoom, descriptions and field errors remain visible.
7. Light and dark themes preserve contrast and visual grouping.

- [ ] **Step 3: Verify compatibility without mutating user data**

Use the pure `pruneStrategyDraft()` checks from Task 1 as the authoritative
round-trip proof. Do not save an existing user strategy merely to test the UI.

- [ ] **Step 4: Report exact state**

Report changed files, commands actually run, build warnings, checks not run, and
whether deployment was skipped. Do not claim deployment, commit, or push unless the
user separately authorized and those actions were verified.
