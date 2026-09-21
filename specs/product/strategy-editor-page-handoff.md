# Strategy creation and editing: detailed implementation handoff

## 1. Purpose and authority

Implement a polished strategy editor using this document as the page specification.
This document records the user's latest corrections to the earlier wizard design.
It is a handoff specification, not evidence that the described functionality exists.
The user has requested documentation instead of further implementation in this task.

Explicit user decisions:

1. Use the selected option B: a horizontal stepper above one centered form card.
2. Remove the persistent summary strip completely, including method, stage count,
   candidate count, and priority. Do not move it into a sidebar or another footer.
3. Types, codecs, and indexes must each have their own actual settings. They are
   not mutually exclusive search-method cards and not merely on/off switches.
4. Sequential Top-N and phased Top-N belong to a separate search-procedure section.
5. Former steps 2 and 3 share one tab/step called `Настройки поиска`.
6. Use the existing ADQM design system. Preserve the surrounding application shell.

The resulting wizard has exactly four steps:

`Основное → Настройки поиска → Бюджет поиска → Оценка`

Product interface copy remains Russian. Code identifiers and this handoff are English.
Communicate with the user in English, following their explicit preference.

Where this document adds details such as spacing, default accordion states, or
placement of controls, these are implementation recommendations derived from the
chosen mockup, not additional independently approved product decisions.

Read repository AGENTS.md and docs/AI_EXECUTION_WORKFLOW.md before implementation.
Do not treat the old plan's deployment commands as current authorization to deploy.

## 2. Required reading and actual source files

- [Earlier wizard specification](../../docs/superpowers/specs/2026-09-21-strategy-template-wizard-design.md)
- [Earlier implementation plan](../../docs/superpowers/plans/2026-09-21-strategy-template-wizard.md)
- [Existing template contract ADR](../../docs/adr/0003-strategy-template-contract.md)
- [In-progress independent-dimensions ADR](../../docs/adr/0004-independent-strategy-dimensions.md)
- [Current page](../../apps/config_editor_ui/src/pages/StrategyEditorPage.tsx)
- [Current strategy model](../../apps/config_editor_ui/src/strategies/model.ts)
- [Current styles](../../apps/config_editor_ui/src/styles.css)
- [Control API](../../apps/realtime_control_api/src/realtime_control_api/main.py)
- [Existing rule editor](../../apps/config_editor_ui/src/components/rules/RulesEditor.tsx)
- [Rule types](../../apps/config_editor_ui/src/types/config.ts)
- [Legacy rule requirements](../../src/models.py)

ADQM documentation is at
`/home/oleg/Documents/Codex/2026-09-11/new-chat/work/adqm_design_system-repo/react-ui/README.md`.
Read it and inspect the installed component markup before writing CSS selectors.
The installed Button renders `.button`, not `.ui-button`; the old selector mismatch
was one cause of the original broken presentation.

Legacy files are requirements references only. Do not import legacy Python models
into a target runtime or connect the old execution engine as a shortcut.

## 3. Current worktree and incomplete work

At handoff, the horizontal layout and four-step navigation have been implemented.
The summary strip has been removed. Step 2 still contains the old mixed method
cards and boolean rule switches. That is an intermediate state, not the requested
finished page.

Two newly created files are unfinished, unintegrated drafts:

- `apps/config_editor_ui/src/components/StrategyDimensionsEditor.tsx`
- `apps/config_editor_ui/src/strategies/dimensions.ts`

Do not assume these drafts are correct because they compile or exist. In particular:

- They are not connected to StrategyEditorPage or the live API.
- Their proposed `dimensions` shape is not an accepted API implementation.
- They use a simplified `alternatives` field, whereas existing rule contracts use
  typed `types`, `codecs`, and `indexes` fields.
- They incorrectly treat column order as a physical optimization dimension.
- Their client validation is incomplete, including whitespace and ORDER BY cases.
- Their accordion defaults open every section; use the defaults in this handoff.

ADR-0004 is also an in-progress document. Correct its column-order semantics and
align its final wire shape with the validated implementation before relying on it.
An `Accepted` heading in that draft is not evidence of implementation verification.

