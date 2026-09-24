# Strategy Search Budget Page Handoff

## 1. Purpose and status

This document is the implementation source of truth for step 3, `Бюджет поиска`,
inside the strategy create/edit wizard. It supersedes section 11 of
`strategy-editor-page-handoff.md`.

The user selected the direct-control design: show the four meaningful numeric
controls without presets, but visually separate the data used for INSERT
measurements from the limits that control candidate and Top-N search breadth.

This is a frontend presentation change. It does not authorize a backend schema,
Control API, optimizer, or runtime change.

## 2. User outcome

After opening the step, a user must understand three facts without knowing internal
field names:

1. how much data is inserted for each candidate measurement;
2. how many times the INSERT measurement is repeated;
3. how many candidate configurations may be checked and, for Sequential Top-N,
   how many winners continue to the next optimization direction.

The page must not present all four values as one undifferentiated grid.

## 3. Page structure

Keep the existing page heading `Бюджет поиска` / `Search budget`.

Replace the current helper with:

- RU: `Настройте объём тестовых INSERT и ограничения перебора вариантов.`
- EN: `Configure test INSERT volume and candidate-search limits.`

Inside the existing strategy form card render a two-column group layout on desktop
and one column below 760 px. Each group is a real `<section>` with its own heading,
description, icon, accent, fields, and a live plain-language explanation.

Use icons and text in addition to color. Color alone must never communicate group
meaning.

### 3.1 Group A — Данные для INSERT-теста

Visual identity:

- icon: `MaterialIcon name="data"`;
- accent: teal/cyan, consistent in both supported themes;
- heading RU: `Данные для INSERT-теста`;
- heading EN: `INSERT test data`.

Description:

- RU: `Определяет, сколько строк вставлять во временную таблицу кандидата и сколько раз повторить измерение.`
- EN: `Controls how many rows are inserted into a candidate's temporary table and how many times the measurement is repeated.`

Fields:

| Draft key | RU label | EN label | Permanent helper |
| --- | --- | --- | --- |
| `rowsPerInsert` | `Строк в одном тестовом INSERT` | `Rows in one test INSERT` | RU: `Размер данных для одного измерения кандидата.` EN: `Data volume for one candidate measurement.` |
| `insertRepetitions` | `Повторов INSERT-теста` | `INSERT test repetitions` | RU: `Повторы снижают влияние случайных колебаний; для оценки используется медиана.` EN: `Repeats reduce random variation; the median is used for scoring.` |

Live explanation below the fields:

- RU: `Для каждого кандидата: {insertRepetitions} измерения × {rowsPerInsert} строк.`
- EN: `For each candidate: {insertRepetitions} measurements × {rowsPerInsert} rows.`

Do not multiply the two values into a claimed row count. The text describes the
measurement shape, not retained storage or an exact runtime duration.

### 3.2 Group B — Ограничения поиска

Visual identity:

- icon: `MaterialIcon name="strategy"`;
- accent: violet/indigo, distinct from Group A and existing destructive colors;
- heading RU: `Ограничения поиска`;
- heading EN: `Search limits`.

Description:

- RU: `Ограничивает число измеряемых вариантов и количество победителей, которые проходят дальше.`
- EN: `Limits the number of measured candidates and the winners that continue.`

Fields:

| Draft key | Visibility | RU label | EN label | Permanent helper |
| --- | --- | --- | --- | --- |
| `maxCandidates` | always | `Максимум проверяемых вариантов` | `Maximum candidates to test` | RU: `Жёсткий предел числа вариантов в одном поиске.` EN: `Hard limit for candidates in one search.` |
| `topN` | only when `procedure === 'sequential'` | `Проходит дальше после шага (Top-N)` | `Continue after each step (Top-N)` | RU: `После каждого направления только лучшие варианты продолжают поиск.` EN: `After each dimension, only the best candidates continue.` |

Sequential live explanation:

- RU: `Будет проверено не более {maxCandidates} вариантов. После каждого направления дальше пройдут Top-{topN}.`
- EN: `Up to {maxCandidates} candidates will be tested. After each dimension, Top-{topN} continue.`

Combined live explanation:

- RU title: `Комбинированный поиск`;
- RU body: `Будет проверено не более {maxCandidates} сочетаний. Все результаты сравниваются вместе — промежуточный Top-N не применяется.`
- EN title: `Combined search`;
- EN body: `Up to {maxCandidates} combinations will be tested. All results are compared together; intermediate Top-N does not apply.`

Render the combined explanation with the supported ADQM `Alert` component using an
informational tone. Do not render a disabled Top-N field for Combined; hiding it is
clearer because it has no effect on that procedure.

## 4. Remove Advanced budget settings

Remove all of the following from the product-facing budget step:

- the `Расширенные настройки бюджета` / `Advanced budget settings` switch;
- `Строк базового варианта`;
- `Строк кандидата`;
- `Кандидатов на этап`;
- `Победителей на родителя`;
- `Кандидатов финальной проверки`;
- `Альтернатив индекса в финале`.

