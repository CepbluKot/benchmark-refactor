# Strategy editor: color cues and guided alternatives

## 1. Deliverable and authority

This is an implementation handoff, requested on 2026-09-22. It describes proposed
work; it is not evidence that autocomplete or database capability checks exist.
The current task produces documentation only. Do not implement, deploy, commit,
or replace the existing editor merely because this document exists.

User requirements:

- Keep the strategy editor design the user already likes.
- Make colors useful for recognizing sections and actions.
- Make types, codecs, index alternatives, and similar inputs understandable
  without requiring users to remember syntax.
- Add a backend facility that supplies applicable choices not already selected.
- Provide enough implementation detail for a less capable coding model.

The concrete layouts, timings, endpoint names, and limits below are recommended
design decisions. They are not claims of current backend behavior. This document
supersedes older handoffs only for alternative entry, color guidance, and suggestions.
Preserve their four-step flow, independent dimensions, and separate search procedure.
Implement both Russian and English using the existing global language choice.

## 2. Read these files first

- [Repository rules](../../AGENTS.md)
- [Execution workflow](../../docs/AI_EXECUTION_WORKFLOW.md)
- [Original editor handoff](strategy-editor-page-handoff.md)
- [Scoring handoff](strategy-scoring-page-handoff.md)
- [Template contract](../../docs/adr/0003-strategy-template-contract.md)
- [Independent dimensions ADR](../../docs/adr/0004-independent-strategy-dimensions.md)
- [Page](../../apps/config_editor_ui/src/pages/StrategyEditorPage.tsx)
- [Dimensions editor](../../apps/config_editor_ui/src/components/StrategyDimensionsEditor.tsx)
- [Dimensions types](../../apps/config_editor_ui/src/strategies/dimensions.ts)
- [Template serialization](../../apps/config_editor_ui/src/strategies/model.ts)
- [Frontend API](../../apps/config_editor_ui/src/control/api.ts)
- [Current Control API](../../apps/realtime_control_api/src/realtime_control_api/main.py)

Read the ADQM library documentation at
`/home/oleg/Documents/Codex/2026-09-11/new-chat/work/adqm_design_system-repo/react-ui/README.md`.
Use its components and supported themes. Extend its source for a missing accessible
combobox; regenerate the local package. Never patch generated bundles or node_modules.

### Verified starting point and prerequisite

At inspection, the frontend uses v2 `config.search_space` with `column_types`,
`codecs`, `skip_indexes`, `order_by`, `column_order`, and
`table_index_granularity_values`. Types/codecs/ORDER BY use multiline textareas.
Rules currently use array indexes as React keys. The frontend has uncommitted
localization changes; preserve them and unrelated work.

The inspected Python `StrategyTemplateConfig` still accepts only schema version 1
with boolean `rules`. Therefore v2 persistence is a prerequisite, not an existing
verified capability. ADR-0004 also calls the field `dimensions`, while the actual
frontend wire field is `search_space`. Resolve that discrepancy in the ADR and
validated DTOs before implementing autocomplete. Use `search_space` consistently;
do not invent a third representation or silently downgrade v2 on save.

The current run endpoint copies a table. Suggestions do not turn it into an
optimizer. Do not claim measured improvements, successful conversion, or execution
support merely because a catalogue entry is shown.

## 3. Preserve the page structure

Keep the shell, breadcrumb, centered card, and four steps:

`Basics → Search settings → Search budget → Scoring`

Do not restore the rejected summary strip or add a new sidebar. Step 2 contains
all dimension editors and the separate combined/sequential/phased procedure choice.
Column iteration order belongs to procedure configuration; it is not physical ORDER BY.
Changing procedures must never clear configured dimensions.

At desktop widths, keep the existing card max-width around 1080px. Use 24–32px
body padding, 24px between panels, 16px between fields, 8px between chips. At narrow
widths use 16–20px padding and one column. No horizontal page scrolling at 360px.

## 4. Color language