Existing dirty `ProductShell.tsx` changes predate this task: preserve them.
The untracked `specs/product/benchmark-plan-creation.md` is unrelated user work:
read if relevant, but do not overwrite it.

Last successful frontend check covered the four-step merge before the two draft
files were added. No successful end-to-end v2 rule persistence has been verified.

## 4. Outer page layout

Keep the application sidebar and global header. Inside the existing scrollable
main content area, render the following from top to bottom:

1. Breadcrumb: link-style ADQM Button `Стратегии`, slash, current mode.
2. Page title: `Создать стратегию` or `Редактировать стратегию`.
3. Subtitle: `Настройте правила оптимизации, порядок поиска и оценку результатов.`
4. Horizontal four-step navigation.
5. One white/themed form card containing the current step and its action footer.

No concept labels such as `B / FOCUSED WIZARD` appear in the product.
No right sidebar, summary panel, metrics row, technical ID, or JSON preview.

Desktop geometry:

| Element | Recommended geometry |
| --- | --- |
| Page content inset | 24px; 32px when surrounding layout permits |
| Form/stepper width | `width: 100%; max-width: 1080px; margin-inline: auto` |
| Breadcrumb to title | 20px |
| Title | 28–32px, medium/semibold, theme heading color |
| Subtitle | 14–16px, muted theme text, 8px below title |
| Header to stepper | 28–32px |
| Stepper to form | 24–28px |
| Form radius/border | 10px; 1px theme border |
| Form body padding | 32px desktop, 20px narrow screen |
| Main step title | 24–26px, line-height 1.3 |
| Helper text | 14px, line-height 1.5–1.6 |
| Section spacing | 24–28px |
| Related field spacing | 16px |
| Input minimum height | 40–44px using supported component sizing |
| Footer padding | 20–24px vertical, matching form side padding |

Use theme tokens for surfaces, text, borders, accent, focus, and errors. Support
both installed light and dark themes. No hardcoded white text on a pale selected
card. No gradients, oversized shadows, decorative pictures, or external fonts.

## 5. Stepper and navigation behavior

Each of four equal-width items has a circular number above its label. The active
circle is blue with contrasting text. Completed preceding steps use a check mark
and pale accent surface. Future steps use neutral circles. Thin lines join circles;
lines never run through their numbers or labels.

Circle diameter: 40px desktop, 32px mobile. Label gap: 8–10px.
Keep labels visible on mobile; do not hide them with `font-size: 0`.

Use semantic navigation with `aria-label="Этапы настройки стратегии"` and
`aria-current="step"` on the active step. Use ADQM Buttons for step actions.
Decorative circles/check marks are aria-hidden; accessible button names are labels.

State rules:

- Current step is clearly indicated independently of hover/focus.
- Backward navigation preserves all draft values.
- Forward navigation validates the steps being left; invalid values block it.
- For new strategies, do not jump over an unvalidated required step.
- Editing may expose all steps, but final submission validates the entire draft.
- Re-entering a step preserves expanded editors, values, and stable row identities.
- On navigation, scroll the form heading into view and focus it without causing
  a second unexpected page jump. Use `tabIndex={-1}` for the heading if necessary.
- During save, disable navigation and editing consistently to avoid saving a draft
  different from the one shown to the user.

Do not hardcode obsolete five-step indexes. Prefer named step constants or a
single ordered definition used by titles, validators, stepper, and footer.

## 6. Form footer

Footer belongs to the card and is separated from the body by a thin border.
Place `Отмена` at the far left. Put `Назад` and the primary action together on the
right, with 8–12px spacing.

| Step | Right-side controls |
| --- | --- |
| Basics | `Далее →` |
| Search configuration | `Назад`, `Далее →` |
| Budget | `Назад`, `Далее →` |
| Scoring, create | `Назад`, `Создать стратегию` |
| Scoring, edit | `Назад`, `Сохранить` |

Save/Create must not appear on intermediate steps. Next/Back do not write to the
API. Cancel returns to the catalog without persisting the draft. If introducing
unsaved-change protection, use one consistent ADQM confirmation for Cancel,
breadcrumb, and leaving the editor; do not make navigation impossible.