Do not replace the switch with an accordion, disclosure, modal, tooltip, or another
hidden entry point. These controls are absent from this page.

The unrelated generic Advanced example in the design-system catalogue is outside
this task and must not be removed.

## 5. Compatibility and serialization

Do not change `StrategyBudgetConfig`, the Control API document schema, or stored
records in this task.

Keep the existing optional advanced properties in `StrategyBudgetDraft` and
`StrategyBudgetConfig` so an older saved strategy can still round-trip without data
loss. `fromStrategy()` may continue loading them, and `pruneStrategyDraft()` may
continue preserving them when the loaded draft has `advanced: true`.

For a newly created strategy, `advanced` remains `false`, so none of the hidden
optional properties is submitted.

Do not add new defaults, silently rewrite old optional values, or add a data
migration. Removing those fields from the contract requires a separate product and
migration decision.

The Top-N control is hidden for Combined, but the existing required `top_n` protocol
field remains serialized for compatibility. The frontend does not claim that it
affects Combined execution.

## 6. Validation

Retain the current positive-integer validation for:

- `rowsPerInsert`;
- `insertRepetitions`;
- `maxCandidates`;
- `topN`.

Errors must render next to the owning field. For a Sequential strategy, an invalid
Top-N value blocks progression. Combined keeps its current stored Top-N compatibility
value; no new backend validation rule is introduced in this UI task.

Do not invent maximum values without a backend contract. Do not accept zero,
negative, fractional, `NaN`, or infinite values.

## 7. Components and files

Create a focused component:

`apps/config_editor_ui/src/components/StrategyBudgetEditor.tsx`

Public props:

```ts
interface StrategyBudgetEditorProps {
  value: StrategyBudgetDraft;
  procedure: SearchProcedure;
  errors: Record<string, string>;
  onChange(next: StrategyBudgetDraft): void;
}
```

The component owns budget labels, descriptions, number fields, conditional Top-N
visibility, explanations, and semantic section markup. It uses `useI18n()` directly.

`StrategyEditorPage.tsx` remains responsible for wizard navigation, validation, and
patching the parent draft. Replace the inline step-3 JSX with
`<StrategyBudgetEditor ... />`. Remove the now-unused `Switch` import and inline
budget field helper.

Add only budget-specific styles to `apps/config_editor_ui/src/styles.css`.

## 8. Visual requirements

- Two equal columns at widths above 760 px; one column at or below 760 px.
- Group padding: 20–24 px; gap between groups: 16–20 px.
- Border radius: 10–12 px, matching the existing strategy editor.
- Each group has a visible 3–4 px accent edge and a tinted icon container.
- Group headings and descriptions align even when field helper text wraps.
- Field labels, units, and errors stay legible in light and dark themes.
- Live explanations use a softly tinted inset panel, not a third large card.
- No fixed height that causes clipping at 200% browser zoom.
- No horizontal scrolling at 320 px viewport width.
- Use existing theme variables and `color-mix`; do not introduce another UI kit,
  remote asset, or CDN.

Suggested class structure:

```text
strategy-budget-editor
  strategy-budget-group strategy-budget-group--data
    strategy-budget-group-heading
    strategy-budget-fields
    strategy-budget-explanation
  strategy-budget-group strategy-budget-group--search
    strategy-budget-group-heading
    strategy-budget-fields
    strategy-budget-explanation
```

## 9. Accessibility and localization

- Each group is a `<section aria-labelledby="...">` with a unique heading ID.
- Decorative icons remain `aria-hidden` through `MaterialIcon`.
- Every field uses ADQM `TextField` with an explicit visible label.
- Meaning never depends on teal versus violet alone.
- Error text remains connected through the ADQM field component.
- All new user-facing copy uses `t(ru, en)`.
- Russian and English layouts must both be checked for wrapping.

## 10. Non-goals

This task does not:

- add presets such as Fast, Balanced, or Thorough;
- estimate wall-clock duration;
- calculate cost or storage retained after the test;
- modify scoring, search dimensions, or procedure selection;
- expose the deferred Phased Top-N method;
- change backend execution or claim that the current local run endpoint executes the
  optimizer;
- remove optional advanced keys from API or persistence contracts.

## 11. Acceptance criteria

1. Step 3 displays exactly two visibly distinct semantic groups.
2. INSERT rows and repetitions appear only in the INSERT-test group.
3. Maximum candidates and applicable Top-N appear only in the search-limit group.
4. Sequential shows an editable Top-N field and explains winner propagation.
5. Combined hides the Top-N field and explains joint comparison.
6. The Advanced switch and all six advanced controls are absent.
7. Existing schema-v2 advanced fields still survive an edit/save round trip.
8. New strategies do not submit hidden optional budget fields.
9. Invalid visible values block progression with field-level errors.
10. RU/EN, light/dark themes, desktop/mobile layouts, UI-kit checks, typecheck, and
    production build all pass.