Use two distinct, consistent meanings: section accents identify WHAT is being
edited; action/status tokens identify WHAT WILL HAPPEN. Do not give every button
inside a purple section a purple action meaning.

| Role | Color treatment | Additional non-color cue |
| --- | --- | --- |
| Column types | Indigo/violet accent | Type icon + title |
| Codecs | Teal/cyan accent | Compression icon + title |
| Skip indexes | Blue accent | Index icon + title |
| ORDER BY | Muted violet accent | Ordered-list icon + title |
| Table granularity | Slate/blue accent | Grid icon + title |
| Procedure/column iteration | Neutral surface | Flow/order icon + title |
| Add alternative | Theme accent outline or subtle fill | Plus + explicit verb |
| Next/Create/Save | Existing primary accent fill | Action text, arrow for Next |
| Back/Cancel/Edit | Neutral secondary/tertiary | Explicit text |
| Remove | Danger text/icon; subtle danger hover | Remove label |
| Validated/completed | Success token | Check + status text |
| Needs checking | Warning token | Warning icon + explanation |
| Invalid | Danger token | Error text linked to field |

Implement semantic aliases such as `--strategy-types-accent` and
`--strategy-codecs-accent` on the editor wrapper. Derive them from inspected ADQM
palette tokens; if absent, add a reviewed light/dark pair to the design system.
Do not scatter literal colors through JSX or override the global theme accent.

Panel header: 3px accent inset line, 32px tinted icon tile, title, neutral count
badge, chevron. Tint only the header/icon/chips: approximately 8–12% accent mixed
into the theme surface, never a saturated full-card background. Body stays neutral.
Use text contrast >=4.5:1, meaningful control/focus contrast >=3:1. Verify both
themes; alpha alone does not prove contrast. Error borders override decorative
section borders while an error is present. Focus uses a visible theme focus ring.

Counts are factual: `2 rules · 4 alternatives`; an empty section says
`Not configured`. Green must not imply measured performance or data compatibility.
No rainbow stepper: active step uses primary, completed steps check marks, future
steps neutral. Scoring preset cards keep this same selection treatment.

## 5. Step 2 wireframe and default state

```text
Search settings
Configure alternatives independently, then choose the search procedure.

Generic template · Choices are checked when applied to a benchmark.

│ [Type icon] Column types             1 rule · 2 alternatives   ▾
│ Rule 1                                         Remove rule
│ Source type [String           ▾]  Column name [Optional      ]
│ Alternatives
│ [LowCardinality(String)  Edit ×] [FixedString(…)  Edit ×]
│ [+ Add type]                         [Advanced text entry]
│ [+ Add rule]

│ [Codec icon] Codecs                 Not configured            ▸
│ [Index icon] Skip indexes           Not configured            ▸
│ [Order icon] ORDER BY               Not configured            ▸
│ [Grid icon] Table granularity       Not configured            ▸

Search procedure
[Combined] [Sequential Top-N] [Phased Top-N]
[Column iteration order ▸]

Cancel                                         Back  Continue →
```

Wireframe values are examples only. Do not insert them into a user's draft.
Open Types for a new empty draft; for editing open the first configured section.
Multiple panels may remain open. Toggling a panel never enables/disables a rule.
Use stable client row IDs, retained while editing/reordering; exclude IDs from
serialized strategy documents. A new rule starts incomplete, not prefilled with
an arbitrary source type or codec.

## 6. Shared alternative picker

Clicking `Add type`, `Add codec alternative`, or `Add index` opens an anchored
picker inside that rule. Desktop width 420–520px, constrained to viewport; on
mobile full available card width. Keep it above the footer and within the viewport.

From top to bottom:

1. Search input with a concrete label, e.g. `Find a codec`.
2. Context line: `For String · Generic catalogue` or actual verified context.
3. Suggestion list, maximum 20 entries per response and approximately 320px scroll.
4. Secondary `Enter manually` action.