Long step 2 may scroll. Do not force all its content into one viewport. A sticky
footer is optional only if it stays within the form, never covers fields, and is
verified with the actual application's scroll container. Default: normal-flow footer.

## 7. Step 1 — Основное

Heading: `Основное`.
Helper: `Дайте стратегии понятное название и добавьте описание для команды.`

Fields, in order:

1. `Название`: TextField, required, full width, maximum 120 characters.
   Placeholder: `Например, Оптимизация аналитической витрины`.
   Reject empty/whitespace-only input; trim at the serialization boundary.
2. `Описание`: TextArea, optional, 3–4 rows, maximum 500 characters.
   Placeholder: `Для каких задач подходит эта стратегия?`.
   A small `Необязательно` hint may accompany the label.

No method preview, derived phases, identifier, workload, or statistics here.

## 8. Step 2 — Настройки поиска: overall structure

Heading: `Настройки поиска`.
Helper: `Настройте каждое направление оптимизации отдельно, затем выберите способ поиска.`

The step consists of TWO major sections, both on the same page:

```text
┌ Настройки поиска ───────────────────────────────────────────┐
│ Short explanatory text                                     │
│                                                           │
│ Что оптимизировать                                        │
│ ┌ Типы колонок                         2 правила       ▾ ┐  │
│ │ matcher + alternatives + Add rule                       │  │
│ └────────────────────────────────────────────────────────┘  │
│ ┌ Кодеки                              Не настроено     ▸ ┐  │
│ ┌ Skip-индексы                         1 правило       ▸ ┐  │
│ ┌ Ключ сортировки ORDER BY             Не настроено     ▸ ┐  │
│ ┌ Гранулярность таблицы                2 значения      ▸ ┐  │
│                                                           │
│ Как выполнять поиск                                       │
│ [Совместный] [Последовательный Top-N] [Поэтапный Top-N]       │
│ Procedure-specific explanation                            │
│ Порядок перебора колонок (optional disclosure)              │
│                                                           │
├ Отмена                                  Назад  Далее → ───┤
```

Counts in this wireframe illustrate layout only. Never populate runtime with these
example values. Count actual configured rules; show `Не настроено` for empty data.

All optimization sections coexist. Choosing one does not remove or overwrite the
others. Procedure selection must not silently clear configuration. Do not offer
`Типы и кодеки` or `Skip-индексы` as alternatives alongside Top-N procedures.

## 9. Independent optimization panels

Render five stacked accordion panels under `Что оптимизировать` in this order:

1. `Типы колонок`
2. `Кодеки`
3. `Skip-индексы`
4. `Ключ сортировки ORDER BY`
5. `Гранулярность таблицы`

Header contains a readable title on the left, actual rule count/status on the
right, and disclosure indicator at the edge. Whole header is keyboard accessible.
Use native details/summary or a supported accessible disclosure; do not simulate
an interactive div. Form controls inside use ADQM.

New template: open Types by default; other panels collapsed. Existing template:
open first nonempty panel. Multiple panels may stay open. Collapsing preserves
data and has no semantic effect on the configuration.

Empty panel: one concise explanation and `Добавить правило`/`Добавить вариант`.
Do not add a meaningless master toggle. Adding/removing actual rules configures
the dimension. Show explicit validation when no effective dimension is configured.

Each rule is a light bordered inner block with stable key, a small heading
`Правило 1`, and `Удалить правило` action. Index numbering is display only; use
stable client IDs so deleting a middle row does not move focus into another rule.
Do not serialize client row IDs.

### 9.1 Types panel

Description: `Укажите, какие физические типы разрешено проверять для исходных типов колонок.`

Rule layout:

- First row, two columns: required `Исходный тип колонки`; optional `Имя колонки`.
- Next row: `Альтернативные типы`, one alternative per row with remove action.
- Below list: `Добавить тип`.
- Bottom of rule: `Удалить правило`.
- Bottom of panel: `Добавить правило`.