An entry has readable name, one-line purpose, parameter summary, and applicability
badge. Show canonical syntax in smaller monospace text. No unexplained IDs.
Do not call entries "best" or "faster"; catalogue order is not measured ranking.
Sort supported entries first, then conditional entries, then label, then stable ID.
Typing searches names, descriptions, syntax, and curated RU/EN aliases.

Selecting a parameterless item explicitly adds one alternative. A parameterized
item opens a small inline form with labeled fields and `Add alternative`/`Cancel`.
Defaults may be displayed but commit only on Add. Hover/focus never adds anything.
Do not automatically choose the first result after typing.

Selected alternatives appear as wrapping chips or compact rows: syntax, edit
button, remove button. The selected list remains outside the combobox listbox.
Screen-reader labels include the value (`Remove ZSTD(3)`). Long syntax wraps or
opens an accessible detail view; do not hide indispensable parameters in tooltips.

Keyboard: Tab reaches the search field; arrows navigate results; Enter selects the
highlighted result; Escape closes and returns focus; Tab leaves without selecting.
Use combobox/listbox/option semantics and `aria-activedescendant`; no interactive
buttons nested in an option. Announce result count/loading/error through a polite
live region. Do not remove a selected chip on Backspace from an empty search field.

### Duplicate scope and immediate feedback

"Not yet selected" means the same alternative in the SAME rule/dimension.
It does not mean not used anywhere in the application, another rule, or past runs.
The same codec may legitimately appear in two rules with different source matchers.
Backend canonicalization determines equality. Exclude committed alternatives from
suggestions; still guard Add and final save against duplicates. A just-removed
alternative becomes eligible again. If the query names an existing selection,
show `Already added` separately, with no active Add action.

Editing an alternative excludes the other alternatives but not its own identity.
Index identity includes type, all parameters, and granularity. Codec chain identity
includes ordered members and their parameters. Do not lowercase arbitrary type
expressions, sort codec chains, strip quoted whitespace, or split strings on commas.

## 7. Domain-specific builders

### 7.1 Column types

Source type is a searchable selector backed by catalogue items, with explicit
manual expression entry. Optional source context can supply actual column types.
Target alternatives use the shared picker. Parameterized types expose required
parameters with units and validated constraints. Nested wrappers are structured
only where the catalogue's grammar supports them; otherwise preserve raw text.

Show `Requires data validation` for narrowing/range/nullability conversions.
Metadata support does not prove all values can be converted. The suggestion service
must not scan source data or attempt casts on each keystroke.

### 7.2 Codecs and chains

One selected alternative is ONE complete codec chain. Render each alternative as
a row, for example `[Delta ▾] → [ZSTD · level 3 ▾] [Edit] [Remove]`.
Offer `Single codec` and `Codec chain` within the picker; these are entry modes,
not mutually exclusive strategy modes.

Builder: ordered codec tiles, parameter inputs under selected tile, plus
`Add next codec`, `Move left`, `Move right`, `Remove codec`. Keyboard buttons are
required even if drag-and-drop is later added. Validate a whole proposed chain,
including order and mutual exclusions, on the backend. Only offer next members
allowed by the current prefix and context. Do not assume arbitrary combinations work.

`Delta, ZSTD(3)` is one alternative. `ZSTD(1)` and `ZSTD(3)` are two alternatives.
Use server-provided parameter constraints; examples here do not establish support,
valid ranges, universal compatibility, or recommended levels.

### 7.3 Skip indexes

Choose index family, then show its schema-driven parameter form. Granularity is a
separate positive-integer field with `granules` unit. Display the result as one
row with syntax and granularity; editing returns to the same parameter form.
Explain: index GRANULARITY and table index_granularity are different settings.
Compatibility may depend on engine, source type, and workload. Do not claim an
index will accelerate an unknown query workload.

### 7.4 ORDER BY

Each candidate is an ordered set of column/expression tokens, not comma-separated
alternatives. Add column uses source metadata only when a validated source context
exists. Otherwise offer manual column/expression entry and state why no column
names are suggested. Never invent columns from a sample dataset.
Provide move-left/right and remove actions. `Add another key` starts a separate
candidate. Preserve the optional existing first-column field and its established
contract; do not reinterpret it as another independent candidate.
Advanced expressions need a real backend parser/allowlist and final validation.
No execution, DDL, or arbitrary SQL probes during editing.

### 7.5 Table granularity and iteration order

Granularity: compact numeric chips and `Add value`. Suggested values come from the
catalogue policy; label them choices, not empirically optimal settings. Empty new
input remains empty. Reject zero, negatives, fractions, non-finite values and
duplicates. Show `rows per table granule` next to the input.

Iteration order: ordered column rows with move-up/down actions and readable
positions. Reordering recalculates unique positive positions. Suggestions remove
columns already listed here. This changes exploration order, not physical sorting.

### 7.6 Advanced/manual entry

Keep an explicit escape hatch for expert users and existing values. Open raw entry
in a disclosure or small dialog; show a preview and errors before Apply. Newline
is the delimiter only for bulk alternatives, never comma. Explain codec-chain and
ORDER BY comma semantics next to the field. Reject blank interior candidates rather
than silently altering intended values. Apply atomically; Cancel preserves the draft.

Unknown historical expressions remain visible/editable as raw text. Never replace
them with a default or drop them while converting to chips. Server validation reports
unsupported/unknown status explicitly; it does not silently accept an invalid value.

## 8. Backend ownership and boundaries

Implement a separate logical suggestion/catalogue module behind the Control API;
do not require another deployed service, database, LLM, broker, or public network.
It is deterministic and read-only. Store the curated catalogue as pinned local data
with a version/hash; no catalogue CRUD screen is needed for this task.

The Control API validates the request envelope, applies bounds, and routes to a
descriptor. Backend-specific compatibility, canonicalization and grammar belong to
the ClickHouse owner. Do not add ClickHouse branches to generic experiment core or
import executable plugin code into the Control Service. In the current product
surface, consume declarative pinned descriptor data. If live semantic checking
requires executable plugin behavior, use the approved out-of-process boundary;
do not improvise a new runtime protocol in this task.

Before coding public contracts, add a proposed ADR and complete the repository's
ADR process for the versioned catalogue/context contract and v2 alignment. Keep
catalogue version separate from strategy document schema version. Read the target
architecture's plugin, capability, and immutable-manifest sections at that point.

No credentials or arbitrary host/table/SQL locators are accepted by this endpoint.
Context references resolve server-side to approved metadata. Source reads are
bounded and read-only through the owning adapter; no source writes or test DDL.

### Generic versus source-aware context

Default: generic global template. A declared source type filters the curated
catalogue, but every result states what remains unverified. Missing server version
must never mean "supports everything".

Source-aware suggestions are a future benchmark/source-context extension, not a
required new selector in this global strategy editor. Do not add source selection
to this implementation. The following describes the reserved boundary only.
A future `Check against a source` uses an existing source ID and a server-issued
opaque object reference. The current `/sources/{id}/tables` returns strings, so it
cannot itself supply a trusted metadata reference. Add a bounded metadata discovery
contract first or leave source-aware mode unavailable with a clear explanation.
Never fabricate a capability fingerprint in the frontend.

Context affects advice only; it does not bind a global template permanently to a
source, filter strategies by workspace, or modify a benchmark snapshot. Switching
context retains selections and marks them for revalidation. Check again against
the actual benchmark source before execution; an editor check is not permanent proof.

## 9. Proposed suggestion contract

`POST /api/v1/strategy-options/suggest`, HTTP 200; read-only query despite POST.
POST avoids putting structured drafts and column names in query strings/access logs.
It emits no mutation event and changes no persistent product state. REST suggestions
are ephemeral editor assistance, not authoritative strategy state. Actual create/
update still returns command acknowledgement and is applied through durable events.
Do not introduce polling, SSE, or per-keystroke WebSocket business events.