Examples may appear as placeholders only: source `String`, alternative
`LowCardinality(String)`. Do not silently instantiate them as configured rules.
Preserve types with parentheses, commas, quotes, and spaces; splitting by commas
would corrupt legitimate parameterized types. Prefer explicit repeatable rows.

At least one nonblank alternative is required per rule. `by_type` is required;
`by_name` narrows the selector and cannot substitute for the source type.
Do not add codecs inside the Types UI: the Codecs panel is independently editable.
If a legacy rule combines both, conversion must preserve both through an explicit,
tested normalization; never discard one field.

### 9.2 Codecs panel

Description: `Задайте кодеки и цепочки сжатия отдельно от типов колонок.`

Same matcher row as Types. List label: `Кодеки и цепочки кодеков`.
Each row is one complete candidate chain. Placeholder examples: `ZSTD(1)` and
`Delta, ZSTD(3)`. A comma inside a chain is not a candidate separator.
Actions: `Добавить кодек`, `Удалить вариант`, `Добавить правило`, `Удалить правило`.

Keep auto-generation settings out of the initial UI unless their exact current
contract and meaningful backend behavior are verified. Do not invent automatic
candidate generation merely to fill an empty panel.

### 9.3 Skip-index panel

Description: `Настройте типы skip-индексов и гранулярность каждого варианта.`

Rule begins with required source type and optional column-name matcher.
Each candidate row has:

1. `Тип индекса и параметры`: text input, e.g. `bloom_filter(0.01)` as placeholder.
2. `Гранулярность индекса`: positive integer input, unit `гранул`.
3. `Удалить вариант`: secondary/icon button with accessible label.

Add candidate button: `Добавить вариант индекса`.
Add rule button: `Добавить правило индекса`.

Prefer a repeatable list of explicit `(type, granularity)` candidates. If supporting
the legacy granularity-list shorthand, normalize it deterministically at the API
boundary and test the expansion. Do not discard nested index parameters.

Helper below the list:
`Гранулярность skip-индекса и index_granularity таблицы — разные настройки.`

### 9.4 ORDER BY panel

Description: `Перечислите ключи сортировки, которые разрешено проверять.`

Optional first field: `Первая колонка` with explanation of its verified meaning.
Then repeatable candidates, labeled `Кандидат ORDER BY`.
Each row holds a whole candidate expression. Do not split on commas within a key.
Actions: `Добавить кандидат`, `Удалить кандидат`.

Empty optional first-column field is omitted. A first-column value without any
effective candidate must not make an otherwise empty strategy valid.
Do not accept raw DDL or execute text during editing/validation.
Validate actual expression support at the owning backend boundary; the UI does
not claim that arbitrary SQL is safe or executable.

### 9.5 Table granularity panel

Description: `Задайте варианты index_granularity — число строк в грануле таблицы.`

Repeatable numeric rows:

- `Строк в грануле`: required positive integer for each added row.
- `Удалить вариант`.
- At bottom: `Добавить вариант`.

Do not combine with skip-index granularity or use a free-form comma parser.
Example placeholder: `8192`. New blank row must remain visibly incomplete until
the user enters a value; avoid silently adding an arbitrary optimization choice.

## 10. Search procedure section

Place this AFTER the independently editable optimization panels, separated by
28px spacing and a thin divider. Heading: `Как выполнять поиск`.
Helper: `Способ поиска определяет, как исследуются настроенные варианты.`

Exactly three mutually exclusive choices:

| UI title | Proposed procedure ID | Description |
| --- | --- | --- |
| Совместный поиск | `combined` | `Рассматривать сочетания настроенных вариантов в одном поиске.` |
| Последовательный Top-N | `sequential` | `Последовательно отбирать лучшие варианты и передавать их дальше.` |
| Поэтапный Top-N | `phased` | `Выполнять поиск по этапам с отбором и финальной проверкой.` |

Use three equal cards on wide screens, one column below the mobile breakpoint.
Card: 16–20px padding, 8px radius, minimum 100px height, title and short description,
visible selected indicator. Selected state: pale theme accent background and blue
border; text stays readable. Card semantics must reflect single selection. Use a
supported radio component, or implement full radio-group keyboard semantics over
ADQM controls. `aria-pressed` alone is a toggle-button model, not a radio group.