Request skeleton (field names are normative for the proposed contract):

```json
{
  "schema_version": 1,
  "request_id": "editor-generated-correlation-id",
  "backend_id": "clickhouse",
  "kind": "codec_alternative",
  "locale": "en",
  "query": "zstd",
  "context": {"mode": "generic"},
  "matcher": {"by_type": "String"},
  "selected": [{"kind": "codec_alternative", "expression": "ZSTD(1)"}],
  "chain_prefix": [],
  "limit": 20,
  "cursor": null
}
```

Use discriminated request/value unions, not arbitrary dictionaries. Kinds:
`source_type`, `column_type`, `codec_alternative`, `codec_member`, `skip_index`,
`order_by_column`, `iteration_column`, `table_granularity`.
This slice accepts only generic context. A future source mode would use
`{mode: "source", source_id, object_ref, metadata_revision}` after its metadata
contract is implemented; reject that mode now with a typed unsupported-context error.
`matcher` is required only for type/codec/index alternatives. `chain_prefix` is
valid only for `codec_member`. For index selection include expression plus
`granularity`; for granularity values include an integer; for columns use a trusted
column reference in source mode or explicit manual identifier in generic mode.

Response skeleton (illustrative fixture, not runtime data):

```json
{
  "schema_version": 1,
  "request_id": "editor-generated-correlation-id",
  "catalogue_revision": "content-hash",
  "context_revision": null,
  "items": [{
    "id": "codec.zstd",
    "kind": "codec_alternative",
    "label": "ZSTD",
    "description": "Compression codec with a configurable level.",
    "canonical_value": null,
    "requires_parameters": true,
    "parameter_schema_ref": "codec.zstd.parameters",
    "applicability": "conditional",
    "reason_codes": ["SOURCE_CAPABILITIES_UNVERIFIED"]
  }],
  "next_cursor": null
}
```

Add typed parameter descriptors to the response under `parameter_schemas`, keyed
by reference. Allowed field kinds: integer, finite number, enum, bounded string,
and catalogue reference. Include label, help, required, unit, supported bounds,
and optional explicit default. Do not execute schema scripts or fetch remote refs.
`canonical_value` is populated only for a complete instantiable alternative.
Families remain discoverable when one parameterization has already been selected;
excluding ZSTD(1) must not hide all possible ZSTD values.

Applicability: `supported`, `conditional`, `unsupported`, `unknown`. `supported`
means only descriptor/capability compatibility, not performance, conversion safety,
or measurement success. Default list excludes unsupported items. An optional
`Show unavailable` disclosure may display disabled entries with reason text.
Unknown entries are never presented with a green success badge.

Limits: query <=128 characters; limit 1–50 (default 20); <=200 selected alternatives;
expression <=2048 characters; chain <=16 members; total request <=64 KiB.
Use a deterministic parser with depth/complexity bounds. Cursor binds query,
kind, matcher, selections, locale, catalogue and context revisions. Reject mismatches
with `409 OPTIONS_CONTEXT_CHANGED`; do not return a misleading mixed page.

Errors: 422 malformed input with field paths; 404 unknown approved context reference;
409 stale revision; 503 unavailable required capability service. Include stable
error codes and localized safe text. Never return exception stacks, credentials,
full submitted documents, connection URLs or DDL in errors/logs.

## 10. Canonicalization and validation contract

Provide `POST /api/v1/strategy-options/validate`, also read-only, accepting a bounded
list of typed proposed alternatives, matcher, context and catalogue revision.
Return per-input canonical value/key, applicability, and field-level issues. Use
the same validator for suggestions, manual input, and final strategy save.

For editing, return parser-supported structured fields alongside canonical text;
if an old expression cannot be decomposed losslessly, retain the raw editor.
Never use `eval`, dynamic import, shell execution, or real query execution to parse.