The descriptions express intended configuration semantics. Do not claim that the
current run endpoint executes these procedures. Runtime support needs its own
capability-validated integration; see section 15.

Do not place types/codecs/indexes in this group. Do not turn selecting a procedure
into destructive pruning of configured optimization fields. For combinations that
a future execution backend cannot support, surface an explicit validation error
or capability explanation rather than silently dropping settings.

No mandatory decorative pipeline preview. If retained, label it as a derived
configuration plan, derive it from both procedure and actual configured dimensions,
and never show a serial arrow chain for genuinely combined execution.

### Column iteration order

An important source-code finding: existing `column_order` changes the order in
which matched columns are explored; it does not rearrange physical table columns.
Put this control under the search procedure, not among physical optimizations.

Disclosure title: `Порядок перебора колонок`.
Description: `Задаёт приоритет исследования колонок. Не меняет их физический порядок в таблице.`
Optional explicit rows: `Колонка`, `Позиция`, remove action.
Positions start at 1 and must be unique; names must also be unique.
Use `Добавить колонку`. Empty list means no explicit override.
If an automatic order mode is exposed, only use a mode with verified semantics,
such as existing `compressed_size_desc`, and make precedence over manual order explicit.

Physical column reordering is a separate feature. Do not promise or implement it
as an accidental consequence of relabeling this existing search control.

## 11. Step 3 — Бюджет поиска

Heading: `Бюджет поиска`.
Helper: `Ограничьте объём измерений и число проверяемых вариантов.`

Two-column field grid on desktop, one column on mobile:

| Field | Meaning/unit | Validation |
| --- | --- | --- |
| Строк для одного измерения INSERT | rows copied per measurement | positive integer |
| Повторов измерения INSERT | number of repetitions | positive integer |
| Максимум кандидатов | candidate count | positive integer |
| Победителей Top-N | retained candidates | positive integer, applicable procedures only |

Under row-limit fields:
`По умолчанию базовый вариант и кандидаты используют одинаковое число строк.`

Below the grid, ADQM Switch `Расширенные настройки`. Revealing it preserves
already entered values; hiding it must have explicit serialization semantics.
Current contract omits advanced values when disabled. Preserve this behavior or
document and test an approved change; do not silently send hidden stale values.

Advanced fields, with units in labels/hints:

- `Строк базового варианта` — rows.
- `Строк варианта-кандидата` — rows.
- `Кандидатов на этап` — candidates; only for applicable procedures.
- `Победителей на родительский вариант` — candidates; only when applicable.
- `Вариантов финальной проверки` — candidates; phased only.
- `Альтернатив индекса в финальной проверке` — positive count; phased with indexes.

For the last field, permanent helper:
`1 — только лучшее сочетание. Большее число проверяет следующие варианты по одной колонке, без полного перебора сочетаний.`

Procedure-dependent fields must be defined consistently in UI, validator, and
serializer. Search dimensions do not disappear when a budget field is inapplicable.
Determine authoritative runtime applicability from the documented contract before
changing existing API validation; do not infer it from English field names alone.

## 12. Step 4 — Оценка

**Superseded by the latest user request:** implement this step using
[the detailed scoring/formula handoff](strategy-scoring-page-handoff.md).
The user now explicitly requires visible formulas, formula presets, and a variable
catalog. The earlier prohibition on expression/variable/direction editing below is
historical and must not be implemented. Other page layout decisions remain in force.

Heading: `Оценка`.
Helper: `Выберите приоритет оптимизации и при необходимости задайте ограничения.`

Four single-select cards in a 2×2 grid, one column on mobile:

- `Сбалансированно` — `Учитывать чтение, вставку и размер хранения.`
- `Быстрее чтение` — `Отдать приоритет времени SELECT-запросов.`
- `Быстрее вставка` — `Сильнее учитывать скорость загрузки данных.`
- `Лучше сжатие` — `Сильнее учитывать итоговый размер данных.`

Then subsection `Жёсткие ограничения` and helper:
`Необязательно. Оставьте поле пустым, если ограничение не требуется.`