Validation is layered: syntax/parameters; canonical duplicate detection; declared
type compatibility; known server/engine capabilities; separate data-dependent
checks. Distinguish failures from checks not performed. A rule spanning multiple
columns is conditional unless compatibility holds for all matched columns under
the available metadata. A type change can affect codec applicability: where the
search procedure's effective input type is unknown, report a condition rather than
pretend the original type proves every generated combination valid.

Saving v2 revalidates the complete document, regardless of cached suggestion state.
Unknown/unsupported syntax blocks save with a field-level explanation. Valid generic
rules may be saved with explicit source-unverified warnings; execution admission
must still fail closed on unsupported capabilities and unsafe transformations.
No failure or missing capability becomes a numeric score or a fallback recommendation.

## 11. Frontend request lifecycle

- Debounce search by 200ms. Opening a picker may request immediately.
- One AbortController per picker; abort on context/query change and unmount.
- Associate each response with current request ID and a complete context key.
  Discard late responses even if abort did not stop the server request.
- Changing matcher, chain prefix, selected alternatives or locale invalidates the
  results. Never reset other rules or overwrite unsaved input.
- Keep a small in-memory cache: <=50 entries, 60-second TTL, full request key plus
  catalogue/context revision. Do not persist source metadata in localStorage.
- Do not query on a timer. No source capability probe per keystroke: use revisioned
  metadata and bounded server-side reuse.
- Loading shows a short skeleton; failure shows Retry and manual entry. Existing
  selections remain usable. An empty result is not a network error.
- Before adding from a stale result, validate/canonicalize against the current
  context. Backend is final authority; client dedup merely improves feedback.

State presentation:

| State | RU | EN |
| --- | --- | --- |
| Loading | Ищем варианты… | Finding alternatives… |
| No matches | Ничего не найдено. Измените запрос. | No matches. Change your search. |
| Already selected | Уже добавлено | Already added |
| No source context | Проверим при выборе источника | Check when a source is selected |
| Conditional | Требует проверки | Requires checking |
| Network failure | Не удалось загрузить варианты | Could not load alternatives |
| Retry | Повторить | Retry |
| Manual | Ввести вручную | Enter manually |
| Add type | Добавить тип | Add type |
| Add chain | Добавить цепочку кодеков | Add codec chain |
| Edit alternative | Изменить вариант | Edit alternative |

Localize headings, descriptions, reasons, parameter hints, counts, validation and
accessible names. Technical SQL/type/codec identifiers remain unchanged. User names
and descriptions are not translated. Language switching must preserve unfinished
parameter input and regenerate message text without dropping validation state.

## 12. Suggested file split and execution order

New filenames below are proposals; inspect current tree before creating them.

1. Contract prerequisite: align ADR-0004 and Python DTOs with frontend v2
   `search_space`, budgets and scoring. Add save/bootstrap/event/snapshot round-trip
   coverage. Do not synthesize missing alternatives when loading v1 records.
   Preserve command acknowledgements and correlate save completion with the
   acknowledged `command_id`, not a matching strategy name. Verify the existing
   [realtime contract](control_api_realtime_v1.md) before changing that path.
2. Record the option contract in a proposed ADR; define typed query/response DTOs,
   descriptor format, revisions, errors, capability ownership and context references.
3. Add current-surface `strategy_options/models.py`, `catalogue.py`, `service.py`
   and `routes.py` under the current Control API package. Keep backend-native
   descriptors at their owning boundary; do not duplicate the catalogue in JS.
4. Add `src/strategies/options.ts` for wire types and API methods accepting an abort
   signal; `useStrategyOptions.ts` for request lifecycle. No changes to event-based
   strategy ownership just to support suggestions.
5. Add `AlternativePicker`, `AlternativeChips`, `ParameterEditor`, and
   `CodecChainEditor` components. Reuse/extend ADQM. Replace textarea entry in
   `StrategyDimensionsEditor` progressively, retaining explicit advanced entry.
6. Add client identity and serialization helpers. Persist only the existing v2
   strategy fields. Picker query, expansion, row IDs, revisions and suggestion
   objects must not leak into saved configuration. A persisted provenance change
   requires its own explicit versioned contract, not accidental extra JSON fields.
7. Add scoped theme aliases and consistent actions in `styles.css`; reuse them on
   budget/scoring steps without redesigning their formulas or content.
8. Verify both locales/themes, keyboard flow, delayed responses and genuine API
   integration. Update product docs with actual implemented scope and evidence.

No database migration is needed merely for a bundled read-only catalogue. If the
implementation adds stored context records or changes persistence, document the
dedicated migration before coding it. Do not add worker/startup ad-hoc migrations.

## 13. Acceptance scenarios

1. Create a strategy; open Types; choose a source type; pick one target alternative.
   It appears immediately as a chip and is absent from the next suggestion query.
2. Try the same value with equivalent accepted syntax: duplicate is blocked with
   readable feedback. The same alternative in another distinct rule is permitted.
3. Add a parameterized type; Cancel changes nothing; invalid parameters cannot be
   added; a valid explicit Add creates exactly one candidate.
4. Build `Delta, ZSTD(3)` where the descriptor permits it. It serializes as one
   alternative. Add `ZSTD(1)` separately. Edit/reorder without losing parameters.
5. Remove a middle rule: focus and every other rule's matcher/values stay correct.
6. Add the same index with different granularity: retained as two distinct choices.
7. Add a two-column ORDER BY key: one candidate, no comma splitting. Move columns
   with keyboard controls. Iteration order remains a separate concept.
8. Change the source-type matcher or chain prefix while a request is delayed:
   late results are ignored; old selections are retained and rechecked. Unknown
   capability is not success. Source-mode requests receive an explicit unsupported
   response until the separate source-context extension exists.
9. Switch RU/EN while a parameter form is open: preserve input and selected items;
   all explanatory/error/accessible text follows the active locale.
10. Fail suggestion requests: retain draft, show Retry/manual entry, never populate
    runtime from a mock list. No automatic benchmark/run/source-check command occurs.
11. Save a complete v2 strategy: acknowledgement alone does not update catalogue
    state; event and fresh bootstrap contain the same canonical configuration.
    Edit/reopen preserves all rules. Existing benchmark snapshots stay unchanged.
12. Inspect 360px and desktop widths in light/dark themes; no overlapping popover,
    clipped footer, inaccessible control, or color-only status distinction.
13. Load unsupported historical raw expressions: visible intact, never rewritten
    into a different type/chain; saving reports specific issues when appropriate.
14. Request unknown IDs, oversized/deep expressions, expired cursors or malicious
    metadata references: bounded typed errors, no SQL execution or secret leakage.

Required evidence: focused deterministic tests for canonicalization, dedup scope,
parameter constraints, chain order and stale-response handling; real API tests for
metadata/context and v2 persistence using disposable approved infrastructure.
Do not treat fixtures as proof that a live database supports a transformation.
Run `npm run check:ui-kit`, `npm run typecheck`, `npm run build` in the frontend,
and applicable Python 3.12 tests. Add meaningful RU/EN interaction coverage; the
current minimal i18n contract check alone is insufficient. No deployment/commit is
implied by completing these checks; if later requested, use `:local` image tags.

## 14. Copyable instruction for the implementing model

Implement this handoff in dependency order. Preserve the current four-step design
and all unrelated changes. First resolve the inspected frontend-v2/backend-v1
contract gap and document the suggestion API decision. Build a pinned, read-only
backend catalogue and schema-driven accessible pickers. Use restrained section
accents plus consistent semantic action colors. Replace raw multiline alternative
entry with chips and parameter/chain editors, retaining lossless advanced input.
Deduplicate within the current rule using server canonical identities. Treat
generic and verified source context differently. Test actual persistence and UI
behavior in both languages and themes; report remaining limits truthfully.