Fields each have `%` adornment:

1. `Максимальный рост хранения`.
2. `Максимальное замедление INSERT`.
3. `Минимальное ускорение SELECT`.

Reject non-finite numbers. Preserve the backend's documented numeric semantics;
do not invent a 0–100 clamp. Optional empty fields are omitted, not serialized as
zero. No scoring expression editor, variable editor, direction selector, or
per-phase formula overrides.

## 13. Validation, errors, and draft behavior

- Show field errors below the owning input, with aria-describedby/aria-invalid.
- A collapsed panel containing an invalid field opens automatically on validation.
- Next focuses the first invalid field and stays on the owning step.
- Save validates every step, then navigates to the earliest invalid one.
- Require at least one effective optimization rule/alternative; iteration order
  alone is not an optimization target.
- Blank added rows are errors, not silently dropped configuration, except an
  explicitly removed row. Whitespace normalization must be deterministic.
- Rules require source type and effective alternatives; index candidates require
  type plus valid integer granularity. Unknown document keys are rejected.
- Preserve unsaved values across switching panels, steps, and procedure choices.
- Removing a rule affects only that rule; removing a candidate affects only it.
- Do not send network writes on each keystroke.
- API errors appear in an ADQM Alert with a retryable Save action and the draft intact.
- While saving: show `Сохранение…`, block duplicate submission, and freeze draft
  mutation. A timeout must not automatically resend an ambiguous command.
- HTTP 202 is acknowledgement only. Catalog updates and successful navigation
  must follow the durable authoritative WebSocket update.
- Match a saved update to the submitted configuration/revision or command identity,
  not just the template name. The current name-only match is insufficient.
- If the stream disconnects while waiting, show a recoverable status. Do not leave
  the form permanently disabled with no explanation or reconciliation path.

## 14. Responsive and accessibility requirements

At desktop widths, retain the centered 1080px maximum. At 760px and below:

- Form padding 20px; at very narrow widths 16px if needed.
- Keep four equal stepper items, short readable labels, and 32px circles.
- All field grids and procedure cards become one column.
- Candidate row actions move below their inputs if needed.
- Footer wraps without reordering primary and cancel meanings.
- Accordion titles wrap; counts must not force horizontal overflow.
- Long type/index expressions wrap or scroll within their field, never the page.

Keyboard: every control is reachable, focus is visible, disclosure works with
Enter/Space, radio groups support arrow navigation, error focus is predictable.
Use meaningful accessible labels for icon-only delete buttons including row context.
Verify at 1440px, 1024px, and approximately 390px width, and with both supported themes.

## 15. API and persistence work required for real editors

Current schema v1 contains boolean rule flags. It cannot persist the settings above.
Do not implement a visually functional form that silently discards its fields.
Introduce a reviewed schema version 2 before wiring production saves.

Recommended shape (resolve names in ADR before coding):

```text
StrategyTemplateV2
  schema_version: 2
  procedure: combined | sequential | phased
  search_space:
    column_rules: explicit type rules
    codec_rules: explicit codec rules
    index_rules: explicit index rules
    order_by_rules: optional first column + candidates
    table_index_granularity_values: positive integer alternatives
  search_controls:
    column_iteration_order: optional column → priority mapping
  budget: typed search and measurement limits
  scoring: priority + optional finite percentage constraints
```

Use real rule meanings from src/models.py as requirements. Do not import that
legacy implementation into new backend packages. Define explicit boundary models.
Keep selectors, type alternatives, codec chains, and index parameter documents
separate. Avoid the unfinished generic `alternatives` draft if it obscures contracts.

Version transition:

1. Existing v1 configurations and historical benchmark snapshots remain intact.
2. Bootstrap/events return stored document versions consistently.
3. New templates use v2. Editing v1 opens a v2 draft with a visible explanation:
   `В этой стратегии сохранены только переключатели. Настройте конкретные правила перед сохранением.`
4. Do not invent old rules: boolean flags do not contain candidate values.
5. Preserve old name, description, budgets, scoring, and mapped procedure in the draft.
6. Explicit save persists validated v2. Existing benchmark snapshots stay unchanged.
7. New benchmark saves copy the selected template's exact configuration version.
8. Do not rewrite old event payloads to make them appear to have always been v2.

The existing local `/api/v1/runs` endpoint currently reads source table and sandbox,
copies the table, and marks a result. It does NOT consume strategy_snapshot/config.
Therefore this task can prove configuration editing/persistence, not optimization
execution. Do not use that table-copy endpoint as evidence that these rules work.
Connecting a real runtime requires a separate authorized and verified vertical slice.

## 16. Implementation order for the next model

1. Read instructions, this document, current source, and git diff. Preserve dirty work.
2. Correct/complete ADR-0004 and the older wizard spec to match this document.
   Mark old implementation-plan sections superseded where they still describe five
   mutually exclusive methods, fixed pipelines, or boolean-only rule configuration.
3. Define v2 boundary models and versioned read/write handling. Add focused failing
   tests for nonempty rules, invalid candidates, and immutable old snapshots.
4. Define frontend typed draft, parser/serializer, validation, and v1-to-draft
   conversion. Keep procedure separate from search-space fields.
5. Replace old method cards/switches on the combined step with the panels described
   here. Reuse existing pure rule knowledge; use ADQM for all product controls.
6. Wire budget applicability, final validation, and reliable save reconciliation.
7. Add scoped styles; check actual component DOM instead of guessing selectors.
8. Run frontend and API contract checks. Use real disposable infrastructure for
   integration proof, never mocked persistence or fabricated execution results.
9. Verify browser create/edit, responsive layouts, and both themes. Fix defects.
10. Update documentation with verified behavior and clearly identify any remaining
    runtime limitations. Report changed files and checks. Do not commit/deploy unless
    separately authorized.

## 17. Acceptance checklist

- [ ] Exactly four steps, correct numbering and final-step-only Save/Create.
- [ ] Search procedure and optimization editors are on the same second step.
- [ ] Types and codecs are independently configurable, including multiple rules.
- [ ] Index type parameters and granularity round-trip without loss.
- [ ] ORDER BY candidates and table granularity can coexist with other dimensions.
- [ ] Column iteration order is labeled accurately and separated from physical design.
- [ ] Procedure group contains only the three search procedures, with single selection.
- [ ] No persistent summary strip, right summary sidebar, technical ID, or workload fields.
- [ ] All product controls use ADQM; local assets only; light/dark are readable.
- [ ] All fields survive Back/Next, collapsed panels, and explicit save/reopen.
- [ ] New blank rows cannot silently create an ineffective rule.
- [ ] Invalid values block progression with an error at the correct field/step.
- [ ] Existing v1 templates show conversion guidance; no invented candidate defaults.
- [ ] v2 API create/update, bootstrap, and events carry equivalent configuration.
- [ ] Editing a template does not mutate existing benchmark snapshots.
- [ ] Duplicate clicks do not issue duplicate saves; disconnects do not hang silently.
- [ ] Desktop/mobile layouts have no clipped controls or horizontal page overflow.
- [ ] No unsupported optimizer-execution claim is made.

Commands from `apps/config_editor_ui`:

```sh
npm run check:strategy-template
npm run check:ui-kit
npm run check:roundtrip
npm run typecheck
npm run build
git diff --check
```

API checks must include valid v2 round trips; unknown keys; invalid/empty type,
codec, and index candidates; noninteger/zero granularity; duplicate column priority;
empty effective search space; old snapshot preservation; and event/bootstrap parity.
Run on Python 3.12 with the repository's approved dependencies. Do not claim tests
passed merely because the older v1 test script passed.

## 18. Suggested starting instruction

Implement this document in the current Benchmark Studio editor. Preserve the user's
chosen option-B layout and four-step flow. Replace the mixed method choices and
boolean-only switches with independent, persistable rule editors, and keep Top-N
as search procedure. Inspect unfinished drafts critically. Complete the versioned
API contract and verification before claiming the page is finished. Preserve dirty
work, do not deploy or commit without authorization, and do not claim the current
table-copy run endpoint executes the new configuration.
